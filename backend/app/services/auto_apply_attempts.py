from typing import Optional

from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, select

from app.models import Application, ApplicationFillReview, AutoApplyAttempt
from app.observability import log_event, url_host
from app.services.fill_review_artifacts import FillReviewArtifactStore
from app.time_utils import utc_now


def fill_review_artifact_url(app_id: int, review_id: Optional[int], kind: str, path: Optional[str]):
    if not review_id or not FillReviewArtifactStore.is_readable(path):
        return None
    return f"/applications/{app_id}/fill-reviews/{review_id}/{kind}"


def serialize_fill_review_record(record: ApplicationFillReview):
    return {
        "id": record.id,
        "application_id": record.application_id,
        "ats_type": record.ats_type,
        "application_url": record.application_url,
        "status": record.status,
        "message": record.message,
        "fields_filled": record.fields_filled,
        "fields_missing": record.fields_missing,
        "blockers": record.blockers,
        "screenshot_url": fill_review_artifact_url(
            record.application_id,
            record.id,
            "screenshot",
            record.screenshot_path,
        ),
        "trace_url": fill_review_artifact_url(
            record.application_id,
            record.id,
            "trace",
            record.trace_path,
        ),
        "created_at": record.created_at,
    }


def serialize_auto_apply_attempt(attempt: AutoApplyAttempt):
    return {
        "id": attempt.id,
        "application_id": attempt.application_id,
        "agent_run_id": attempt.agent_run_id,
        "fill_review_id": attempt.fill_review_id,
        "job_url": attempt.job_url,
        "job_title": attempt.job_title,
        "company": attempt.company,
        "ats_type": attempt.ats_type,
        "mode": attempt.mode,
        "status": attempt.status,
        "confidence_score": attempt.confidence_score,
        "blocked_reason": attempt.blocked_reason,
        "filled_fields": attempt.filled_fields or [],
        "missing_fields": attempt.missing_fields or [],
        "blockers": attempt.blockers or [],
        "readiness_snapshot": attempt.readiness_snapshot or {},
        "submit_control": attempt.submit_control or {},
        "steps": attempt.steps or [],
        "screenshot_url": fill_review_artifact_url(
            attempt.application_id,
            attempt.fill_review_id,
            "screenshot",
            attempt.screenshot_path,
        ),
        "trace_url": fill_review_artifact_url(
            attempt.application_id,
            attempt.fill_review_id,
            "trace",
            attempt.trace_path,
        ),
        "submitted_at": attempt.submitted_at,
        "created_at": attempt.created_at,
        "updated_at": attempt.updated_at,
    }


def blocked_reason_from_lists(blockers: list[str], missing_fields: Optional[list[str]] = None):
    if blockers:
        return blockers[0]
    if missing_fields:
        return f"Missing required field: {missing_fields[0]}"
    return None


def build_attempt_step(name: str, status: str, message: Optional[str] = None, details: Optional[dict] = None):
    return jsonable_encoder({
        "name": name,
        "status": status,
        "message": message,
        "details": details or {},
        "at": utc_now(),
    })


def append_attempt_step(
    session: Session,
    attempt: AutoApplyAttempt,
    name: str,
    status: str,
    message: Optional[str] = None,
    details: Optional[dict] = None,
    *,
    commit: bool = True,
):
    steps = list(attempt.steps or [])
    steps.append(build_attempt_step(name, status, message, details))
    attempt.steps = steps[-50:]
    attempt.updated_at = utc_now()
    session.add(attempt)
    if commit:
        session.commit()
        session.refresh(attempt)
    log_event(
        "auto_apply_attempt.step",
        user_id=attempt.user_id,
        application_id=attempt.application_id,
        auto_apply_attempt_id=attempt.id,
        step_name=name,
        step_status=status,
        message=message,
        details=details or {},
    )
    return attempt


