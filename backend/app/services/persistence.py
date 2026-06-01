from sqlmodel import Session, select
from app.database import engine
from app.models import Application
from typing import Dict, Any
import re


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation/extra spaces for fuzzy comparison."""
    return re.sub(r'[^a-z0-9 ]', '', text.lower()).strip()


class PersistenceService:
    @staticmethod
    def save_job(user_id: int, job_data: Dict[str, Any], status: str):
        """
        Upserts an application record.
        Deduplication strategy:
          1. Exact URL match → update the existing record.
          2. Same normalised (title, company) → update the existing record (catches
             same job posted with slightly different URLs across scrapers).
          3. Neither match → insert a new record.
        """
        if not user_id:
            print("Warning: No user_id provided to save_job. Skipping persistence.")
            return

        job_url = job_data.get("url")
        if not job_url:
            print("Warning: No job_url provided. Skipping persistence.")
            return

        job_title_raw = job_data.get("title", "")
        company_raw = job_data.get("company", "")
        norm_title = _normalise(job_title_raw)
        norm_company = _normalise(company_raw)

        try:
            with Session(engine) as session:
                # ── 1. Match by URL ──────────────────────────────────────────
                existing_app = session.exec(
                    select(Application).where(
                        Application.user_id == user_id,
                        Application.job_url == job_url
                    )
                ).first()

                # ── 2. Fallback: match by normalised title + company ─────────
                if not existing_app and norm_title and norm_company:
                    candidates = session.exec(
                        select(Application).where(Application.user_id == user_id)
                    ).all()
                    for c in candidates:
                        if (
                            _normalise(c.job_title) == norm_title
                            and _normalise(c.company) == norm_company
                        ):
                            existing_app = c
                            break

                if existing_app:
                    # Only update score/analysis fields — preserve user-set status
                    if "fit_score" in job_data:
                        existing_app.fit_score = job_data["fit_score"]
                    if job_data.get("explanation"):
                        existing_app.explanation = job_data["explanation"]
                    if job_data.get("cover_letter"):
                        existing_app.cover_letter = job_data["cover_letter"]
                    # Update status only when moving to a more advanced stage
                    status_order = [
                        "Identified", "Analyzed", "Analysis Failed",
                        "Applied", "Phone Screen", "Interview",
                        "Take-Home", "Offer", "Rejected", "No Response"
                    ]
                    current_rank = status_order.index(existing_app.status) if existing_app.status in status_order else 0
                    new_rank = status_order.index(status) if status in status_order else 0
                    if new_rank >= current_rank:
                        existing_app.status = status

                    session.add(existing_app)
                    session.commit()
                else:
                    new_app = Application(
                        user_id=user_id,
                        job_title=job_title_raw,
                        company=company_raw,
                        job_url=job_url,
                        status=status,
                        fit_score=job_data.get("fit_score", 0.0),
                        explanation=job_data.get("explanation"),
                        cover_letter=job_data.get("cover_letter")
                    )
                    session.add(new_app)
                    session.commit()

        except Exception as e:
            print(f"Error persisting job {job_url}: {e}")
