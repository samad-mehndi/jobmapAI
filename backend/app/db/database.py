import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_connection():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            print(f" Database connected: {result.fetchone()[0]}")
            result2 = conn.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis', 'vector')"))
            for row in result2:
                print(f" Extension: {row[0]} v{row[1]}")
    except Exception as e:
        print(f" Database connection failed: {e}")

if __name__ == "__main__":
    test_connection()