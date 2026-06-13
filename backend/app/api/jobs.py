import os
import math
import numpy as np
from fastapi import APIRouter, Query
from psycopg2.extras import RealDictCursor
import psycopg2
from langchain_openai import OpenAIEmbeddings
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../..', '.env'))

router = APIRouter()
DB_URL = os.getenv("DATABASE_URL")
embeddings_model = OpenAIEmbeddings(model="text-embedding-3-small")

def haversine_distance(lat1, lng1, lat2, lng2):
    """Calculate distance in miles between two lat/lng points"""
    R = 3959  # Earth radius in miles
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


@router.get("/jobs/map")
def get_jobs_map(
    lat: float = Query(32.9483),
    lng: float = Query(-96.7297),
    radius_miles: float = Query(40),
    role: str = Query(None)
):
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = """
                SELECT
                    c.id AS company_id,
                    c.name AS company_name,
                    c.lng,
                    c.lat,
                    COUNT(DISTINCT j.id) AS job_count,
                    (
                        SELECT JSON_AGG(
                            JSON_BUILD_OBJECT(
                                'title', j2.title,
                                'url', j2.source_url,
                                'seniority', j2.seniority,
                                'remote_type', j2.remote_type,
                                'salary_min', j2.salary_min,
                                'salary_max', j2.salary_max
                            )
                        )
                        FROM (
                            SELECT DISTINCT ON (j2.title)
                                j2.title, j2.source_url, j2.seniority,
                                j2.remote_type, j2.salary_min, j2.salary_max
                            FROM jobs j2
                            WHERE j2.company_id = c.id
                            ORDER BY j2.title
                        ) j2
                    ) AS jobs,
                    ROUND(AVG(j.salary_min)) AS avg_salary_min,
                    ROUND(AVG(j.salary_max)) AS avg_salary_max,
                    ARRAY_AGG(DISTINCT s.name)
                        FILTER (WHERE s.name IS NOT NULL) AS top_skills
                FROM companies c
                JOIN jobs j ON j.company_id = c.id
                LEFT JOIN job_skills js ON js.job_id = j.id
                LEFT JOIN skills s ON s.id = js.skill_id
                WHERE c.lat IS NOT NULL AND c.lng IS NOT NULL
            """
            params = []

            if role:
                query += " AND LOWER(j.title) LIKE %s"
                params.append(f"%{role.lower()}%")

            query += " GROUP BY c.id, c.name, c.lat, c.lng"
            cur.execute(query, params)
            rows = cur.fetchall()

        # Filter by radius in Python
        features = []
        for row in rows:
            dist = haversine_distance(lat, lng, float(row["lat"]), float(row["lng"]))
            if dist <= radius_miles:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(row["lng"]), float(row["lat"])]
                    },
                    "properties": {
                        "company_id": row["company_id"],
                        "company_name": row["company_name"],
                        "job_count": row["job_count"],
                        "jobs": row["jobs"],
                        "avg_salary_min": row["avg_salary_min"],
                        "avg_salary_max": row["avg_salary_max"],
                        "top_skills": (row["top_skills"] or [])[:8]
                    }
                })

        features.sort(key=lambda x: x["properties"]["job_count"], reverse=True)

        return {
            "type": "FeatureCollection",
            "features": features,
            "total": len(features)
        }
    finally:
        conn.close()