def create_auto_apply_attempt(
    session: Session,
    *,
    user_id: int,
    app: Application,
    mode: str,
    status: str = "queued",
    agent_run_id: Optional[int] = None,
):
    attempt = AutoApplyAttempt(
        user_id=user_id,
        application_id=app.id,
        agent_run_id=agent_run_id,
        job_url=app.resolved_url or app.job_url,
        job_title=app.job_title,
        company=app.company,
        ats_type=app.ats_type,
        mode=mode,
        status=status,
        updated_at=utc_now(),
        steps=[
            build_attempt_step(
                "attempt_created",
                status,
                f"{mode.replace('_', ' ')} attempt created.",
            )
        ],
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    log_event(
        "auto_apply_attempt.created",
        user_id=user_id,
        application_id=app.id,
        auto_apply_attempt_id=attempt.id,
        agent_run_id=agent_run_id,
        mode=mode,
        status=status,
        ats_type=app.ats_type,
        source_host=url_host(app.resolved_url or app.job_url),
    )
    return attempt


def get_latest_auto_apply_attempt(session: Session, user_id: int, application_id: int):
    return session.exec(
        select(AutoApplyAttempt)
        .where(AutoApplyAttempt.user_id == user_id, AutoApplyAttempt.application_id == application_id)
        .order_by(AutoApplyAttempt.created_at.desc())
    ).first()


def update_attempt_from_fill_review(
    session: Session,
    attempt: AutoApplyAttempt,
    review_record: ApplicationFillReview,
):
    attempt.fill_review_id = review_record.id
    attempt.ats_type = review_record.ats_type
    attempt.job_url = review_record.application_url
    attempt.status = (
        "ready_for_confirmation"
        if not review_record.blockers and not review_record.fields_missing
        else "blocked_needs_review"
    )
    attempt.confidence_score = 0.75 if attempt.status == "ready_for_confirmation" else 0.25
    attempt.blocked_reason = blocked_reason_from_lists(review_record.blockers or [], review_record.fields_missing or [])
    attempt.filled_fields = review_record.fields_filled or []
    attempt.missing_fields = review_record.fields_missing or []
    attempt.blockers = review_record.blockers or []
    attempt.screenshot_path = review_record.screenshot_path
    attempt.trace_path = review_record.trace_path
    attempt.updated_at = utc_now()
    attempt.steps = (list(attempt.steps or []) + [
        build_attempt_step(
            "fill_review_completed",
            attempt.status,
            review_record.message or "Application prep completed.",
            {
                "fields_filled_count": len(review_record.fields_filled or []),
                "needs_review_count": len(review_record.fields_missing or []) + len(review_record.blockers or []),
            },
        )
    ])[-50:]
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    log_event(
        "auto_apply_attempt.fill_review_completed",
        user_id=attempt.user_id,
        application_id=attempt.application_id,
        auto_apply_attempt_id=attempt.id,
        fill_review_id=review_record.id,
        status=attempt.status,
        ats_type=review_record.ats_type,
        fields_filled_count=len(review_record.fields_filled or []),
        missing_fields_count=len(review_record.fields_missing or []),
        blockers_count=len(review_record.blockers or []),
    )
    return attempt


def update_attempt_from_confirmation(
    session: Session,
    attempt: AutoApplyAttempt,
    response: dict,
):
    submit_control = response.get("submit_control") or {}
    attempt.mode = "submit_confirmation"
    attempt.status = "ready_for_human_confirmation" if response.get("ready") else "blocked_needs_review"
    attempt.confidence_score = float(submit_control.get("confidence") or 0.0)
    attempt.blocked_reason = blocked_reason_from_lists(response.get("blockers") or [])
    attempt.blockers = response.get("blockers") or []
    attempt.readiness_snapshot = jsonable_encoder(response.get("readiness") or {})
    attempt.submit_control = jsonable_encoder(submit_control)
    attempt.updated_at = utc_now()
    attempt.steps = (list(attempt.steps or []) + [
        build_attempt_step(
            "final_confirmation_prepared",
            attempt.status,
            response.get("message"),
            {
                "ready": bool(response.get("ready")),
                "submit_control_status": submit_control.get("status"),
                "submit_control_confidence": submit_control.get("confidence"),
            },
        )
    ])[-50:]
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    log_event(
        "auto_apply_attempt.submit_confirmation_prepared",
        user_id=attempt.user_id,
        application_id=attempt.application_id,
        auto_apply_attempt_id=attempt.id,
        status=attempt.status,
        ready=bool(response.get("ready")),
        submit_control_status=submit_control.get("status"),
        submit_control_confidence=submit_control.get("confidence"),
        blockers_count=len(response.get("blockers") or []),
    )
    return attempt
