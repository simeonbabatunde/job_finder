from sqlmodel import Session, select
from app.database import engine
from app.models import Application
from app.observability import log_event
from app.services.application_link_resolver import ApplicationLinkResolver
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
            log_event("application_persistence.skipped", level="warning", reason="missing_user_id")
            return

        job_url = job_data.get("url")
        if not job_url:
            log_event("application_persistence.skipped", level="warning", user_id=user_id, reason="missing_job_url")
            return
        link_resolution = ApplicationLinkResolver.classify_url(job_url)

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
                    if job_data.get("pre_screen_status"):
                        existing_app.pre_screen_status = job_data["pre_screen_status"]
                    if "pre_screen_reasons" in job_data:
                        existing_app.pre_screen_reasons = job_data.get("pre_screen_reasons") or []
                    elif existing_app.pre_screen_reasons is None:
                        existing_app.pre_screen_reasons = []
                    existing_app.source_url = existing_app.source_url or link_resolution.original_url
                    existing_app.resolved_url = link_resolution.resolved_url
                    existing_app.source_type = link_resolution.source_type
                    existing_app.ats_type = link_resolution.ats_type
                    existing_app.resolution_status = link_resolution.resolution_status
                    existing_app.resolution_notes = link_resolution.notes
                    # Update status only when moving to a more advanced stage
                    status_order = [
                        "Screened Out", "Identified", "Analysis Failed",
                        "Analyzed", "Needs Review", "Submitted",
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
                        source_url=link_resolution.original_url,
                        resolved_url=link_resolution.resolved_url,
                        source_type=link_resolution.source_type,
                        ats_type=link_resolution.ats_type,
                        resolution_status=link_resolution.resolution_status,
                        resolution_notes=link_resolution.notes,
                        status=status,
                        fit_score=job_data.get("fit_score", 0.0),
                        explanation=job_data.get("explanation"),
                        cover_letter=job_data.get("cover_letter"),
                        pre_screen_status=job_data.get("pre_screen_status", "not_screened"),
                        pre_screen_reasons=job_data.get("pre_screen_reasons") or [],
                    )
                    session.add(new_app)
                    session.commit()

        except Exception as e:
            log_event("application_persistence.failed", level="error", user_id=user_id, job_url=job_url, error=str(e))
