import os
import json
import time
import httpx
import psycopg2
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../..', '.env'))

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

DB_URL = os.getenv("DATABASE_URL")
JSEARCH_KEY = os.getenv("JSEARCH_API_KEY")

# ── Agent State ────────────────────────────────────────────────
class ResumeMatcherState(TypedDict):
    resume_text: str
    parsed_skills: list[str]
    target_roles: list[str]
    seniority: Optional[str]
    resume_embedding: Optional[list[float]]
    fetched_job_ids: list[int]
    error: Optional[str]

# ── Node 1: Parse resume ───────────────────────────────────────
def parse_resume(state: ResumeMatcherState) -> ResumeMatcherState:
    try:
        prompt = f"""Extract structured information from this resume.

Resume Text:
{state['resume_text'][:4000]}

Return ONLY a JSON object with exactly these fields:
{{
  "skills": ["skill1", "skill2", ...],
  "target_roles": ["role1", "role2", "role3"],
  "seniority": "entry" or "mid" or "senior" or "lead"
}}

Rules:
- skills: all technical skills, languages, frameworks, tools mentioned (max 20)
- target_roles: 3 most relevant job titles this person should search for
- seniority: estimate based on years of experience and roles held
- Return ONLY the JSON, no explanation, no markdown
"""
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        parsed = json.loads(raw)

        return {
            **state,
            "parsed_skills": parsed.get("skills", []),
            "target_roles": parsed.get("target_roles", []),
            "seniority": parsed.get("seniority"),
            "error": None
        }
    except Exception as e:
        return {**state, "error": f"Resume parsing failed: {e}"}

# ── Node 2: Fetch relevant jobs from JSearch ───────────────────
def fetch_relevant_jobs(state: ResumeMatcherState) -> ResumeMatcherState:
    if state.get("error"):
        return state
    try:
        conn = psycopg2.connect(DB_URL)
        register_vector(conn)
        fetched_ids = []

        for role in state["target_roles"][:3]:
            query = f"{role} in Dallas TX"
            print(f"  Fetching jobs for: {query}")

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
                jobs = r.json().get("data", [])
            except Exception:
                jobs = []

            for job in jobs:
                company_name = job.get("employer_name", "Unknown")
                city = job.get("job_city") or "Dallas"
                state_code = job.get("job_state") or "TX"

                # Geocode
                time.sleep(1)
                lat, lng = geocode(company_name, city, state_code)

                with conn.cursor() as cur:
                    if lat and lng:
                        cur.execute("""
                            INSERT INTO companies (name, address, location)
                            VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                            ON CONFLICT (name) DO UPDATE SET location = EXCLUDED.location
                            RETURNING id
                        """, (company_name, f"{company_name}, {city}, {state_code}", lng, lat))
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
                        fetched_ids.append(job_row[0])

                conn.commit()

        conn.close()
        return {**state, "fetched_job_ids": fetched_ids}
    except Exception as e:
        return {**state, "error": f"Job fetching failed: {e}", "fetched_job_ids": []}

# ── Node 3: Generate resume embedding ─────────────────────────
def embed_resume(state: ResumeMatcherState) -> ResumeMatcherState:
    if state.get("error"):
        return state
    try:
        text = f"{' '.join(state['target_roles'])} {' '.join(state['parsed_skills'])} {state['resume_text'][:1000]}"
        embedding = embeddings.embed_query(text)
        return {**state, "resume_embedding": embedding}
    except Exception as e:
        return {**state, "error": f"Embedding failed: {e}"}

# ── Geocode helper ─────────────────────────────────────────────
def geocode(company: str, city: str, state_code: str) -> tuple:
    try:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "dfw-jobmap-dev/1.0"}
        params = {"q": f"{company}, {city}, {state_code}", "format": "json", "limit": 1}
        r = httpx.get(url, headers=headers, params=params, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
        params["q"] = f"{city}, {state_code}"
        r = httpx.get(url, headers=headers, params=params, timeout=10)
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None, None

# ── Build graph ────────────────────────────────────────────────
def build_resume_matcher_graph():
    graph = StateGraph(ResumeMatcherState)
    graph.add_node("parse", parse_resume)
    graph.add_node("fetch_jobs", fetch_relevant_jobs)
    graph.add_node("embed", embed_resume)
    graph.set_entry_point("parse")
    graph.add_edge("parse", "fetch_jobs")
    graph.add_edge("fetch_jobs", "embed")
    graph.add_edge("embed", END)
    return graph.compile()

resume_matcher_graph = build_resume_matcher_graph()

def process_resume(resume_text: str) -> dict:
    result = resume_matcher_graph.invoke({
        "resume_text": resume_text,
        "parsed_skills": [],
        "target_roles": [],
        "seniority": None,
        "resume_embedding": None,
        "fetched_job_ids": [],
        "error": None
    })
    return result