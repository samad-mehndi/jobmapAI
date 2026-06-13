import os
import time
import httpx
import psycopg2
from fastapi import APIRouter, Header, HTTPException
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()
DB_URL = os.getenv("DATABASE_URL")
JSEARCH_KEY = os.getenv("JSEARCH_API_KEY")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "dfw-jobmap-admin-2026")

SEED_QUERIES = [
    "Software Engineer in Dallas TX",
    "Full Stack Developer in Plano TX",
    "Backend Engineer in Dallas TX",
    "AI Engineer in Dallas TX",
    "Data Engineer in Irving TX",
    "Frontend Engineer in Dallas TX",
    "DevOps Engineer in Dallas TX",
    "Machine Learning Engineer in Dallas TX",
    "Python Developer in Dallas TX",
    "React Developer in Plano TX",
]

def geocode(company: str, city: str, state: str) -> tuple:
    try:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "dfw-jobmap-dev/1.0"}
        r = httpx.get(url, headers=headers,
            params={"q": f"{company}, {city}, {state}", "format": "json", "limit": 1}, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
        r = httpx.get(url, headers=headers,
            params={"q": f"{city}, {state}", "format": "json", "limit": 1}, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return 32.7767, -96.7970


@router.post("/admin/seed")
def seed_jobs(x_admin_secret: str = Header(...)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")

    conn = psycopg2.connect(DB_URL)
    total = 0

    for query in SEED_QUERIES:
        try:
            r = httpx.get(
                "https://jsearch.p.rapidapi.com/search",
                headers={
                    "X-RapidAPI-Key": JSEARCH_KEY,
                    "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
                },
                params={
                    "query": query,
                    "page": "1",
                    "num_pages": "1",
                    "date_posted": "month"
                },
                timeout=15
            )
            jobs = r.json().get("data", [])
        except Exception:
            jobs = []

        for job in jobs:
            company_name = job.get("employer_name", "Unknown")
            city = job.get("job_city") or "Dallas"
            state_code = job.get("job_state") or "TX"
            time.sleep(1)
            lat, lng = geocode(company_name, city, state_code)

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO companies (name, address, location)
                    VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                    ON CONFLICT (name) DO UPDATE SET location = EXCLUDED.location
                    RETURNING id
                """, (company_name, f"{company_name}, {city}, {state_code}", lng, lat))
                row = cur.fetchone()
                if not row:
                    cur.execute("SELECT id FROM companies WHERE name = %s", (company_name,))
                    row = cur.fetchone()
                company_id = row[0] if row else None

                cur.execute("""
                    INSERT INTO jobs
                        (company_id, title, description, salary_min, salary_max,
                         remote_type, source_url, source, posted_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    company_id,
                    job.get("job_title"),
                    (job.get("job_description") or "")[:5000],
                    job.get("job_min_salary"),
                    job.get("job_max_salary"),
                    "remote" if job.get("job_is_remote") else "onsite",
                    job.get("job_apply_link"),
                    "jsearch"
                ))
            conn.commit()
            total += 1

    conn.close()
    return {"status": "done", "jobs_seeded": total}


@router.post("/admin/parse-embeddings")
def parse_embeddings(x_admin_secret: str = Header(...)):
    """Generate embeddings for all jobs that don't have one yet"""
    import json
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_core.messages import HumanMessage

    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    emb_model = OpenAIEmbeddings(model="text-embedding-3-small")

    conn = psycopg2.connect(DB_URL)
    from pgvector.psycopg2 import register_vector
    register_vector(conn)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, title, description FROM jobs
            WHERE embedding IS NULL AND description IS NOT NULL
        """)
        jobs = cur.fetchall()

    processed = 0
    failed = 0

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
            embedding = emb_model.embed_query(text)

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
            processed += 1
        except Exception as e:
            failed += 1
            continue

    conn.close()
    return {"status": "done", "processed": processed, "failed": failed}