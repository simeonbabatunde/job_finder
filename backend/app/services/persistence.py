from sqlmodel import Session, select
from app.database import engine
from app.models import Application
from app.observability import log_event
from app.services.application_link_resolver import ApplicationLinkResolver, LinkResolutionResult
from typing import Dict, Any
import re


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation/extra spaces for fuzzy comparison."""
    return re.sub(r'[^a-z0-9 ]', '', text.lower()).strip()


class PersistenceService:
    @staticmethod
    def _link_resolution_from_job(job_url: str, job_data: Dict[str, Any]) -> LinkResolutionResult:
        base_resolution = ApplicationLinkResolver.classify_url(job_url)
        resolved_url = job_data.get("resolved_url")
        if not resolved_url:
            return base_resolution

        resolved_classification = ApplicationLinkResolver.classify_url(resolved_url)
        return LinkResolutionResult(
            original_url=job_data.get("source_url") or base_resolution.original_url,
            resolved_url=resolved_url,
            source_type=job_data.get("source_type") or base_resolution.source_type,
            ats_type=job_data.get("ats_type") or resolved_classification.ats_type,
            resolution_status=job_data.get("resolution_status") or "resolved",
            notes=job_data.get("resolution_notes") or resolved_classification.notes,
        )

    @staticmethod
    def save_job(user_id: int, job_data: Dict[str, Any], status: str, matching_profile_id: int | None = None, agent_run_id: int | None = None):
        """
        Upserts an application record and returns its id when saved.
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
        link_resolution = PersistenceService._link_resolution_from_job(job_url, job_data)

        job_title_raw = job_data.get("title", "")
        company_raw = job_data.get("company", "")
        norm_title = _normalise(job_title_raw)
        norm_company = _normalise(company_raw)

        try:
            with Session(engine) as session:
                # ── 1. Match by URL ──────────────────────────────────────────
                url_query = select(Application).where(
                    Application.user_id == user_id,
                    Application.job_url == job_url,
                )
                if matching_profile_id is not None:
                    url_query = url_query.where(Application.matching_profile_id == matching_profile_id)
                else:
                    url_query = url_query.where(Application.matching_profile_id.is_(None))
                existing_app = session.exec(url_query).first()

                # ── 2. Fallback: match by normalised title + company ─────────
                if not existing_app and norm_title and norm_company:
                    candidate_query = select(Application).where(Application.user_id == user_id)
                    if matching_profile_id is not None:
                        candidate_query = candidate_query.where(Application.matching_profile_id == matching_profile_id)
                    else:
                        candidate_query = candidate_query.where(Application.matching_profile_id.is_(None))
                    candidates = session.exec(candidate_query).all()
                    for c in candidates:
                        if (
                            _normalise(c.job_title) == norm_title
                            and _normalise(c.company) == norm_company
                        ):
                            existing_app = c
                            break

                if existing_app:
                    # Preserve strong analysis if a later discovery or failed-analysis pass
                    # finds the same role again. Those lower-confidence states should not
                    # zero scores, replace cover letters, or erase explanations.
                    status_order = [
                        "Screened Out", "Identified", "Analysis Failed",
                        "Analyzed", "Needs Review", "Submitted",
                        "Applied", "Phone Screen", "Interview",
                        "Take-Home", "Offer", "Rejected", "No Response"
                    ]
                    analysis_field_statuses = {
                        "Analyzed", "Needs Review", "Submitted", "Applied",
                        "Phone Screen", "Interview", "Take-Home", "Offer",
                        "Rejected", "No Response",
                    }
                    current_rank = status_order.index(existing_app.status) if existing_app.status in status_order else 0
                    new_rank = status_order.index(status) if status in status_order else 0
                    should_update_analysis_fields = status in analysis_field_statuses

                    if matching_profile_id is not None:
                        existing_app.matching_profile_id = matching_profile_id
                    if agent_run_id is not None:
                        existing_app.agent_run_id = agent_run_id
                    if should_update_analysis_fields and "fit_score" in job_data:
                        existing_app.fit_score = job_data["fit_score"]
                    if should_update_analysis_fields and job_data.get("explanation"):
                        existing_app.explanation = job_data["explanation"]
                    if should_update_analysis_fields and job_data.get("cover_letter"):
                        existing_app.cover_letter = job_data["cover_letter"]
                    if job_data.get("pre_screen_status"):
                        existing_app.pre_screen_status = job_data["pre_screen_status"]
                    if "pre_screen_reasons" in job_data:
                        existing_app.pre_screen_reasons = job_data.get("pre_screen_reasons") or []
                    elif existing_app.pre_screen_reasons is None:
                        existing_app.pre_screen_reasons = []
                    should_update_link_metadata = (
                        link_resolution.resolution_status == "resolved"
                        or existing_app.resolution_status != "resolved"
                    )
                    if should_update_link_metadata:
                        existing_app.source_url = existing_app.source_url or link_resolution.original_url
                        existing_app.resolved_url = link_resolution.resolved_url
                        existing_app.source_type = link_resolution.source_type
                        existing_app.ats_type = link_resolution.ats_type
                        existing_app.resolution_status = link_resolution.resolution_status
                        existing_app.resolution_notes = link_resolution.notes
                    # Update status only when moving to a more advanced stage.
                    if new_rank >= current_rank:
                        existing_app.status = status

                    session.add(existing_app)
                    session.commit()
                    session.refresh(existing_app)
                    return existing_app.id
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
                        matching_profile_id=matching_profile_id,
                        agent_run_id=agent_run_id,
                        fit_score=job_data.get("fit_score", 0.0),
                        explanation=job_data.get("explanation"),
                        cover_letter=job_data.get("cover_letter"),
                        pre_screen_status=job_data.get("pre_screen_status", "not_screened"),
                        pre_screen_reasons=job_data.get("pre_screen_reasons") or [],
                    )
                    session.add(new_app)
                    session.commit()
                    session.refresh(new_app)
                    return new_app.id

        except Exception as e:
            log_event("application_persistence.failed", level="error", user_id=user_id, job_url=job_url, error=str(e))
        return None
