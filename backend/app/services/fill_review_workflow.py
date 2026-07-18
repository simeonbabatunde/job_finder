from dataclasses import dataclass
from typing import Optional

from sqlmodel import Session, select

from app.models import Application, ApplicationAnswerProfile, ApplicationFillReview, Profile, Resume
from app.observability import log_event, url_host
from app.services.application_answer_profiles import (
    audit_application_answer_access,
    decrypt_application_answer_profile,
)
from app.services.application_fill_review import ApplicationFillReviewService
from app.services.application_link_resolver import ApplicationLinkResolver
from app.services.auto_apply_attempts import (
    append_attempt_step,
    create_auto_apply_attempt,
    fill_review_artifact_url,
    update_attempt_from_fill_review,
)
from app.services.fill_review_artifacts import FillReviewArtifactStore


class FillReviewWorkflowError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass
class FillReviewWorkflowResult:
    response: dict
    review_record: ApplicationFillReview
    attempt_id: int


def _latest_resume(session: Session, user_id: int) -> Optional[Resume]:
    return session.exec(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(Resume.upload_date.desc())
    ).first()


def _profile(session: Session, user_id: int) -> Optional[Profile]:
    return session.exec(select(Profile).where(Profile.user_id == user_id)).first()


def _answer_profile(session: Session, user_id: int) -> Optional[ApplicationAnswerProfile]:
    return decrypt_application_answer_profile(session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user_id)
    ).first())


async def prepare_application_for_review(
    session: Session,
    *,
    user_id: int,
    app: Application,
    agent_run_id: Optional[int] = None,
    audit_source: str = "browser_fill_review",
) -> FillReviewWorkflowResult:
    if not app or app.user_id != user_id:
        raise FillReviewWorkflowError("Application not found", status_code=404)

    application_url = app.resolved_url or app.job_url
    link_resolution = ApplicationLinkResolver.classify_url(application_url)
    ats_type = app.ats_type or link_resolution.ats_type

    log_event(
        "browser_fill_review.requested",
        user_id=user_id,
        application_id=app.id,
        agent_run_id=agent_run_id,
        ats_type=ats_type,
        source_host=url_host(application_url),
        resolution_status=app.resolution_status,
        audit_source=audit_source,
    )

    if app.resolution_status != "resolved" or not application_url:
        raise FillReviewWorkflowError("Resolve this application link before application prep")
    if ats_type not in ApplicationFillReviewService.SUPPORTED_ATS:
        raise FillReviewWorkflowError(
            "Application prep currently supports Greenhouse, Lever, Ashby, SmartRecruiters, "
            "Workday, BambooHR, iCIMS, Recruitee, and Taleo links only"
        )

    resume = _latest_resume(session, user_id)
    profile = _profile(session, user_id)
    answer_profile = _answer_profile(session, user_id)
    if answer_profile:
        audit_application_answer_access(
            session,
            user_id=user_id,
            action="automation_use",
            access_reason="fill_for_review",
            source=audit_source,
            application_id=app.id,
        )

    if not resume:
        raise FillReviewWorkflowError("Please upload a resume first")
    if not profile:
        raise FillReviewWorkflowError("Please complete your candidate profile first")

    app.ats_type = ats_type
    session.add(app)
    session.commit()
    session.refresh(app)

    attempt = create_auto_apply_attempt(
        session,
        user_id=user_id,
        app=app,
        mode="fill_for_review",
        status="filling",
        agent_run_id=agent_run_id,
    )
    attempt = append_attempt_step(
        session,
        attempt,
        "inputs_validated",
        "success",
        "Resume, profile, application link, and ATS support were validated.",
        {
            "ats_type": ats_type,
            "has_answer_profile": bool(answer_profile and answer_profile.consent_to_use_answers),
        },
    )
    attempt = append_attempt_step(
        session,
        attempt,
        "browser_fill_started",
        "running",
        "Browser application prep started.",
        {"application_url": application_url},
    )

    try:
        fill_result = await ApplicationFillReviewService.fill_application_for_review(
            application_url=application_url,
            ats_type=ats_type,
            profile=profile,
            resume_bytes=resume.file_content,
            resume_filename=resume.filename,
            answer_profile=answer_profile if answer_profile and answer_profile.consent_to_use_answers else None,
            cover_letter=app.cover_letter,
        )
    except Exception as exc:
        attempt.status = "failed"
        attempt.blocked_reason = str(exc)
        session.add(attempt)
        session.commit()
        append_attempt_step(
            session,
            attempt,
            "fill_review_failed",
            "failed",
            str(exc),
            {"application_url": application_url, "ats_type": ats_type},
        )
        raise

    review_record = ApplicationFillReview(
        user_id=user_id,
        application_id=app.id,
        ats_type=fill_result.ats_type,
        application_url=fill_result.application_url,
        status=fill_result.status,
        message=fill_result.message,
        fields_filled=fill_result.fields_filled,
        fields_missing=fill_result.fields_missing,
        blockers=fill_result.blockers,
    )
    app.status = fill_result.application_status
    session.add(review_record)
    session.add(app)
    session.commit()
    session.refresh(review_record)

    review_record.screenshot_path = FillReviewArtifactStore.save_base64(
        user_id=user_id,
        application_id=app.id,
        review_id=review_record.id,
        kind="screenshot",
        payload_base64=fill_result.screenshot_base64,
        extension="png",
    )
    review_record.trace_path = FillReviewArtifactStore.save_base64(
        user_id=user_id,
        application_id=app.id,
        review_id=review_record.id,
        kind="trace",
        payload_base64=fill_result.trace_base64,
        extension="zip",
    )
    session.add(review_record)
    session.commit()
    session.refresh(review_record)
    attempt = update_attempt_from_fill_review(session, attempt, review_record)

    response = fill_result.model_dump()
    response["review_id"] = review_record.id
    response["attempt_id"] = attempt.id
    response["screenshot_url"] = fill_review_artifact_url(
        app.id,
        review_record.id,
        "screenshot",
        review_record.screenshot_path,
    )
    response["trace_url"] = fill_review_artifact_url(
        app.id,
        review_record.id,
        "trace",
        review_record.trace_path,
    )
    response.pop("trace_base64", None)

    log_event(
        "browser_fill_review.completed",
        user_id=user_id,
        application_id=app.id,
        agent_run_id=agent_run_id,
        auto_apply_attempt_id=attempt.id,
        fill_review_id=review_record.id,
        status=fill_result.status,
        application_status=fill_result.application_status,
        ats_type=fill_result.ats_type,
        fields_filled_count=len(fill_result.fields_filled or []),
        missing_fields_count=len(fill_result.fields_missing or []),
        blockers_count=len(fill_result.blockers or []),
        screenshot_saved=bool(review_record.screenshot_path),
        trace_saved=bool(review_record.trace_path),
    )

    return FillReviewWorkflowResult(
        response=response,
        review_record=review_record,
        attempt_id=attempt.id,
    )
