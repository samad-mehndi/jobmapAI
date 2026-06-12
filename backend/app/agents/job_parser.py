import os
import json
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../..', '.env'))

# ── Models ─────────────────────────────────────────────────────
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# ── Agent State ────────────────────────────────────────────────
class JobParserState(TypedDict):
    job_id: int
    title: str
    description: str
    extracted_skills: list[str]
    seniority: Optional[str]
    remote_type: Optional[str]
    embedding: Optional[list[float]]
    error: Optional[str]

# ── Node 1: Extract skills + seniority + remote type ──────────
def extract_job_details(state: JobParserState) -> JobParserState:
    try:
        prompt = f"""Extract structured information from this job posting.

Job Title: {state['title']}
Job Description: {state['description'][:3000]}

Return ONLY a JSON object with exactly these fields:
{{
  "skills": ["skill1", "skill2", ...],
  "seniority": "entry" or "mid" or "senior" or "lead",
  "remote_type": "remote" or "hybrid" or "onsite"
}}

Rules:
- skills: list of 5-15 specific technical skills mentioned (languages, frameworks, tools)
- seniority: pick the single best match based on years of experience and title
- remote_type: pick the single best match based on job description
- Return ONLY the JSON, no explanation, no markdown
"""
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()

        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)

        return {
            **state,
            "extracted_skills": parsed.get("skills", []),
            "seniority": parsed.get("seniority"),
            "remote_type": parsed.get("remote_type"),
            "error": None
        }
    except Exception as e:
        return {**state, "error": f"Extraction failed: {e}"}

# ── Node 2: Generate embedding ─────────────────────────────────
def generate_embedding(state: JobParserState) -> JobParserState:
    if state.get("error"):
        return state
    try:
        # Combine title + skills for a richer embedding
        text = f"{state['title']} {' '.join(state['extracted_skills'])} {state['description'][:1000]}"
        embedding = embeddings.embed_query(text)
        return {**state, "embedding": embedding}
    except Exception as e:
        return {**state, "error": f"Embedding failed: {e}"}

# ── Build the graph ────────────────────────────────────────────
def build_job_parser_graph():
    graph = StateGraph(JobParserState)
    graph.add_node("extract", extract_job_details)
    graph.add_node("embed", generate_embedding)
    graph.set_entry_point("extract")
    graph.add_edge("extract", "embed")
    graph.add_edge("embed", END)
    return graph.compile()

job_parser_graph = build_job_parser_graph()

def parse_job(job_id: int, title: str, description: str) -> dict:
    """Main entry point — parse a single job"""
    result = job_parser_graph.invoke({
        "job_id": job_id,
        "title": title,
        "description": description,
        "extracted_skills": [],
        "seniority": None,
        "remote_type": None,
        "embedding": None,
        "error": None
    })
    return result