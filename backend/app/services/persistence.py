from sqlmodel import Session, select
from app.database import engine
from app.models import Application
from typing import Dict, Any

class PersistenceService:
    @staticmethod
    def save_job(user_id: int, job_data: Dict[str, Any], status: str):
        """
        Upserts an application record.
        """
        if not user_id:
            print("Warning: No user_id provided to save_job. Skipping persistence.")
            return

        job_url = job_data.get("url")
        if not job_url:
            print("Warning: No job_url provided. Skipping persistence.")
            return

        try:
            with Session(engine) as session:
                # Check for existing application
                statement = select(Application).where(
                    Application.user_id == user_id,
                    Application.job_url == job_url
                )
                existing_app = session.exec(statement).first()
                
                if existing_app:
                    # Update existing record
                    existing_app.status = status
                    
                    # Only update fields if they are present and meaningful in job_data
                    if "fit_score" in job_data:
                        existing_app.fit_score = job_data["fit_score"]
                    if "explanation" in job_data and job_data["explanation"]:
                        existing_app.explanation = job_data["explanation"]
                    if "cover_letter" in job_data and job_data["cover_letter"]:
                        existing_app.cover_letter = job_data["cover_letter"]
                    
                    session.add(existing_app)
                    session.commit()
                    # print(f"Updated application for {job_data.get('title')} to status {status}")
                else:
                    # Create new record
                    new_app = Application(
                        user_id=user_id,
                        job_title=job_data.get("title", "Unknown"),
                        company=job_data.get("company", "Unknown"),
                        job_url=job_url,
                        status=status,
                        fit_score=job_data.get("fit_score", 0.0),
                        explanation=job_data.get("explanation"),
                        cover_letter=job_data.get("cover_letter")
                    )
                    session.add(new_app)
                    session.commit()
                    # print(f"Created application for {job_data.get('title')} with status {status}")
                    
        except Exception as e:
            print(f"Error persisting job {job_url}: {e}")
