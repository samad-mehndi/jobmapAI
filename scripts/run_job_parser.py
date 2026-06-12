import os
import sys
import psycopg2
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.agents.job_parser import parse_job

DB_URL = os.getenv("DATABASE_URL")

def run():
    conn = psycopg2.connect(DB_URL)
    register_vector(conn)

    # Fetch all jobs without embeddings
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, title, description
            FROM jobs
            WHERE embedding IS NULL
            AND description IS NOT NULL
        """)
        jobs = cur.fetchall()

    print(f"Found {len(jobs)} jobs to process\n")

    success = 0
    failed = 0

    for i, (job_id, title, description) in enumerate(jobs):
        print(f"[{i+1}/{len(jobs)}] Parsing: {title[:60]}")
        result = parse_job(job_id, title, description or "")

        if result.get("error"):
            print(f"  Error: {result['error']}")
            failed += 1
            continue

        skills = result.get("extracted_skills", [])
        seniority = result.get("seniority")
        remote_type = result.get("remote_type")
        embedding = result.get("embedding")

        with conn.cursor() as cur:
            # Update job with extracted data + embedding
            cur.execute("""
                UPDATE jobs
                SET seniority = %s,
                    remote_type = %s,
                    embedding = %s
                WHERE id = %s
            """, (seniority, remote_type, embedding, job_id))

            # Insert skills
            for skill in skills:
                cur.execute("""
                    INSERT INTO skills (name)
                    VALUES (%s)
                    ON CONFLICT (name) DO NOTHING
                """, (skill.lower(),))
                cur.execute("SELECT id FROM skills WHERE name = %s", (skill.lower(),))
                skill_row = cur.fetchone()
                if skill_row:
                    cur.execute("""
                        INSERT INTO job_skills (job_id, skill_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                    """, (job_id, skill_row[0]))

        conn.commit()
        print(f"  Skills: {skills[:5]} | Seniority: {seniority} | Remote: {remote_type}")
        success += 1

    conn.close()

    print(f"\n{'='*50}")
    print(f" Successfully parsed: {success}")
    print(f" Failed:             {failed}")

    # Final verification
    conn2 = psycopg2.connect(DB_URL)
    register_vector(conn2)
    with conn2.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM jobs WHERE embedding IS NOT NULL")
        embedded = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT skill_id) FROM job_skills")
        skills_count = cur.fetchone()[0]
    conn2.close()

    print(f"\n Jobs with embeddings: {embedded}")
    print(f" Unique skills found:  {skills_count}")

if __name__ == "__main__":
    run()