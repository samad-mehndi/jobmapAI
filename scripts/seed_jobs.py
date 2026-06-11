import httpx
import os
import sys
import time
import psycopg2
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_URL = os.getenv("DATABASE_URL")
JSEARCH_KEY = os.getenv("JSEARCH_API_KEY")

SEARCH_QUERIES = [
    "Software Engineer in Richardson TX",
    "Full Stack Developer in Plano TX",
    "Backend Engineer in Dallas TX",
    "AI Engineer in Dallas TX",
    "Data Engineer in Irving TX",
]

def geocode_nominatim(company: str, city: str, state: str) -> tuple:
    """Free geocoding via OpenStreetMap Nominatim — no API key needed"""
    try:
        query = f"{company}, {city}, {state}"
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "dfw-jobmap-dev/1.0"}
        params = {"q": query, "format": "json", "limit": 1}
        r = httpx.get(url, headers=headers, params=params, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
        # Fall back to city-only search
        params["q"] = f"{city}, {state}"
        r = httpx.get(url, headers=headers, params=params, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"  Geocoding error: {e}")
    return None, None

def fetch_jobs(query: str) -> list:
    """Fetch jobs from JSearch API"""
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": JSEARCH_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    params = {
        "query": query,
        "page": "1",
        "num_pages": "1",
        "date_posted": "month"
    }
    try:
        r = httpx.get(url, headers=headers, params=params, timeout=15)
        return r.json().get("data", [])
    except Exception as e:
        print(f"  JSearch error: {e}")
        return []

def insert_job(conn, job: dict):
    """Insert a single job + company into the database"""
    company_name = job.get("employer_name", "Unknown")
    city = job.get("job_city") or "Dallas"
    state = job.get("job_state") or "TX"

    # Respect Nominatim rate limit (1 req/sec)
    time.sleep(1)
    lat, lng = geocode_nominatim(company_name, city, state)

    with conn.cursor() as cur:
        # Upsert company
        if lat and lng:
            cur.execute("""
                INSERT INTO companies (name, address, location)
                VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                ON CONFLICT (name) DO UPDATE
                SET location = EXCLUDED.location
                RETURNING id
            """, (company_name, f"{company_name}, {city}, {state}", lng, lat))
        else:
            cur.execute("""
                INSERT INTO companies (name, address)
                VALUES (%s, %s)
                ON CONFLICT (name) DO NOTHING
                RETURNING id
            """, (company_name, f"{city}, {state}"))

        row = cur.fetchone()
        if not row:
            cur.execute("SELECT id FROM companies WHERE name = %s", (company_name,))
            row = cur.fetchone()

        company_id = row[0] if row else None

        # Insert job
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
    if not JSEARCH_KEY or JSEARCH_KEY == "replace-me":
        print("❌ JSEARCH_API_KEY not set in .env")
        sys.exit(1)

    print("Connecting to database...")
    conn = psycopg2.connect(DB_URL)
    print("✅ Connected\n")

    total = 0
    for query in SEARCH_QUERIES:
        print(f"Fetching: {query}")
        jobs = fetch_jobs(query)
        print(f"  Found {len(jobs)} jobs")
        for i, job in enumerate(jobs):
            title = job.get("job_title", "Unknown")
            company = job.get("employer_name", "Unknown")
            print(f"  [{i+1}/{len(jobs)}] {title} @ {company}")
            insert_job(conn, job)
            total += 1
        print()

    conn.close()
    print(f"✅ Done. Total jobs seeded: {total}")

    # Show counts
    conn2 = psycopg2.connect(DB_URL)
    with conn2.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM jobs")
        jobs_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM companies")
        companies_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM companies WHERE location IS NOT NULL")
        geocoded_count = cur.fetchone()[0]
    conn2.close()

    print(f"📊 Jobs in database:        {jobs_count}")
    print(f"📊 Companies in database:   {companies_count}")
    print(f"📊 Companies geocoded:      {geocoded_count}")

if __name__ == "__main__":
    main()