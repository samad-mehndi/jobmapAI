import httpx
import os
import sys
import time
import argparse
import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_URL = os.getenv("DATABASE_URL")
JSEARCH_KEY = os.getenv("JSEARCH_API_KEY")

DEFAULT_QUERIES = [
    "Software Engineer in Richardson TX",
    "Full Stack Developer in Plano TX",
    "Backend Engineer in Dallas TX",
    "AI Engineer in Dallas TX",
    "Data Engineer in Irving TX",
    "Frontend Engineer in Dallas TX",
    "DevOps Engineer in Dallas TX",
    "Machine Learning Engineer in Dallas TX",
    "Python Developer in Dallas TX",
    "React Developer in Plano TX",
    "Java Developer in Dallas TX",
    "Cloud Engineer in Dallas TX",
    "Software Engineer in Frisco TX",
    "Engineering Manager in Dallas TX",
    "Product Engineer in Dallas TX",
    "iOS Developer in Dallas TX",
    "Android Developer in Dallas TX",
    "Cybersecurity Engineer in Dallas TX",
    "Data Scientist in Dallas TX",
    "Site Reliability Engineer in Dallas TX",
]

def geocode_nominatim(company: str, city: str, state: str) -> tuple:
    try:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "dfw-jobmap-dev/1.0"}
        params = {"q": f"{company}, {city}, {state}", "format": "json", "limit": 1}
        r = httpx.get(url, headers=headers, params=params, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
        params["q"] = f"{city}, {state}"
        r = httpx.get(url, headers=headers, params=params, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"  Geocoding error: {e}")
    return 32.7767, -96.7970

def fetch_jobs(query: str, num_pages: int = 1) -> list:
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": JSEARCH_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    params = {
        "query": query,
        "page": "1",
        "num_pages": str(num_pages),
        "date_posted": "month"
    }
    try:
        r = httpx.get(url, headers=headers, params=params, timeout=15)
        return r.json().get("data", [])
    except Exception as e:
        print(f"  JSearch error: {e}")
        return []

def insert_job(conn, job: dict):
    company_name = job.get("employer_name", "Unknown")
    city = job.get("job_city") or "Dallas"
    state = job.get("job_state") or "TX"

    time.sleep(1)
    lat, lng = geocode_nominatim(company_name, city, state)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO companies (name, address, lat, lng)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET lat = EXCLUDED.lat, lng = EXCLUDED.lng
            RETURNING id
        """, (company_name, f"{company_name}, {city}, {state}", lat, lng))

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

def main():
    parser = argparse.ArgumentParser(description="Seed DFW job data")
    parser.add_argument("--queries", nargs="+", help="Custom search queries")
    parser.add_argument("--per-query", type=int, default=1, help="Pages per query (10 jobs/page)")
    parser.add_argument("--list", action="store_true", help="List default queries and exit")
    args = parser.parse_args()

    if args.list:
        print("Default queries:")
        for i, q in enumerate(DEFAULT_QUERIES, 1):
            print(f"  {i}. {q}")
        return

    if not JSEARCH_KEY or JSEARCH_KEY == "replace-me":
        print("JSEARCH_API_KEY not set in .env")
        sys.exit(1)

    queries = args.queries if args.queries else DEFAULT_QUERIES
    per_query = args.per_query

    print(f"Running {len(queries)} queries, {per_query} page(s) each\n")

    conn = psycopg2.connect(DB_URL)
    print("Connected to database\n")

    total = 0
    for query in queries:
        print(f"Fetching: {query}")
        jobs = fetch_jobs(query, num_pages=per_query)
        print(f"  Found {len(jobs)} jobs")
        for i, job in enumerate(jobs):
            title = job.get("job_title", "Unknown")
            company = job.get("employer_name", "Unknown")
            print(f"  [{i+1}/{len(jobs)}] {title[:50]} @ {company[:30]}")
            insert_job(conn, job)
            total += 1
        print()

    conn.close()
    print(f"Done. Total jobs inserted: {total}")

    conn2 = psycopg2.connect(DB_URL)
    with conn2.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM jobs")
        jobs_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM companies")
        companies_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM companies WHERE lat IS NOT NULL")
        geocoded = cur.fetchone()[0]
    conn2.close()

    print(f"Total jobs in DB:      {jobs_count}")
    print(f"Total companies in DB: {companies_count}")
    print(f"Companies geocoded:    {geocoded}")

if __name__ == "__main__":
    main()