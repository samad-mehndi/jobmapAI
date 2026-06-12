from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.api.jobs import router as jobs_router
from app.api.resume import router as resume_router

load_dotenv()

app = FastAPI(title="DFW JobMap API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router, prefix="/api")
app.include_router(resume_router, prefix="/api")

@app.get("/")
async def root():
    return {"status": "DFW JobMap API running"}

@app.get("/health")
async def health():
    return {"status": "ok"}