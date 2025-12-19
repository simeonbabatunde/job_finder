from sqlalchemy import create_engine, text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/job_finder")
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE jobpreference ADD COLUMN posted_within_weeks INTEGER DEFAULT 1;"))
        conn.commit()
        print("Successfully added posted_within_weeks column.")
    except Exception as e:
        print(f"Error: {e}")
