-- Enable extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- Companies table
CREATE TABLE IF NOT EXISTS companies (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    industry    TEXT,
    website     TEXT,
    address     TEXT,
    location    GEOGRAPHY(Point, 4326),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name)
);

CREATE INDEX IF NOT EXISTS idx_companies_location
    ON companies USING GIST(location);

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id),
    title           TEXT NOT NULL,
    description     TEXT,
    salary_min      INTEGER,
    salary_max      INTEGER,
    remote_type     TEXT CHECK (remote_type IN ('remote','hybrid','onsite')),
    seniority       TEXT CHECK (seniority IN ('entry','mid','senior','lead')),
    source_url      TEXT,
    source          TEXT,
    posted_date     DATE,
    embedding       VECTOR(1536),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_embedding
    ON jobs USING hnsw (embedding vector_cosine_ops);

-- Skills tables
CREATE TABLE IF NOT EXISTS skills (
    id    SERIAL PRIMARY KEY,
    name  TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS job_skills (
    job_id   INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    skill_id INTEGER REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, skill_id)
);

-- Users / resume table
CREATE TABLE IF NOT EXISTS users (
    id               SERIAL PRIMARY KEY,
    email            TEXT UNIQUE,
    raw_resume_text  TEXT,
    parsed_skills    TEXT[],
    resume_embedding VECTOR(1536),
    created_at       TIMESTAMPTZ DEFAULT NOW()
);