@router.get("/jobs/stats")
def get_jobs_stats():
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT s.name, COUNT(*) AS count
                FROM job_skills js
                JOIN skills s ON s.id = js.skill_id
                GROUP BY s.name ORDER BY count DESC LIMIT 10
            """)
            top_skills = cur.fetchall()

            cur.execute("""
                SELECT remote_type, COUNT(*) AS count
                FROM jobs WHERE remote_type IS NOT NULL
                GROUP BY remote_type
            """)
            remote_breakdown = cur.fetchall()

            cur.execute("""
                SELECT seniority, COUNT(*) AS count
                FROM jobs WHERE seniority IS NOT NULL
                GROUP BY seniority
            """)
            seniority_breakdown = cur.fetchall()

            cur.execute("""
                SELECT c.name, COUNT(j.id) AS job_count
                FROM companies c JOIN jobs j ON j.company_id = c.id
                GROUP BY c.name ORDER BY job_count DESC LIMIT 8
            """)
            top_companies = cur.fetchall()

        return {
            "top_skills": [dict(r) for r in top_skills],
            "remote_breakdown": [dict(r) for r in remote_breakdown],
            "seniority_breakdown": [dict(r) for r in seniority_breakdown],
            "top_companies": [dict(r) for r in top_companies]
        }
    finally:
        conn.close()


@router.get("/jobs/search")
def semantic_search(
    q: str = Query(...),
    lat: float = Query(32.9483),
    lng: float = Query(-96.7297),
    radius_miles: float = Query(40)
):
    import httpx
    import time
    import json
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_core.messages import HumanMessage

    query_embedding = embeddings_model.embed_query(q)

    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    j.id, j.title, j.seniority, j.remote_type,
                    j.salary_min, j.salary_max, j.source_url,
                    c.id AS company_id, c.name AS company_name,
                    c.lng, c.lat,
                    1 - (j.embedding <=> %s::vector) AS similarity
                FROM jobs j
                JOIN companies c ON j.company_id = c.id
                WHERE j.embedding IS NOT NULL
                AND c.lat IS NOT NULL AND c.lng IS NOT NULL
                ORDER BY j.embedding <=> %s::vector
                LIMIT 50
            """, (query_embedding, query_embedding))
            all_jobs = cur.fetchall()

        # Filter by radius and top similarity
        jobs = [j for j in all_jobs
                if haversine_distance(lat, lng, float(j["lat"]), float(j["lng"])) <= radius_miles]

        top_similarity = float(jobs[0]["similarity"]) if jobs else 0
        should_fetch = len(jobs) < 5 or top_similarity < 0.45

        if should_fetch:
            print(f"  Low results for '{q}' — fetching from JSearch...")
            jsearch_key = os.getenv("JSEARCH_API_KEY")
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            emb_model = OpenAIEmbeddings(model="text-embedding-3-small")

            title_response = llm.invoke([HumanMessage(content=
                f"Extract the core job title from this query. Return only the job title. Query: '{q}'"
            )])
            clean_title = title_response.content.strip()

            try:
                r = httpx.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers={
                        "X-RapidAPI-Key": jsearch_key,
                        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
                    },
                    params={"query": f"{clean_title} in Dallas TX", "page": "1", "num_pages": "1"},
                    timeout=15
                )
                new_jobs = r.json().get("data", [])
            except Exception:
                new_jobs = []

            new_job_ids = []
            for job in new_jobs:
                company_name = job.get("employer_name", "Unknown")
                city = job.get("job_city") or "Dallas"
                state_code = job.get("job_state") or "TX"

                time.sleep(1)
                geo_lat, geo_lng = 32.7767, -96.7970
                try:
                    geo_r = httpx.get(
                        "https://nominatim.openstreetmap.org/search",
                        headers={"User-Agent": "dfw-jobmap-dev/1.0"},
                        params={"q": f"{company_name}, {city}, {state_code}", "format": "json", "limit": 1},
                        timeout=10
                    )
                    results = geo_r.json()
                    if results:
                        geo_lat = float(results[0]["lat"])
                        geo_lng = float(results[0]["lon"])
                except Exception:
                    pass

                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO companies (name, address, lat, lng)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET lat = EXCLUDED.lat, lng = EXCLUDED.lng
                        RETURNING id
                    """, (company_name, f"{company_name}, {city}, {state_code}", geo_lat, geo_lng))
                    row = cur.fetchone()
                    if not row:
                        cur.execute("SELECT id FROM companies WHERE name = %s", (company_name,))
                        row = cur.fetchone()
                    company_id = row[0] if row else None

                    cur.execute("""
                        INSERT INTO jobs (company_id, title, description, salary_min, salary_max,
                            remote_type, source_url, source, posted_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        RETURNING id
                    """, (
                        company_id, job.get("job_title"),
                        (job.get("job_description") or "")[:5000],
                        job.get("job_min_salary"), job.get("job_max_salary"),
                        "remote" if job.get("job_is_remote") else "onsite",
                        job.get("job_apply_link"), "jsearch"
                    ))
                    job_row = cur.fetchone()
                    if job_row:
                        new_job_ids.append(job_row[0])
                conn.commit()

            # Generate embeddings for new jobs
            for job_id in new_job_ids:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT title, description FROM jobs WHERE id = %s", (job_id,))
                    job_row = cur.fetchone()
                if not job_row:
                    continue
                try:
                    prompt = f"""Extract skills from this job. Return ONLY JSON:
{{"skills": ["skill1", ...], "seniority": "entry/mid/senior/lead", "remote_type": "remote/hybrid/onsite"}}
Title: {job_row['title']}
Description: {(job_row['description'] or '')[:2000]}"""
                    response = llm.invoke([HumanMessage(content=prompt)])
                    raw = response.content.strip()
                    if raw.startswith("```"):
                        raw = raw.split("```")[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                    parsed = json.loads(raw.strip())
                    skills = parsed.get("skills", [])
                    embedding = emb_model.embed_query(
                        f"{job_row['title']} {' '.join(skills)} {(job_row['description'] or '')[:500]}"
                    )
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE jobs SET embedding = %s, seniority = %s, remote_type = %s
                            WHERE id = %s
                        """, (embedding, parsed.get("seniority"), parsed.get("remote_type"), job_id))
                        for skill in skills:
                            cur.execute("INSERT INTO skills (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (skill.lower(),))
                            cur.execute("SELECT id FROM skills WHERE name = %s", (skill.lower(),))
                            skill_row = cur.fetchone()
                            if skill_row:
                                cur.execute("INSERT INTO job_skills (job_id, skill_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                    (job_id, skill_row[0]))
                    conn.commit()
                except Exception as e:
                    print(f"Embedding failed for job {job_id}: {e}")

            # Re-run search
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT j.id, j.title, j.seniority, j.remote_type,
                        j.salary_min, j.salary_max, j.source_url,
                        c.id AS company_id, c.name AS company_name,
                        c.lng, c.lat,
                        1 - (j.embedding <=> %s::vector) AS similarity
                    FROM jobs j
                    JOIN companies c ON j.company_id = c.id
                    WHERE j.embedding IS NOT NULL AND c.lat IS NOT NULL
                    ORDER BY j.embedding <=> %s::vector
                    LIMIT 50
                """, (query_embedding, query_embedding))
                all_jobs = cur.fetchall()
            jobs = [j for j in all_jobs
                    if haversine_distance(lat, lng, float(j["lat"]), float(j["lng"])) <= radius_miles]

        # Group by company
        company_map: dict = {}
        for job in jobs:
            cid = job["company_id"]
            if cid not in company_map:
                company_map[cid] = {
                    "company_id": cid,
                    "company_name": job["company_name"],
                    "lat": float(job["lat"]),
                    "lng": float(job["lng"]),
                    "jobs": [],
                    "max_similarity": 0
                }
            company_map[cid]["jobs"].append({
                "title": job["title"],
                "url": job["source_url"],
                "seniority": job["seniority"],
                "remote_type": job["remote_type"],
                "salary_min": job["salary_min"],
                "salary_max": job["salary_max"],
                "similarity": round(float(job["similarity"]) * 100, 1)
            })
            if float(job["similarity"]) > company_map[cid]["max_similarity"]:
                company_map[cid]["max_similarity"] = float(job["similarity"])

        features = []
        for company in company_map.values():
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [company["lng"], company["lat"]]},
                "properties": {
                    "company_id": company["company_id"],
                    "company_name": company["company_name"],
                    "job_count": len(company["jobs"]),
                    "jobs": company["jobs"],
                    "top_skills": [],
                    "avg_salary_min": None,
                    "avg_salary_max": None,
                    "similarity": round(company["max_similarity"] * 100, 1)
                }
            })

        features.sort(key=lambda x: x["properties"]["similarity"], reverse=True)
        return {
            "type": "FeatureCollection",
            "features": features,
            "total": len(features),
            "query": q,
            "semantic": True
        }
    finally:
        conn.close()