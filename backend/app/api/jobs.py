import os
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


@router.get("/jobs/map")
def get_jobs_map(
    lat: float = Query(32.9483, description="Latitude"),
    lng: float = Query(-96.7297, description="Longitude"),
    radius_miles: float = Query(25, description="Search radius in miles"),
    role: str = Query(None, description="Role keyword filter")
):
    radius_meters = radius_miles * 1609.34
    conn = psycopg2.connect(DB_URL)

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # Base query — deduplicate jobs via subquery to avoid JSON DISTINCT issue
            query = """
                SELECT
                    c.id AS company_id,
                    c.name AS company_name,
                    ST_X(c.location::geometry) AS lng,
                    ST_Y(c.location::geometry) AS lat,
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
                                j2.title,
                                j2.source_url,
                                j2.seniority,
                                j2.remote_type,
                                j2.salary_min,
                                j2.salary_max
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
                WHERE c.location IS NOT NULL
                AND ST_DWithin(
                    c.location,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s
                )
            """
            params = [lng, lat, radius_meters]

            if role:
                query += " AND LOWER(j.title) LIKE %s"
                params.append(f"%{role.lower()}%")

            query += """
                GROUP BY c.id, c.name, c.location
                ORDER BY job_count DESC
            """

            cur.execute(query, params)
            rows = cur.fetchall()

        features = []
        for row in rows:
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
                GROUP BY s.name
                ORDER BY count DESC
                LIMIT 10
            """)
            top_skills = cur.fetchall()

            cur.execute("""
                SELECT remote_type, COUNT(*) AS count
                FROM jobs
                WHERE remote_type IS NOT NULL
                GROUP BY remote_type
            """)
            remote_breakdown = cur.fetchall()

            cur.execute("""
                SELECT seniority, COUNT(*) AS count
                FROM jobs
                WHERE seniority IS NOT NULL
                GROUP BY seniority
            """)
            seniority_breakdown = cur.fetchall()

            cur.execute("""
                SELECT c.name, COUNT(j.id) AS job_count
                FROM companies c
                JOIN jobs j ON j.company_id = c.id
                GROUP BY c.name
                ORDER BY job_count DESC
                LIMIT 8
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
    q: str = Query(..., description="Natural language search query"),
    lat: float = Query(32.9483),
    lng: float = Query(-96.7297),
    radius_miles: float = Query(40)
):
    """Semantic search using pgvector — understands natural language.
    If top similarity is below threshold, auto-fetches new jobs from JSearch."""

    import httpx
    import time
    import json
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_core.messages import HumanMessage

    radius_meters = radius_miles * 1609.34
    query_embedding = embeddings_model.embed_query(q)

    conn = psycopg2.connect(DB_URL)
    try:
        # ── Step 1: Vector search in existing jobs ─────────────────────
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    j.id, j.title, j.seniority, j.remote_type,
                    j.salary_min, j.salary_max, j.source_url,
                    c.id AS company_id, c.name AS company_name,
                    ST_X(c.location::geometry) AS lng,
                    ST_Y(c.location::geometry) AS lat,
                    1 - (j.embedding <=> %s::vector) AS similarity
                FROM jobs j
                JOIN companies c ON j.company_id = c.id
                WHERE j.embedding IS NOT NULL
                AND c.location IS NOT NULL
                AND ST_DWithin(
                    c.location,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s
                )
                ORDER BY j.embedding <=> %s::vector
                LIMIT 20
            """, (query_embedding, lng, lat, radius_meters, query_embedding))
            jobs = cur.fetchall()

        # ── Step 2: Check quality — fetch from JSearch if needed ────────
        top_similarity = float(jobs[0]["similarity"]) if jobs else 0
        should_fetch = len(jobs) < 5 or top_similarity < 0.45

        if should_fetch:
            print(f"  Only {len(jobs)} results for '{q}' (top similarity: {round(top_similarity*100,1)}%) — fetching from JSearch...")
            jsearch_key = os.getenv("JSEARCH_API_KEY")
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            emb_model = OpenAIEmbeddings(model="text-embedding-3-small")

            # Extract clean job title from natural language query
            title_response = llm.invoke([HumanMessage(content=
                f"Extract the core job title from this search query for a job search API. "
                f"Return only the job title, nothing else. Query: '{q}'"
            )])
            clean_title = title_response.content.strip()
            jsearch_query = f"{clean_title} in Dallas TX"
            print(f"  JSearch query: {jsearch_query}")

            # Fetch from JSearch
            try:
                r = httpx.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers={
                        "X-RapidAPI-Key": jsearch_key,
                        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
                    },
                    params={
                        "query": jsearch_query,
                        "page": "1",
                        "num_pages": "1",
                        "date_posted": "month"
                    },
                    timeout=15
                )
                new_jobs = r.json().get("data", [])
                print(f"  Fetched {len(new_jobs)} new jobs from JSearch")
            except Exception as e:
                print(f"  JSearch fetch failed: {e}")
                new_jobs = []

            # Geocode and insert new jobs
            new_job_ids = []
            for job in new_jobs:
                company_name = job.get("employer_name", "Unknown")
                city = job.get("job_city") or "Dallas"
                state_code = job.get("job_state") or "TX"

                # Geocode — company first, then city, then Dallas fallback
                time.sleep(1)
                geo_lat, geo_lng = None, None
                try:
                    geo_r = httpx.get(
                        "https://nominatim.openstreetmap.org/search",
                        headers={"User-Agent": "dfw-jobmap-dev/1.0"},
                        params={"q": f"{company_name}, {city}, {state_code}", "format": "json", "limit": 1},
                        timeout=10
                    )
                    geo_results = geo_r.json()
                    if geo_results:
                        geo_lat = float(geo_results[0]["lat"])
                        geo_lng = float(geo_results[0]["lon"])
                    else:
                        # Fall back to city-level geocoding
                        time.sleep(1)
                        city_r = httpx.get(
                            "https://nominatim.openstreetmap.org/search",
                            headers={"User-Agent": "dfw-jobmap-dev/1.0"},
                            params={"q": f"{city}, {state_code}", "format": "json", "limit": 1},
                            timeout=10
                        )
                        city_results = city_r.json()
                        if city_results:
                            geo_lat = float(city_results[0]["lat"])
                            geo_lng = float(city_results[0]["lon"])
                        else:
                            # Hard fallback to Dallas city center
                            geo_lat, geo_lng = 32.7767, -96.7970
                except Exception:
                    # Hard fallback to Dallas city center
                    geo_lat, geo_lng = 32.7767, -96.7970

                with conn.cursor() as cur:
                    if geo_lat and geo_lng:
                        cur.execute("""
                            INSERT INTO companies (name, address, location)
                            VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                            ON CONFLICT (name) DO UPDATE SET location = EXCLUDED.location
                            RETURNING id
                        """, (company_name, f"{company_name}, {city}, {state_code}", geo_lng, geo_lat))
                    else:
                        cur.execute("""
                            INSERT INTO companies (name, address)
                            VALUES (%s, %s)
                            ON CONFLICT (name) DO NOTHING
                            RETURNING id
                        """, (company_name, f"{city}, {state_code}"))

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
                        RETURNING id
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
                    job_row = cur.fetchone()
                    if job_row:
                        new_job_ids.append(job_row[0])

                conn.commit()

            # Generate embeddings for new jobs immediately
            if new_job_ids:
                print(f"  Generating embeddings for {len(new_job_ids)} new jobs...")
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
                        seniority = parsed.get("seniority")
                        remote_type = parsed.get("remote_type")

                        text = f"{job_row['title']} {' '.join(skills)} {(job_row['description'] or '')[:500]}"
                        embedding = emb_model.embed_query(text)

                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE jobs
                                SET embedding = %s, seniority = %s, remote_type = %s
                                WHERE id = %s
                            """, (embedding, seniority, remote_type, job_id))
                            for skill in skills:
                                cur.execute(
                                    "INSERT INTO skills (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                                    (skill.lower(),)
                                )
                                cur.execute("SELECT id FROM skills WHERE name = %s", (skill.lower(),))
                                skill_row = cur.fetchone()
                                if skill_row:
                                    cur.execute(
                                        "INSERT INTO job_skills (job_id, skill_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                        (job_id, skill_row[0])
                                    )
                        conn.commit()
                        print(f"  Embedded: {job_row['title']}")
                    except Exception as e:
                        print(f"  Embedding failed for job {job_id}: {e}")
                        continue

            # Re-run vector search with newly added jobs
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        j.id, j.title, j.seniority, j.remote_type,
                        j.salary_min, j.salary_max, j.source_url,
                        c.id AS company_id, c.name AS company_name,
                        ST_X(c.location::geometry) AS lng,
                        ST_Y(c.location::geometry) AS lat,
                        1 - (j.embedding <=> %s::vector) AS similarity
                    FROM jobs j
                    JOIN companies c ON j.company_id = c.id
                    WHERE j.embedding IS NOT NULL
                    AND c.location IS NOT NULL
                    AND ST_DWithin(
                        c.location,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        %s
                    )
                    ORDER BY j.embedding <=> %s::vector
                    LIMIT 20
                """, (query_embedding, lng, lat, radius_meters, query_embedding))
                jobs = cur.fetchall()
            print(f"  Re-ran search — found {len(jobs)} results")

        # ── Step 3: Group by company and build GeoJSON ──────────────────
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
                "geometry": {
                    "type": "Point",
                    "coordinates": [company["lng"], company["lat"]]
                },
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