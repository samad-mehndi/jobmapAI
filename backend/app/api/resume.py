import os
import json
import fitz
import psycopg2
import numpy as np
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv
from app.agents.resume_matcher import process_resume

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../..', '.env'))

router = APIRouter()
DB_URL = os.getenv("DATABASE_URL")
embeddings_model = OpenAIEmbeddings(model="text-embedding-3-small")
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


def parse_new_job_embeddings(job_ids: list[int]):
    """Generate embeddings for newly fetched jobs in background"""
    if not job_ids:
        return
    conn = psycopg2.connect(DB_URL)
    register_vector(conn)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, description FROM jobs
                WHERE id = ANY(%s) AND embedding IS NULL
            """, (job_ids,))
            jobs = cur.fetchall()

        for job_id, title, description in jobs:
            try:
                prompt = f"""Extract skills from this job. Return ONLY JSON:
{{"skills": ["skill1", ...], "seniority": "entry/mid/senior/lead", "remote_type": "remote/hybrid/onsite"}}
Title: {title}
Description: {(description or '')[:2000]}"""
                response = llm.invoke([HumanMessage(content=prompt)])
                raw = response.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                parsed = json.loads(raw.strip())
                skills = parsed.get("skills", [])
                seniority = parsed.get("seniority")
                remote_type = parsed.get("remote_type")

                text = f"{title} {' '.join(skills)} {(description or '')[:500]}"
                embedding = embeddings_model.embed_query(text)

                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jobs SET embedding = %s, seniority = %s, remote_type = %s
                        WHERE id = %s
                    """, (embedding, seniority, remote_type, job_id))
                    for skill in skills:
                        cur.execute("INSERT INTO skills (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (skill.lower(),))
                        cur.execute("SELECT id FROM skills WHERE name = %s", (skill.lower(),))
                        skill_row = cur.fetchone()
                        if skill_row:
                            cur.execute("INSERT INTO job_skills (job_id, skill_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                (job_id, skill_row[0]))
                conn.commit()
            except Exception as e:
                print(f"Error processing job {job_id}: {e}")
                continue
    finally:
        conn.close()


@router.post("/resume/match")
async def match_resume(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    contents = await file.read()
    try:
        pdf = fitz.open(stream=contents, filetype="pdf")
        resume_text = ""
        for page in pdf:
            resume_text += page.get_text()
        pdf.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {e}")

    if len(resume_text.strip()) < 50:
        raise HTTPException(status_code=400, detail="PDF appears empty or unreadable")

    result = process_resume(resume_text)

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    parsed_skills = result["parsed_skills"]
    target_roles = result["target_roles"]
    seniority = result["seniority"]
    resume_embedding = result["resume_embedding"]
    new_job_ids = result.get("fetched_job_ids", [])

    if new_job_ids:
        background_tasks.add_task(parse_new_job_embeddings, new_job_ids)

    conn = psycopg2.connect(DB_URL)
    register_vector(conn)

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    j.id, j.title, j.seniority, j.remote_type,
                    j.salary_min, j.salary_max, j.source_url,
                    c.name AS company_name,
                    c.lng, c.lat,
                    j.embedding,
                    ARRAY_AGG(s.name) FILTER (WHERE s.name IS NOT NULL) AS job_skills
                FROM jobs j
                JOIN companies c ON j.company_id = c.id
                LEFT JOIN job_skills js ON js.job_id = j.id
                LEFT JOIN skills s ON s.id = js.skill_id
                WHERE j.embedding IS NOT NULL
                AND c.lat IS NOT NULL
                GROUP BY j.id, c.name, c.lat, c.lng
            """)
            jobs = cur.fetchall()

        matches = []
        resume_vec = np.array(resume_embedding)

        for job in jobs:
            job_vec = np.array(job["embedding"])
            cosine_sim = float(np.dot(resume_vec, job_vec) / (
                np.linalg.norm(resume_vec) * np.linalg.norm(job_vec) + 1e-9
            ))
            job_skills_set = set(s.lower() for s in (job["job_skills"] or []))
            resume_skills_set = set(s.lower() for s in parsed_skills)
            overlap = len(resume_skills_set & job_skills_set) / len(job_skills_set) if job_skills_set else 0
            final_score = (0.6 * cosine_sim) + (0.4 * overlap)

            matches.append({
                "job_id": job["id"],
                "title": job["title"],
                "company_name": job["company_name"],
                "seniority": job["seniority"],
                "remote_type": job["remote_type"],
                "salary_min": job["salary_min"],
                "salary_max": job["salary_max"],
                "source_url": job["source_url"],
                "lat": float(job["lat"]) if job["lat"] else None,
                "lng": float(job["lng"]) if job["lng"] else None,
                "match_score": round(final_score * 100, 1),
                "matched_skills": list(resume_skills_set & job_skills_set)[:8],
                "missing_skills": list(job_skills_set - resume_skills_set)[:5]
            })

        matches.sort(key=lambda x: x["match_score"], reverse=True)

        return {
            "resume_skills": parsed_skills,
            "resume_seniority": seniority,
            "target_roles": target_roles,
            "total_jobs_scored": len(jobs),
            "new_jobs_fetched": len(new_job_ids),
            "matches": matches[:30]
        }

    finally:
        conn.close()