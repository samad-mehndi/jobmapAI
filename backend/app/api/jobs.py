import os
from fastapi import APIRouter, Query
from psycopg2.extras import RealDictCursor
import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../..', '.env'))

router = APIRouter()
DB_URL = os.getenv("DATABASE_URL")


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