from fastapi import APIRouter, BackgroundTasks, UploadFile, File, HTTPException, Depends, Header, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
import base64
import hmac
import io
import os
import secrets
import time
from sqlalchemy import asc, desc, text
from sqlmodel import Session, select
from app.models import (
    AgentRun,
    Application,
    ApplicationAnswerAudit,
    ApplicationAnswerProfile,
    ApplicationFillReview,
    ApplicationSubmitSettings,
    AuthSession,
    AutoApplyAudit,
    AutoApplyAttempt,
    JobPreference,
    PasswordResetToken,
    Profile,
    Resume,
    ScraperConfig,
    User,
    WorkerHeartbeat,
)
from app.database import USE_ALEMBIC_MIGRATIONS, engine, get_session
from typing import List, Optional
from app.services.resume_parser import ResumeService
from app.services.job_search import JobSearchService
from app.services.email import send_reset_email
from app.services.application_link_resolver import ApplicationLinkResolver
from app.services.application_fill_review import ApplicationFillReviewService
from app.services.fill_review_artifacts import FillReviewArtifactStore
from app.services.field_encryption import (
    data_encryption_key_is_configured,
    decrypt_text,
    encrypt_text,
)
from app.schemas import (
    AccountDataExportResponse,
    AgentRunResponse,
    AgentRunRecordResponse,
    ApplicationAnswerProfileRequest,
    ApplicationAnswerAuditResponse,
    ApplicationAnswerExportResponse,
    ApplicationAnswerProfileResponse,
    ApplicationFillReviewResponse,
    ApplicationFillReviewRecordResponse,
    ApplicationPackageRequest,
    ApplicationPackageResponse,
    ApplicationSubmitConfirmationResponse,
    ApplicationSubmitReadinessResponse,
    ApplicationSubmitSettingsRequest,
    ApplicationSubmitSettingsResponse,
    ApplicationResponse,
    ApplicationStatusRequest,
    ApplicationStatusResponse,
    AuthResponse,
    AutoApplyAttemptResponse,
    DatabaseHealthResponse,
    EmailRequest,
    HealthResponse,
    JobAnalysisRequest,
    JobAnalysisResponse,
    JobPreferenceRequest,
    JobPreferenceResponse,
    LoginRequest,
    MessageResponse,
    ProfileRequest,
    RefreshTokenRequest,
    ProfileResponse,
    RegisterRequest,
    ResumeFeedbackResponse,
    ResumeUploadResponse,
    ResetPasswordRequest,
    SocialAuthRequest,
    UserStatusResponse,
    WorkerHealthResponse,
)
from app.agent.graph import agent_graph
from datetime import datetime, timedelta
from uuid import uuid4
import json
from app.agent.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
import bcrypt
import hashlib
import requests
from urllib.parse import urlencode, quote, urlparse
from app.time_utils import utc_now
from app.oauth_config import (
    get_google_oauth_url, 
    get_linkedin_oauth_url,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
    FRONTEND_URL
)

router = APIRouter()

APP_ENV = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").lower()
PRODUCTION_LIKE_ENVS = {"prod", "production", "staging"}
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY") or os.getenv("SECRET_KEY") or "job-finder-dev-secret-change-me"
AUTH_PREVIOUS_SECRET_KEYS = tuple(
    key.strip()
    for key in os.getenv("AUTH_PREVIOUS_SECRET_KEYS", "").split(",")
    if key.strip()
)
AUTH_ACCESS_TOKEN_TTL_SECONDS = int(
    os.getenv("AUTH_ACCESS_TOKEN_TTL_SECONDS")
    or os.getenv("AUTH_TOKEN_TTL_SECONDS", str(60 * 60))
)
AUTH_REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("AUTH_REFRESH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 30)))
FREE_DAILY_AGENT_RUN_LIMIT = int(os.getenv("FREE_DAILY_AGENT_RUN_LIMIT", "3"))
PRO_DAILY_AGENT_RUN_LIMIT = int(os.getenv("PRO_DAILY_AGENT_RUN_LIMIT", "50"))
INSECURE_AUTH_SECRET_VALUES = {
    "",
    "change-me-in-production",
    "job-finder-dev-secret-change-me",
}

def auth_secret_is_insecure(secret: str) -> bool:
    return not secret or secret in INSECURE_AUTH_SECRET_VALUES or len(secret) < 32

if APP_ENV in PRODUCTION_LIKE_ENVS and auth_secret_is_insecure(AUTH_SECRET_KEY):
    raise RuntimeError("Set a strong AUTH_SECRET_KEY before running in production.")

if APP_ENV in PRODUCTION_LIKE_ENVS and not data_encryption_key_is_configured():
    raise RuntimeError("Set APP_DATA_ENCRYPTION_KEY before running in production.")

def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)

def serialize_user(user: User):
    return {
        "id": user.id,
        "email": user.email,
        "subscription_tier": user.subscription_tier,
        "role": user.role,
    }

def sign_access_token_body(body: str, secret: str) -> str:
    signature = hmac.new(
        secret.encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return b64url_encode(signature)

def create_signed_access_token(user: User, token_id: str, expires_at: datetime):
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "jti": token_id,
        "exp": int(expires_at.timestamp()),
    }
    body = b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{body}.{sign_access_token_body(body, AUTH_SECRET_KEY)}"

def create_refresh_token(token_id: str) -> str:
    return f"{token_id}.{secrets.token_urlsafe(48)}"

def hash_refresh_token(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()

def create_auth_tokens(user: User, session: Session):
    token_id = uuid4().hex
    now = utc_now()
    expires_at = now + timedelta(seconds=AUTH_ACCESS_TOKEN_TTL_SECONDS)
    refresh_expires_at = now + timedelta(seconds=AUTH_REFRESH_TOKEN_TTL_SECONDS)
    refresh_token = create_refresh_token(token_id)
    session.add(
        AuthSession(
            user_id=user.id,
            token_id=token_id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
        )
    )
    session.commit()
    return {
        "access_token": create_signed_access_token(user, token_id, expires_at),
        "refresh_token": refresh_token,
        "expires_in": AUTH_ACCESS_TOKEN_TTL_SECONDS,
        "refresh_expires_in": AUTH_REFRESH_TOKEN_TTL_SECONDS,
    }

def decode_access_token(token: str):
    try:
        body, signature = token.split(".", 1)
        actual_signature = b64url_decode(signature)
        for secret in (AUTH_SECRET_KEY, *AUTH_PREVIOUS_SECRET_KEYS):
            expected_signature = hmac.new(
                secret.encode("utf-8"),
                body.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if hmac.compare_digest(expected_signature, actual_signature):
                payload = json.loads(b64url_decode(body))
                if int(payload.get("exp", 0)) < int(time.time()):
                    return None
                return payload
        return None
    except Exception:
        return None

def get_valid_refresh_session(refresh_token: str, session: Session) -> Optional[AuthSession]:
    try:
        token_id, _ = refresh_token.split(".", 1)
    except ValueError:
        return None

    auth_session = session.exec(
        select(AuthSession).where(AuthSession.token_id == token_id)
    ).first()
    if (
        not auth_session
        or auth_session.revoked_at is not None
        or auth_session.rotated_at is not None
        or not auth_session.refresh_token_hash
        or not auth_session.refresh_expires_at
        or auth_session.refresh_expires_at < utc_now()
    ):
        return None

    if not hmac.compare_digest(auth_session.refresh_token_hash, hash_refresh_token(refresh_token)):
        return None
    return auth_session

def find_auth_session_from_refresh(refresh_token: str, session: Session) -> Optional[AuthSession]:
    try:
        token_id, _ = refresh_token.split(".", 1)
    except ValueError:
        return None
    auth_session = session.exec(
        select(AuthSession).where(AuthSession.token_id == token_id)
    ).first()
    if not auth_session:
        return None
    if auth_session.refresh_token_hash and hmac.compare_digest(
        auth_session.refresh_token_hash,
        hash_refresh_token(refresh_token),
    ):
        return auth_session
    return None

def revoke_auth_session(auth_session: Optional[AuthSession], session: Session):
    if not auth_session or auth_session.revoked_at is not None:
        return
    auth_session.revoked_at = utc_now()
    session.add(auth_session)
    session.commit()

def rotate_auth_session(refresh_token: str, session: Session):
    auth_session = get_valid_refresh_session(refresh_token, session)
    if not auth_session:
        return None

    user = session.get(User, auth_session.user_id)
    if not user:
        return None

    now = utc_now()
    auth_session.revoked_at = now
    auth_session.rotated_at = now
    session.add(auth_session)
    session.commit()
    return auth_response(user, session)

def auth_response(user: User, session: Session):
    tokens = create_auth_tokens(user, session)
    return {
        "user": serialize_user(user),
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "expires_in": tokens["expires_in"],
        "refresh_expires_in": tokens["refresh_expires_in"],
    }

def hash_password(password: str):
    # Bcrypt has a 72-byte limit. 
    # Standard practice: hash the password with SHA256 first to allow unlimited length.
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    
    # Pre-hash with SHA256
    digest = hashlib.sha256(pwd_bytes).hexdigest().encode('utf-8')
    
    hashed = bcrypt.hashpw(digest, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str):
    # Re-calculate digest and verify
    digest = hashlib.sha256(plain_password.encode('utf-8')).hexdigest().encode('utf-8')
    return bcrypt.checkpw(digest, hashed_password.encode('utf-8'))

# Helper to get user from a signed bearer token
def get_current_user(session: Session = Depends(get_session), authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    token_id = payload.get("jti")
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not token_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    auth_session = session.exec(
        select(AuthSession).where(AuthSession.token_id == token_id)
    ).first()
    if (
        not auth_session
        or auth_session.user_id != user_id_int
        or auth_session.revoked_at is not None
        or auth_session.expires_at < utc_now()
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = session.get(User, user_id_int)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

def get_latest_resume(session: Session, user_id: int):
    return session.exec(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(Resume.upload_date.desc())
    ).first()

def get_latest_preferences(session: Session, user_id: int):
    return session.exec(
        select(JobPreference)
        .where(JobPreference.user_id == user_id)
        .order_by(JobPreference.created_at.desc())
    ).first()

def get_min_match_score(session: Session, user_id: int):
    prefs = get_latest_preferences(session, user_id)
    return prefs.min_match_score if prefs else 70

def assert_application_matches_threshold(app: Application, session: Session, user_id: int, action: str):
    if app.pre_screen_status == "reject" or app.status == "Screened Out":
        raise HTTPException(
            status_code=400,
            detail=f"Screened-out jobs are review-only and cannot be used for {action}.",
        )

    min_match_score = get_min_match_score(session, user_id)
    if app.fit_score * 100 < min_match_score:
        raise HTTPException(
            status_code=400,
            detail=f"This job is below your {min_match_score}% minimum match score and cannot be used for {action}.",
        )

def get_daily_agent_run_limit(user: User):
    if user.role == "admin":
        return PRO_DAILY_AGENT_RUN_LIMIT
    if user.subscription_tier == "pro":
        return PRO_DAILY_AGENT_RUN_LIMIT
    return FREE_DAILY_AGENT_RUN_LIMIT

def can_auto_apply(user: User):
    return user.role == "admin" or user.subscription_tier == "pro"

def get_agent_runner_mode():
    mode = os.getenv("AGENT_RUNNER_MODE", "background").strip().lower()
    return mode or "background"

def should_schedule_background_agent_run():
    return get_agent_runner_mode() != "worker"

def get_agent_run_stale_minutes():
    try:
        return max(int(os.getenv("AGENT_RUN_STALE_MINUTES", "120")), 1)
    except ValueError:
        return 120

def get_worker_heartbeat_stale_seconds():
    try:
        return max(int(os.getenv("AGENT_WORKER_HEARTBEAT_STALE_SECONDS", "30")), 5)
    except ValueError:
        return 30

def get_agent_runs_today(session: Session, user_id: int):
    today_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return session.exec(
        select(AgentRun).where(
            AgentRun.user_id == user_id,
            AgentRun.started_at >= today_start,
        )
    ).all()

def ensure_agent_quota(session: Session, user: User):
    quota_limit = get_daily_agent_run_limit(user)
    runs_used = len(get_agent_runs_today(session, user.id))
    if runs_used >= quota_limit:
        raise HTTPException(
            status_code=403,
            detail=f"Daily agent run limit reached for your {user.subscription_tier} plan.",
        )
    return quota_limit, quota_limit - runs_used

def get_agent_quota_status(session: Session, user: User):
    quota_limit = get_daily_agent_run_limit(user)
    runs_used = len(get_agent_runs_today(session, user.id))
    return {
        "agent_runs_used_today": runs_used,
        "agent_run_limit": quota_limit,
        "agent_runs_remaining": max(quota_limit - runs_used, 0),
        "auto_apply_enabled": can_auto_apply(user),
    }

def persist_auto_apply_audit(session: Session, user_id: int, agent_run_id: Optional[int], audit_records: list[dict]):
    for record in audit_records:
        job_url = record.get("job_url")
        if not job_url:
            continue
        session.add(
            AutoApplyAudit(
                user_id=user_id,
                agent_run_id=agent_run_id,
                auto_apply_attempt_id=record.get("auto_apply_attempt_id"),
                job_url=job_url,
                job_title=record.get("job_title"),
                company=record.get("company"),
                action=record.get("action", "submit"),
                status=record.get("status", "unknown"),
                message=record.get("message"),
            )
        )

def fail_stale_agent_runs(session: Session):
    stale_before = utc_now() - timedelta(minutes=get_agent_run_stale_minutes())
    stale_runs = session.exec(
        select(AgentRun).where(
            AgentRun.status == "running",
            AgentRun.claimed_at.is_not(None),
            AgentRun.claimed_at < stale_before,
        )
    ).all()
    for run in stale_runs:
        run.status = "failed"
        run.error = "Agent run timed out while claimed by a worker."
        run.logs = (run.logs or []) + [run.error]
        run.completed_at = utc_now()
        session.add(run)
    if stale_runs:
        session.commit()
    return len(stale_runs)

def claim_next_queued_agent_run():
    with Session(engine) as session:
        fail_stale_agent_runs(session)
        run = session.exec(
            select(AgentRun)
            .where(AgentRun.status == "queued")
            .order_by(AgentRun.started_at.asc())
        ).first()
        if not run:
            return None

        run.status = "running"
        run.claimed_at = utc_now()
        run.logs = (run.logs or []) + ["Agent workflow claimed by worker"]
        session.add(run)
        session.commit()
        session.refresh(run)
        return {
            "agent_run_id": run.id,
            "user_id": run.user_id,
            "auto_apply": run.auto_apply,
        }

async def run_next_queued_agent_run():
    claim = claim_next_queued_agent_run()
    if not claim:
        return False

    await execute_agent_run(
        claim["agent_run_id"],
        claim["user_id"],
        claim["auto_apply"],
    )
    return True

def get_worker_health_snapshot(session: Session):
    now = utc_now()
    runner_mode = get_agent_runner_mode()
    worker_expected = runner_mode == "worker"
    heartbeat_stale_before = now - timedelta(seconds=get_worker_heartbeat_stale_seconds())
    run_stale_before = now - timedelta(minutes=get_agent_run_stale_minutes())

    latest_heartbeat = session.exec(
        select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc())
    ).first()
    queued_runs = session.exec(
        select(AgentRun).where(AgentRun.status == "queued")
    ).all()
    running_runs = session.exec(
        select(AgentRun).where(AgentRun.status == "running")
    ).all()
    stale_runs = [
        run
        for run in running_runs
        if run.claimed_at is not None and run.claimed_at < run_stale_before
    ]
    oldest_queued = session.exec(
        select(AgentRun)
        .where(AgentRun.status == "queued")
        .order_by(AgentRun.started_at.asc())
    ).first()

    heartbeat_status = "not_expected"
    heartbeat_age_seconds = None
    if latest_heartbeat:
        heartbeat_age_seconds = max((now - latest_heartbeat.last_seen_at).total_seconds(), 0)
        heartbeat_status = (
            "fresh"
            if latest_heartbeat.last_seen_at >= heartbeat_stale_before
            else "stale"
        )
    elif worker_expected:
        heartbeat_status = "missing"

    overall_status = "ok"
    if worker_expected and heartbeat_status != "fresh":
        overall_status = "degraded"
    if latest_heartbeat and latest_heartbeat.status == "error":
        overall_status = "degraded"
    if stale_runs:
        overall_status = "degraded"

    return {
        "status": overall_status,
        "service": "job-finder-api",
        "checked_at": now,
        "runner_mode": runner_mode,
        "worker_expected": worker_expected,
        "heartbeat_status": heartbeat_status,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "heartbeat_worker_id": latest_heartbeat.worker_id if latest_heartbeat else None,
        "heartbeat_worker_status": latest_heartbeat.status if latest_heartbeat else None,
        "heartbeat_last_seen_at": latest_heartbeat.last_seen_at if latest_heartbeat else None,
        "queued_runs": len(queued_runs),
        "running_runs": len(running_runs),
        "stale_running_runs": len(stale_runs),
        "stale_run_ids": [run.id for run in stale_runs if run.id is not None],
        "oldest_queued_at": oldest_queued.started_at if oldest_queued else None,
    }

@router.get("/health", response_model=HealthResponse)
def health_check():
    return {
        "status": "ok",
        "service": "job-finder-api",
        "checked_at": utc_now(),
    }

@router.get("/health/db", response_model=DatabaseHealthResponse)
def database_health_check(session: Session = Depends(get_session)):
    try:
        session.exec(text("SELECT 1")).first()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database health check failed: {exc}") from exc
    return {
        "status": "ok",
        "service": "job-finder-api",
        "checked_at": utc_now(),
        "database": "reachable",
        "migration_mode": "alembic" if USE_ALEMBIC_MIGRATIONS else "lightweight",
    }

@router.get("/health/worker", response_model=WorkerHealthResponse)
def worker_health_check(response: Response, session: Session = Depends(get_session)):
    snapshot = get_worker_health_snapshot(session)
    if snapshot["status"] != "ok":
        response.status_code = 503
    return snapshot

def serialize_agent_run(run: AgentRun, audit_records: Optional[list[AutoApplyAudit]] = None):
    return {
        "id": run.id,
        "status": run.status,
        "auto_apply": run.auto_apply,
        "logs": run.logs,
        "applications_count": run.applications_count,
        "found_jobs_count": run.found_jobs_count,
        "error": run.error,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "auto_apply_audit": audit_records or [],
    }

def serialize_resume_export(record: Resume):
    return {
        "id": record.id,
        "filename": record.filename,
        "uploaded_at": record.upload_date,
        "skills": record.skills or [],
        "summary": record.summary,
        "content_text": record.content,
        "file_content_base64": (
            base64.b64encode(record.file_content).decode("ascii")
            if record.file_content
            else None
        ),
    }

def serialize_generated_package_export(app: Application):
    return {
        "application_id": app.id,
        "job_title": app.job_title,
        "company": app.company,
        "status": app.status,
        "fit_score": app.fit_score,
        "cover_letter": app.cover_letter,
        "cover_letter_pdf_url": (
            f"/applications/{app.id}/cover-letter.pdf"
            if app.id is not None and app.cover_letter
            else None
        ),
        "created_at": app.created_at,
    }

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
            review_record.message or "Fill-for-review completed.",
            {
                "fields_filled_count": len(review_record.fields_filled or []),
                "needs_review_count": len(review_record.fields_missing or []) + len(review_record.blockers or []),
            },
        )
    ])[-50:]
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
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
    return attempt

def normalize_policy_list(values: Optional[list[str]]) -> list[str]:
    if not values:
        return []
    normalized = []
    for value in values:
        item = str(value or "").strip()
        if item:
            normalized.append(item)
    return normalized[:50]

def serialize_submit_settings(settings: ApplicationSubmitSettings):
    return {
        "id": settings.id,
        "true_submit_enabled": settings.true_submit_enabled,
        "require_human_confirmation": settings.require_human_confirmation,
        "min_fit_score": settings.min_fit_score,
        "max_submits_per_day": settings.max_submits_per_day,
        "allowed_companies": settings.allowed_companies or [],
        "denied_companies": settings.denied_companies or [],
        "allowed_domains": settings.allowed_domains or [],
        "denied_domains": settings.denied_domains or [],
        "allowed_job_title_keywords": settings.allowed_job_title_keywords or [],
        "consented_at": settings.consented_at,
        "updated_at": settings.updated_at,
    }

def get_or_create_submit_settings(session: Session, user_id: int):
    settings = session.exec(
        select(ApplicationSubmitSettings).where(ApplicationSubmitSettings.user_id == user_id)
    ).first()
    if settings:
        return settings

    settings = ApplicationSubmitSettings(user_id=user_id)
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings

def update_submit_settings_from_payload(
    session: Session,
    settings: ApplicationSubmitSettings,
    payload: ApplicationSubmitSettingsRequest,
):
    settings.true_submit_enabled = payload.true_submit_enabled and payload.consent_to_submit
    settings.require_human_confirmation = payload.require_human_confirmation
    settings.min_fit_score = min(max(payload.min_fit_score, 0), 100)
    settings.max_submits_per_day = min(max(payload.max_submits_per_day, 0), 50)
    settings.allowed_companies = normalize_policy_list(payload.allowed_companies)
    settings.denied_companies = normalize_policy_list(payload.denied_companies)
    settings.allowed_domains = normalize_policy_list(payload.allowed_domains)
    settings.denied_domains = normalize_policy_list(payload.denied_domains)
    settings.allowed_job_title_keywords = normalize_policy_list(payload.allowed_job_title_keywords)
    settings.consented_at = utc_now() if settings.true_submit_enabled else None
    settings.updated_at = utc_now()
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings

def domain_matches(hostname: str, patterns: list[str]) -> bool:
    normalized_host = hostname.lower().removeprefix("www.")
    for pattern in patterns:
        normalized_pattern = pattern.lower().removeprefix("www.")
        if normalized_host == normalized_pattern or normalized_host.endswith(f".{normalized_pattern}"):
            return True
    return False

def get_latest_fill_review(session: Session, user_id: int, application_id: int):
    return session.exec(
        select(ApplicationFillReview)
        .where(ApplicationFillReview.user_id == user_id, ApplicationFillReview.application_id == application_id)
        .order_by(ApplicationFillReview.created_at.desc())
    ).first()

def get_submits_today_count(session: Session, user_id: int):
    today_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    submit_audits = session.exec(
        select(AutoApplyAudit).where(
            AutoApplyAudit.user_id == user_id,
            AutoApplyAudit.action == "submit",
            AutoApplyAudit.status.in_(["submitted", "success", "succeeded", "completed"]),
            AutoApplyAudit.created_at >= today_start,
        )
    ).all()
    if submit_audits:
        return len(submit_audits)

    return len(session.exec(
        select(Application).where(
            Application.user_id == user_id,
            Application.status == "Submitted",
            Application.created_at >= today_start,
        )
    ).all())

def evaluate_submit_readiness(
    *,
    app: Application,
    user: User,
    settings: ApplicationSubmitSettings,
    answer_profile: Optional[ApplicationAnswerProfile],
    latest_review: Optional[ApplicationFillReview],
    submits_today_count: int,
):
    blockers: list[str] = []
    warnings: list[str] = [
        "This check does not submit the application. Use final confirmation to inspect the submit control; automated clicking remains disabled."
    ]
    checks: list[str] = []
    application_url = app.resolved_url or app.job_url
    hostname = (urlparse(application_url or "").hostname or "").lower().removeprefix("www.")

    if not can_auto_apply(user):
        blockers.append("Pro plan or admin access is required for final-submit workflows.")
    else:
        checks.append("Plan allows advanced submission workflows.")

    if not settings.true_submit_enabled:
        blockers.append("True submit mode is off in submission settings.")
    else:
        checks.append("True submit mode has explicit user consent.")

    if settings.require_human_confirmation:
        checks.append("Per-application human confirmation is required.")

    if app.resolution_status != "resolved":
        blockers.append("Resolve this application link before final-submit review.")
    elif app.ats_type not in ApplicationFillReviewService.SUPPORTED_ATS:
        blockers.append("This ATS is not supported for deterministic final-submit review.")
    else:
        checks.append(f"{app.ats_type} is a supported deterministic ATS adapter.")

    if int((app.fit_score or 0) * 100) < settings.min_fit_score:
        blockers.append(f"Fit score is below the submit threshold of {settings.min_fit_score}%.")
    else:
        checks.append("Fit score meets the submit threshold.")

    company = (app.company or "").lower()
    if any(item.lower() in company for item in settings.denied_companies or []):
        blockers.append("Company matches the denylist.")
    if settings.allowed_companies and not any(item.lower() in company for item in settings.allowed_companies):
        blockers.append("Company is not on the allowlist.")
    if hostname and domain_matches(hostname, settings.denied_domains or []):
        blockers.append("Application domain matches the denylist.")
    if settings.allowed_domains and not domain_matches(hostname, settings.allowed_domains):
        blockers.append("Application domain is not on the allowlist.")

    title = (app.job_title or "").lower()
    if settings.allowed_job_title_keywords and not any(keyword.lower() in title for keyword in settings.allowed_job_title_keywords):
        blockers.append("Job title does not match the allowed title keywords.")

    if settings.max_submits_per_day <= submits_today_count:
        blockers.append("Daily final-submit limit has been reached.")
    else:
        checks.append("Daily final-submit limit has room.")

    if not answer_profile or not answer_profile.consent_to_use_answers:
        blockers.append("Application answer consent must be enabled before final-submit review.")
    else:
        required_answers = {
            "Work authorization": answer_profile.work_authorized_us,
            "Sponsorship now": answer_profile.requires_sponsorship_now,
            "Sponsorship future": answer_profile.requires_sponsorship_future,
        }
        missing = [
            label
            for label, value in required_answers.items()
            if value in ("unspecified", "prefer_not_to_answer", None, "")
        ]
        if missing:
            blockers.append(f"Required application answers are incomplete: {', '.join(missing)}.")
        else:
            checks.append("Required work-authorization answers are complete.")

    if not latest_review:
        blockers.append("Run fill-for-review before final-submit readiness can be evaluated.")
    else:
        if latest_review.blockers:
            blockers.append("Latest fill-review attempt still has blockers.")
        if latest_review.fields_missing:
            blockers.append("Latest fill-review attempt still has missing fields.")
        if not latest_review.blockers and not latest_review.fields_missing:
            checks.append("Latest fill-review attempt has no saved blockers or missing fields.")

    ready = len(blockers) == 0
    return {
        "application_id": app.id,
        "ready": ready,
        "can_submit": False,
        "status": "ready_for_confirmation" if ready else "blocked",
        "message": (
            "This application is ready for a future final confirmation step."
            if ready
            else "This application is not ready for final-submit confirmation yet."
        ),
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "evaluated_at": utc_now(),
    }

def unavailable_submit_control(blockers: Optional[list[str]] = None):
    return {
        "status": "unavailable",
        "detected": False,
        "confidence": 0.0,
        "label": None,
        "selector": None,
        "button_type": None,
        "current_url": None,
        "evidence": [],
        "blockers": blockers or [],
        "warnings": [],
    }

def serialize_submit_control_detection(detection):
    data = detection.model_dump() if hasattr(detection, "model_dump") else dict(detection or {})
    return {
        "status": data.get("status", "unavailable"),
        "detected": bool(data.get("detected", False)),
        "confidence": float(data.get("confidence", 0.0) or 0.0),
        "label": data.get("label"),
        "selector": data.get("selector"),
        "button_type": data.get("button_type"),
        "current_url": data.get("current_url"),
        "evidence": data.get("evidence") or [],
        "blockers": data.get("blockers") or [],
        "warnings": data.get("warnings") or [],
    }

def build_submit_confirmation_response(app: Application, readiness: dict, submit_control: dict):
    blockers = list(readiness.get("blockers") or [])
    warnings = list(readiness.get("warnings") or [])
    checks = list(readiness.get("checks") or [])

    if readiness.get("ready"):
        blockers.extend(submit_control.get("blockers") or [])
        warnings.extend(submit_control.get("warnings") or [])
        if submit_control.get("detected") and submit_control.get("confidence", 0.0) >= 0.85:
            checks.append("Final submit control was detected with high confidence.")
        elif submit_control.get("detected"):
            blockers.append("Final submit control confidence is below the 85% threshold.")
        elif not submit_control.get("blockers"):
            blockers.append("Final submit control was not detected.")

    warnings.append("No automated final click was performed.")
    ready = readiness.get("ready") and len(blockers) == 0
    return {
        "application_id": app.id,
        "ready": ready,
        "can_submit": False,
        "status": "ready_for_human_confirmation" if ready else "blocked",
        "message": (
            "This application is ready for a human final confirmation. Automated final submit is still disabled."
            if ready
            else "This application is not ready for final confirmation yet."
        ),
        "readiness": readiness,
        "submit_control": submit_control,
        "blockers": blockers,
        "warnings": list(dict.fromkeys(warnings)),
        "checks": checks,
        "evaluated_at": utc_now(),
    }

APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS = {
    "work_authorized_us": "unspecified",
    "requires_sponsorship_now": "unspecified",
    "requires_sponsorship_future": "unspecified",
    "willing_to_relocate": "unspecified",
    "remote_preference": "unspecified",
    "earliest_start_date": None,
    "notice_period": None,
    "desired_salary": None,
    "work_authorization_notes": None,
    "gender": "prefer_not_to_answer",
    "race_ethnicity": "prefer_not_to_answer",
    "veteran_status": "prefer_not_to_answer",
    "disability_status": "prefer_not_to_answer",
}

APPLICATION_ANSWER_AUDIT_FIELDS = tuple(
    APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS.keys()
) + (
    "consent_to_use_answers",
    "consent_to_use_demographics",
)


def encrypt_application_answer_payload(payload: dict) -> dict:
    encrypted = dict(payload)
    for field in APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS:
        encrypted[field] = encrypt_text(encrypted.get(field))
    return encrypted


def decrypt_application_answer_profile(record: Optional[ApplicationAnswerProfile]) -> Optional[ApplicationAnswerProfile]:
    if not record:
        return None

    data = record.model_dump()
    for field, fallback in APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS.items():
        data[field] = decrypt_text(data.get(field), fallback=fallback)
    return ApplicationAnswerProfile(**data)


def serialize_application_answer_profile(record: Optional[ApplicationAnswerProfile]):
    decrypted = decrypt_application_answer_profile(record)
    if not decrypted:
        return None

    data = {
        field: getattr(decrypted, field)
        for field in APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS
    }
    data.update({
        "id": decrypted.id,
        "consent_to_use_answers": decrypted.consent_to_use_answers,
        "consent_to_use_demographics": decrypted.consent_to_use_demographics,
        "updated_at": decrypted.updated_at,
    })
    return data


def audit_application_answer_access(
    session: Session,
    *,
    user_id: int,
    action: str,
    access_reason: str,
    source: str,
    application_id: Optional[int] = None,
    fields: Optional[list[str]] = None,
    commit: bool = True,
):
    audit = ApplicationAnswerAudit(
        user_id=user_id,
        application_id=application_id,
        action=action,
        access_reason=access_reason,
        source=source,
        fields=fields or list(APPLICATION_ANSWER_AUDIT_FIELDS),
    )
    session.add(audit)
    if commit:
        session.commit()
        session.refresh(audit)
    return audit


def sanitize_application_answer_payload(payload: ApplicationAnswerProfileRequest) -> dict:
    data = payload.model_dump()
    if not data.get("consent_to_use_demographics"):
        data["gender"] = "prefer_not_to_answer"
        data["race_ethnicity"] = "prefer_not_to_answer"
        data["veteran_status"] = "prefer_not_to_answer"
        data["disability_status"] = "prefer_not_to_answer"
    return data

async def execute_agent_run(agent_run_id: int, user_id: int, auto_apply: bool):
    with Session(engine) as session:
        agent_run = session.get(AgentRun, agent_run_id)
        user = session.get(User, user_id)
        if not agent_run or not user:
            return

        try:
            agent_run.status = "running"
            agent_run.claimed_at = agent_run.claimed_at or utc_now()
            agent_run.logs = ["Agent workflow started"]
            session.add(agent_run)
            session.commit()

            resume = get_latest_resume(session, user_id)
            prefs = get_latest_preferences(session, user_id)
            profile = session.exec(select(Profile).where(Profile.user_id == user_id)).first()

            if not resume:
                raise ValueError("Please upload a resume first")

            initial_state = {
                "resume": resume.content,
                "resume_bytes": resume.file_content,
                "resume_filename": resume.filename,
                "resume_summary": None,
                "extracted_skills": [],
                "preferences": prefs,
                "profile": profile,
                "found_jobs": [],
                "current_job": None,
                "application_status": "searching",
                "applications_submitted": [],
                "logs": ["Agent workflow started"],
                "user_id": user_id,
                "agent_run_id": agent_run_id,
                "auto_apply": auto_apply,
                "auto_apply_audit": [],
            }

            result = await agent_graph.ainvoke(initial_state)

            if result.get("extracted_skills") or result.get("resume_summary"):
                resume.skills = result.get("extracted_skills", [])
                resume.summary = result.get("resume_summary")
                session.add(resume)

            agent_run.status = result.get("application_status", "completed")
            agent_run.logs = result.get("logs", [])
            agent_run.applications_count = len(result.get("applications_submitted", []))
            agent_run.found_jobs_count = result.get("total_found_jobs", len(result.get("found_jobs", [])))
            agent_run.completed_at = utc_now()
            persist_auto_apply_audit(session, user_id, agent_run.id, result.get("auto_apply_audit", []))
            session.add(agent_run)
            session.commit()
        except Exception as e:
            agent_run.status = "failed"
            agent_run.error = str(e)
            agent_run.logs = (agent_run.logs or []) + [f"Agent failed: {e}"]
            agent_run.completed_at = utc_now()
            session.add(agent_run)
            session.commit()

@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    email = payload.email
    password = payload.password
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please register.")
    
    if not user.hashed_password:
        raise HTTPException(status_code=400, detail="User account has no password set (possibly social login).")

    if not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    return auth_response(user, session)

@router.post("/auth/refresh", response_model=AuthResponse)
def refresh_auth_session(payload: RefreshTokenRequest, session: Session = Depends(get_session)):
    response = rotate_auth_session(payload.refresh_token, session)
    if not response:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    return response

@router.post("/auth/register", response_model=AuthResponse)
def register_user(payload: RegisterRequest, session: Session = Depends(get_session)):
    email = payload.email
    password = payload.password
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    
    existing_user = session.exec(select(User).where(User.email == email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    
    # Create User
    user = User(email=email, hashed_password=hash_password(password), subscription_tier="free")
    session.add(user)
    session.commit()
    session.refresh(user)
    
    # Create Profile
    profile_data = payload.profile
    new_profile = Profile(
        user_id=user.id,
        first_name=profile_data.first_name,
        last_name=profile_data.last_name,
        email=email,
        phone=profile_data.phone,
        location=profile_data.location,
        linkedin_url=profile_data.linkedin_url,
        portfolio_url=profile_data.portfolio_url,
        github_url=profile_data.github_url,
        years_experience=profile_data.years_experience,
        expected_salary=profile_data.expected_salary,
    )
    session.add(new_profile)
    session.commit()
    session.refresh(user)
    
    response = auth_response(user, session)
    response["message"] = "User registered successfully"
    return response

@router.get("/auth/google/login")
def google_login():
    return RedirectResponse(get_google_oauth_url())

@router.get("/auth/google/callback")
def google_callback(code: str, session: Session = Depends(get_session)):
    # 1. Exchange code for token using requests
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": GOOGLE_REDIRECT_URI,
    }
    
    try:
        token_response = requests.post(token_url, data=data)
        token_data = token_response.json()
        
        if "error" in token_data:
            return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?error={quote(token_data.get('error_description', 'Google Auth Error'))}")
        
        access_token = token_data.get("access_token")
        
        # 2. Get user info
        user_info_response = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        user_info = user_info_response.json()
        email = user_info.get("email")
        first_name = user_info.get("given_name", "")
        last_name = user_info.get("family_name", "")

        if not email:
            return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?error=No email received from Google")

        # 3. Handle user in DB
        user = session.exec(select(User).where(User.email == email)).first()
        if not user:
            user = User(email=email, subscription_tier="free")
            session.add(user)
            session.commit()
            session.refresh(user)
            
            profile = Profile(
                user_id=user.id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone="",
                location=""
            )
            session.add(profile)
            session.commit()
        
        auth = auth_response(user, session)
        params = urlencode({"token": auth["access_token"], "refresh_token": auth["refresh_token"], "email": email})
        return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?{params}")
    except Exception as e:
        print(f"Error in Google callback: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?error=Internal server error during Google login")

@router.get("/auth/linkedin/login")
def linkedin_login():
    return RedirectResponse(get_linkedin_oauth_url())

@router.get("/auth/linkedin/callback")
def linkedin_callback(code: str, session: Session = Depends(get_session)):
    try:
        # 1. Exchange code for token
        token_url = "https://www.linkedin.com/oauth/v2/accessToken"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LINKEDIN_REDIRECT_URI,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        token_response = requests.post(token_url, data=data, headers=headers)
        token_data = token_response.json()
        
        if "error" in token_data:
            return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?error={quote(token_data.get('error_description', 'LinkedIn Auth Error'))}")
        
        access_token = token_data.get("access_token")
        
        # 2. Get user data (OpenID Connect compliant endpoint)
        user_info_url = "https://api.linkedin.com/v2/userinfo"
        user_response = requests.get(
            user_info_url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        user_data = user_response.json()
        
        email = user_data.get("email")
        if not email:
            return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?error=No email received from LinkedIn")

        first_name = user_data.get("given_name", "")
        last_name = user_data.get("family_name", "")

        # 3. Handle user in DB
        user = session.exec(select(User).where(User.email == email)).first()
        if not user:
            user = User(email=email, subscription_tier="free")
            session.add(user)
            session.commit()
            session.refresh(user)
            
            profile = Profile(
                user_id=user.id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone="",
                location=""
            )
            session.add(profile)
            session.commit()
        
        auth = auth_response(user, session)
        params = urlencode({"token": auth["access_token"], "refresh_token": auth["refresh_token"], "email": email})
        return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?{params}")
    except Exception as e:
        print(f"Error in LinkedIn callback: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?error=Internal server error during LinkedIn login")

@router.post("/auth/social", response_model=AuthResponse)
def legacy_social_login(payload: SocialAuthRequest, session: Session = Depends(get_session)):
    # Kept for compatibility but we now use redirect flow
    email = payload.email
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        user = User(email=email, subscription_tier="free")
        session.add(user)
        session.commit()
        session.refresh(user)
    return auth_response(user, session)

@router.post("/auth/logout", response_model=MessageResponse)
def logout(
    payload: Optional[RefreshTokenRequest] = None,
    session: Session = Depends(get_session),
    authorization: Optional[str] = Header(None)
):
    token = authorization.split(" ", 1)[1].strip() if authorization else ""
    access_payload = decode_access_token(token)
    token_id = access_payload.get("jti") if access_payload else None
    auth_session = None
    if token_id:
        auth_session = session.exec(
            select(AuthSession).where(AuthSession.token_id == token_id)
        ).first()
    if not auth_session and payload and payload.refresh_token:
        auth_session = find_auth_session_from_refresh(payload.refresh_token, session)

    revoke_auth_session(auth_session, session)
    return {"message": "Signed out successfully"}

@router.post("/upload-resume", response_model=ResumeUploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    content = await file.read()
    try:
        text_content = ResumeService.parse_resume(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing resume: {str(e)}")

    resume = Resume(
        user_id=user.id,
        content=text_content,
        file_content=content,
        filename=file.filename
    )
    session.add(resume)
    session.commit()
    session.refresh(resume)
    return {"id": resume.id, "filename": resume.filename, "message": "Resume uploaded successfully"}

@router.get("/search-jobs")
def search_jobs(query: str, location: str):
    return JobSearchService.search_jobs(query, location)

@router.post("/preferences", response_model=JobPreferenceResponse)
def create_preferences(
    prefs: JobPreferenceRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    preference_data = prefs.model_dump()
    scoped_preferences = JobPreference(**preference_data, user_id=user.id)
    session.add(scoped_preferences)
    session.commit()
    session.refresh(scoped_preferences)
    return scoped_preferences

@router.get("/profile", response_model=Optional[ProfileResponse])
def get_profile(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    return profile

@router.post("/profile", response_model=MessageResponse)
def update_profile(profile_data: ProfileRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    existing_profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    if existing_profile:
        for key, value in profile_data.model_dump().items():
            setattr(existing_profile, key, value)
        existing_profile.updated_at = utc_now()
        session.add(existing_profile)
    else:
        session.add(Profile(**profile_data.model_dump(), user_id=user.id))
    session.commit()
    return {"message": "Profile updated successfully"}

@router.get("/application-profile/export", response_model=ApplicationAnswerExportResponse)
def export_application_profile(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    answer_profile_record = session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user.id)
    ).first()
    profile = serialize_application_answer_profile(answer_profile_record)
    if answer_profile_record:
        audit_application_answer_access(
            session,
            user_id=user.id,
            action="export",
            access_reason="user_requested_export",
            source="application_profile_export",
        )
    return {
        "profile": profile,
        "exported_at": utc_now(),
        "message": "Application answers exported." if profile else "No saved application answers to export.",
    }

@router.get("/application-profile/audit", response_model=List[ApplicationAnswerAuditResponse])
def get_application_profile_audit(
    limit: int = 50,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    safe_limit = max(min(limit, 100), 1)
    query = (
        select(ApplicationAnswerAudit)
        .where(ApplicationAnswerAudit.user_id == user.id)
        .order_by(ApplicationAnswerAudit.created_at.desc())
        .limit(safe_limit)
    )
    return session.exec(query).all()

@router.get("/account/export", response_model=AccountDataExportResponse)
def export_account_data(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if user.id is None:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user.id
    exported_at = utc_now()

    resumes = session.exec(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(Resume.upload_date.desc())
    ).all()
    preferences = session.exec(
        select(JobPreference)
        .where(JobPreference.user_id == user_id)
        .order_by(JobPreference.created_at.desc())
    ).all()
    profile = session.exec(select(Profile).where(Profile.user_id == user_id)).first()
    answer_profile_record = session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user_id)
    ).first()
    application_profile = serialize_application_answer_profile(answer_profile_record)
    if answer_profile_record:
        audit_application_answer_access(
            session,
            user_id=user_id,
            action="export",
            access_reason="account_data_export",
            source="account_export",
        )

    application_answer_audit = session.exec(
        select(ApplicationAnswerAudit)
        .where(ApplicationAnswerAudit.user_id == user_id)
        .order_by(ApplicationAnswerAudit.created_at.desc())
    ).all()
    submission_settings = session.exec(
        select(ApplicationSubmitSettings).where(ApplicationSubmitSettings.user_id == user_id)
    ).first()
    applications = session.exec(
        select(Application)
        .where(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
    ).all()
    agent_runs = session.exec(
        select(AgentRun)
        .where(AgentRun.user_id == user_id)
        .order_by(AgentRun.started_at.desc())
    ).all()
    auto_apply_audit = session.exec(
        select(AutoApplyAudit)
        .where(AutoApplyAudit.user_id == user_id)
        .order_by(AutoApplyAudit.created_at.desc())
    ).all()
    audit_by_run: dict[int, list[AutoApplyAudit]] = {}
    for audit_record in auto_apply_audit:
        if audit_record.agent_run_id is not None:
            audit_by_run.setdefault(audit_record.agent_run_id, []).append(audit_record)

    fill_reviews = session.exec(
        select(ApplicationFillReview)
        .where(ApplicationFillReview.user_id == user_id)
        .order_by(ApplicationFillReview.created_at.desc())
    ).all()
    automation_attempts = session.exec(
        select(AutoApplyAttempt)
        .where(AutoApplyAttempt.user_id == user_id)
        .order_by(AutoApplyAttempt.created_at.desc())
    ).all()

    generated_packages = [
        serialize_generated_package_export(application)
        for application in applications
        if application.cover_letter
    ]
    serialized_fill_reviews = [
        serialize_fill_review_record(review)
        for review in fill_reviews
    ]
    serialized_attempts = [
        serialize_auto_apply_attempt(attempt)
        for attempt in automation_attempts
    ]

    counts = {
        "resumes": len(resumes),
        "preferences": len(preferences),
        "applications": len(applications),
        "generated_packages": len(generated_packages),
        "agent_runs": len(agent_runs),
        "fill_reviews": len(fill_reviews),
        "automation_attempts": len(automation_attempts),
        "auto_apply_audit": len(auto_apply_audit),
        "application_answer_audit": len(application_answer_audit),
    }

    return {
        "user": user,
        "exported_at": exported_at,
        "resumes": [serialize_resume_export(resume) for resume in resumes],
        "preferences": preferences,
        "profile": profile,
        "application_profile": application_profile,
        "application_answer_audit": application_answer_audit,
        "submission_settings": serialize_submit_settings(submission_settings) if submission_settings else None,
        "applications": applications,
        "generated_packages": generated_packages,
        "agent_runs": [
            serialize_agent_run(run, audit_by_run.get(run.id or 0, []))
            for run in agent_runs
        ],
        "fill_reviews": serialized_fill_reviews,
        "automation_attempts": serialized_attempts,
        "auto_apply_audit": auto_apply_audit,
        "counts": counts,
        "message": "Account data exported.",
    }

@router.get("/application-profile", response_model=Optional[ApplicationAnswerProfileResponse])
def get_application_profile(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    answer_profile_record = session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user.id)
    ).first()
    profile = serialize_application_answer_profile(answer_profile_record)
    if answer_profile_record:
        audit_application_answer_access(
            session,
            user_id=user.id,
            action="view",
            access_reason="user_opened_application_answers",
            source="application_profile",
        )
    return profile

@router.post("/application-profile", response_model=ApplicationAnswerProfileResponse)
def update_application_profile(
    profile_data: ApplicationAnswerProfileRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    payload = encrypt_application_answer_payload(sanitize_application_answer_payload(profile_data))
    existing_profile = session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user.id)
    ).first()
    if existing_profile:
        for key, value in payload.items():
            setattr(existing_profile, key, value)
        existing_profile.updated_at = utc_now()
        answer_profile = existing_profile
    else:
        answer_profile = ApplicationAnswerProfile(**payload, user_id=user.id)

    session.add(answer_profile)
    session.commit()
    session.refresh(answer_profile)
    response = serialize_application_answer_profile(answer_profile)
    audit_application_answer_access(
        session,
        user_id=user.id,
        action="upsert",
        access_reason="user_saved_application_answers",
        source="application_profile",
    )
    return response

@router.delete("/application-profile", response_model=MessageResponse)
def delete_application_profile(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    answer_profile = session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user.id)
    ).first()
    if answer_profile:
        audit_application_answer_access(
            session,
            user_id=user.id,
            action="delete",
            access_reason="user_reset_application_answers",
            source="application_profile",
            commit=False,
        )
        session.delete(answer_profile)
        session.commit()
    return {"message": "Application answers reset successfully"}

@router.get("/submission-settings", response_model=ApplicationSubmitSettingsResponse)
def get_submission_settings(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    settings = get_or_create_submit_settings(session, user.id)
    return serialize_submit_settings(settings)

@router.post("/submission-settings", response_model=ApplicationSubmitSettingsResponse)
def update_submission_settings(
    payload: ApplicationSubmitSettingsRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    settings = get_or_create_submit_settings(session, user.id)
    updated = update_submit_settings_from_payload(session, settings, payload)
    return serialize_submit_settings(updated)

@router.delete("/submission-settings", response_model=ApplicationSubmitSettingsResponse)
def reset_submission_settings(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    existing = session.exec(
        select(ApplicationSubmitSettings).where(ApplicationSubmitSettings.user_id == user.id)
    ).first()
    if existing:
        session.delete(existing)
        session.commit()
    settings = get_or_create_submit_settings(session, user.id)
    return serialize_submit_settings(settings)

@router.post("/agent/run", response_model=AgentRunResponse)
async def run_agent(
    background_tasks: BackgroundTasks,
    auto_apply: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    # Get latest resume, preferences and profile
    resume = get_latest_resume(session, user.id)

    if not resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first")

    if auto_apply and not can_auto_apply(user):
        raise HTTPException(
            status_code=403,
            detail="Browser fill-for-review requires a pro plan.",
        )

    quota_limit, quota_remaining_before_run = ensure_agent_quota(session, user)
    agent_run = AgentRun(
        user_id=user.id,
        status="queued",
        auto_apply=auto_apply,
        logs=[
            "Agent workflow queued for worker"
            if get_agent_runner_mode() == "worker"
            else "Agent workflow queued"
        ],
    )
    session.add(agent_run)
    session.commit()
    session.refresh(agent_run)

    if should_schedule_background_agent_run():
        background_tasks.add_task(execute_agent_run, agent_run.id, user.id, auto_apply)

    return {
        "status": "queued",
        "logs": agent_run.logs,
        "applications_count": 0,
        "found_jobs_count": 0,
        "agent_run_id": agent_run.id,
        "quota_limit": quota_limit,
        "quota_remaining": max(quota_remaining_before_run - 1, 0),
    }

@router.get("/agent/runs", response_model=List[AgentRunRecordResponse])
def get_agent_runs(
    limit: int = 10,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    query = (
        select(AgentRun)
        .where(AgentRun.user_id == user.id)
        .order_by(AgentRun.started_at.desc())
        .limit(min(max(limit, 1), 50))
    )
    runs = session.exec(query).all()
    return [serialize_agent_run(run) for run in runs]

@router.get("/agent/runs/{run_id}", response_model=AgentRunRecordResponse)
def get_agent_run(
    run_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    run = session.get(AgentRun, run_id)
    if not run or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="Agent run not found")

    audit_records = session.exec(
        select(AutoApplyAudit)
        .where(AutoApplyAudit.agent_run_id == run.id, AutoApplyAudit.user_id == user.id)
        .order_by(AutoApplyAudit.created_at.asc())
    ).all()
    return serialize_agent_run(run, audit_records)

@router.get("/applications", response_model=List[ApplicationResponse])
def get_applications(
    limit: Optional[int] = None,
    sort: str = "date",
    direction: str = "desc",
    status: Optional[str] = None,
    match_bucket: str = "all",
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    query = select(Application).where(Application.user_id == user.id)

    if status:
        query = query.where(Application.status == status)

    if match_bucket != "all":
        latest_prefs = get_latest_preferences(session, user.id)
        min_match_score = latest_prefs.min_match_score if latest_prefs else 70
        threshold = min_match_score / 100

        if match_bucket == "strong":
            query = query.where(
                Application.pre_screen_status != "reject",
                Application.status != "Screened Out",
                Application.fit_score >= threshold,
            )
        elif match_bucket == "below_threshold":
            query = query.where(
                Application.pre_screen_status != "reject",
                Application.status != "Screened Out",
                Application.fit_score > 0,
                Application.fit_score < threshold,
            )
        elif match_bucket == "screened_out":
            query = query.where(
                (Application.pre_screen_status == "reject") | (Application.status == "Screened Out")
            )
        else:
            raise HTTPException(status_code=400, detail="match_bucket must be one of: all, strong, below_threshold, screened_out")

    sort_columns = {
        "date": Application.created_at,
        "score": Application.fit_score,
        "company": Application.company,
        "role": Application.job_title,
    }
    sort_column = sort_columns.get(sort, Application.created_at)
    sort_direction = asc if direction == "asc" else desc
    query = query.order_by(sort_direction(sort_column))

    if limit and limit > 0:
        query = query.limit(min(limit, 100))

    return session.exec(query).all()

@router.post("/applications/{app_id}/resolve-link", response_model=ApplicationResponse)
async def resolve_application_link(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    resolution = await ApplicationLinkResolver.resolve_url(app.source_url or app.job_url)
    app.source_url = resolution.original_url
    app.resolved_url = resolution.resolved_url
    app.source_type = resolution.source_type
    app.ats_type = resolution.ats_type
    app.resolution_status = resolution.resolution_status
    app.resolution_notes = resolution.notes

    session.add(app)
    session.commit()
    session.refresh(app)
    return app

@router.delete("/applications", response_model=MessageResponse)
def clear_applications(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    applications = session.exec(select(Application).where(Application.user_id == user.id)).all()
    for app in applications:
        session.delete(app)
    session.commit()
    return {"message": f"Cleared {len(applications)} applications"}

@router.post("/agent/analyze-single", response_model=JobAnalysisResponse)
async def analyze_single_job(
    job_data: JobAnalysisRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    resume = get_latest_resume(session, user.id)
    prefs = get_latest_preferences(session, user.id)
    
    if not resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first")

    # Use OpenAI to analyze just this job
    llm = get_llm(model_type="openai")
    parser = JsonOutputParser()
    
    # We can reuse the prompt logic from nodes.py or just implement it here for simplicity
    criteria = {
        "Desired Experience Level": ", ".join(prefs.experience_level) if prefs else "Not specified",
        "Desired Job Type": ", ".join(prefs.job_type) if prefs else "Not specified"
    }
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a world class career assistant. Analyze the fit between the candidate's resume and the job description. Return JSON with 'score' (0-1), 'explanation', and 'cover_letter'."),
        ("user", "Job: {job_title} at {company}\nDescription: {description}\n\nResume Summary: {resume_summary}\n\nUser Profile/Preferences: {prefs}\n\nAnalyze fit:")
    ])
    
    chain = prompt | llm | parser
    
    result = await chain.ainvoke({
        "job_title": job_data.title,
        "company": job_data.company,
        "description": job_data.description or "",
        "resume_summary": resume.content[:5000], # Use raw content if summary not yet generated
        "prefs": json.dumps(criteria)
    })
    
    return result

@router.get("/user/status", response_model=UserStatusResponse)
def get_user_status(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    resume = get_latest_resume(session, user.id)
    prefs = get_latest_preferences(session, user.id)
    profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    application_profile = session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user.id)
    ).first()
    serialized_application_profile = serialize_application_answer_profile(application_profile)
    if application_profile:
        audit_application_answer_access(
            session,
            user_id=user.id,
            action="view",
            access_reason="dashboard_preload",
            source="user_status",
        )

    return {
        "user": user,
        "resume": {
            "filename": resume.filename,
            "uploaded_at": resume.upload_date,
            "skills": resume.skills,
            "summary": resume.summary
        } if resume else None,
        "preferences": {
            "role": prefs.role,
            "location": prefs.location,
            "job_type": prefs.job_type,
            "experience_level": prefs.experience_level,
            "target_companies": getattr(prefs, "target_companies", []),
            "posted_within_days": prefs.posted_within_days,
            "min_match_score": prefs.min_match_score
        } if prefs else None,
        "profile": {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
            "phone": profile.phone,
            "location": profile.location,
            "linkedin_url": profile.linkedin_url,
            "portfolio_url": profile.portfolio_url,
            "github_url": profile.github_url,
            "years_experience": profile.years_experience,
            "expected_salary": profile.expected_salary,
        } if profile else None,
        "application_profile": serialized_application_profile,
        "quota": get_agent_quota_status(session, user)
    }

@router.get("/admin/config")
def get_admin_config(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    # Enforce Admin Access
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    config = session.exec(select(ScraperConfig).order_by(ScraperConfig.updated_at.desc())).first()
    if not config:
        return ScraperConfig() # Return defaults
    return config

@router.put("/admin/config", response_model=MessageResponse)
def update_admin_config(new_config: ScraperConfig, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    # Enforce Admin Access
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    config = session.exec(select(ScraperConfig).order_by(ScraperConfig.updated_at.desc())).first()
    if config:
        config.site_names = new_config.site_names
        config.results_wanted = new_config.results_wanted
        config.country_indeed = new_config.country_indeed
        config.updated_at = utc_now()
        session.add(config)
    else:
        session.add(new_config)
    session.commit()
    return {"message": "Configuration updated"}

@router.post("/auth/forgot-password", response_model=MessageResponse)
def forgot_password(payload: EmailRequest, session: Session = Depends(get_session)):
    email = payload.email
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
        
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        # Mock behavior: pretend we sent it
        return {"message": "If this email is registered, a reset link has been sent."}
    
    token_str = str(uuid4())
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token_str,
        expires_at=utc_now() + timedelta(hours=1)
    )
    session.add(reset_token)
    session.commit()
    
    # MOCK EMAIL -> REAL EMAIL
    reset_link = f"{FRONTEND_URL}/reset-password?token={token_str}"
    
    # Send email (prints to log if creds are missing)
    send_reset_email(email, reset_link)
    
    return {"message": "Password reset link sent to your email."}

@router.post("/auth/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, session: Session = Depends(get_session)):
    token = payload.token
    new_password = payload.password
    
    if not token or not new_password:
        raise HTTPException(status_code=400, detail="Token and password required")
        
    reset_record = session.exec(select(PasswordResetToken).where(PasswordResetToken.token == token)).first()
    if not reset_record:
        raise HTTPException(status_code=400, detail="Invalid token")
        
    if reset_record.expires_at < utc_now():
        session.delete(reset_record)
        session.commit()
        raise HTTPException(status_code=400, detail="Token expired")
        
    user = session.get(User, reset_record.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    user.hashed_password = hash_password(new_password)
    session.add(user)
    session.delete(reset_record) # Consume token
    session.commit()
    
    return {"message": "Password updated successfully"}


# ─── Application Package ────────────────────────────────────────────────────

@router.post("/applications/{app_id}/fill-review", response_model=ApplicationFillReviewResponse)
async def fill_application_for_review(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    assert_application_matches_threshold(app, session, user.id, "fill-for-review")

    application_url = app.resolved_url or app.job_url
    link_resolution = ApplicationLinkResolver.classify_url(application_url)
    ats_type = app.ats_type or link_resolution.ats_type
    if app.resolution_status != "resolved" or not application_url:
        raise HTTPException(status_code=400, detail="Resolve this application link before fill-for-review")
    if ats_type not in ApplicationFillReviewService.SUPPORTED_ATS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Fill-for-review currently supports Greenhouse, Lever, Ashby, SmartRecruiters, "
                "Workday, BambooHR, iCIMS, Recruitee, and Taleo links only"
            ),
        )

    resume = get_latest_resume(session, user.id)
    profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    answer_profile = decrypt_application_answer_profile(session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user.id)
    ).first())
    if answer_profile:
        audit_application_answer_access(
            session,
            user_id=user.id,
            action="automation_use",
            access_reason="fill_for_review",
            source="browser_fill_review",
            application_id=app.id,
        )

    if not resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first")
    if not profile:
        raise HTTPException(status_code=400, detail="Please complete your candidate profile first")

    attempt = create_auto_apply_attempt(
        session,
        user_id=user.id,
        app=app,
        mode="fill_for_review",
        status="filling",
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
        "Browser fill-for-review started.",
        {"application_url": application_url},
    )

    fill_result = await ApplicationFillReviewService.fill_application_for_review(
        application_url=application_url,
        ats_type=ats_type,
        profile=profile,
        resume_bytes=resume.file_content,
        resume_filename=resume.filename,
        answer_profile=answer_profile if answer_profile and answer_profile.consent_to_use_answers else None,
        cover_letter=app.cover_letter,
    )

    review_record = ApplicationFillReview(
        user_id=user.id,
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
        user_id=user.id,
        application_id=app.id,
        review_id=review_record.id,
        kind="screenshot",
        payload_base64=fill_result.screenshot_base64,
        extension="png",
    )
    review_record.trace_path = FillReviewArtifactStore.save_base64(
        user_id=user.id,
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
    return response

@router.post("/applications/{app_id}/submit-readiness", response_model=ApplicationSubmitReadinessResponse)
def check_application_submit_readiness(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    settings = get_or_create_submit_settings(session, user.id)
    answer_profile = decrypt_application_answer_profile(session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user.id)
    ).first())
    if answer_profile:
        audit_application_answer_access(
            session,
            user_id=user.id,
            action="automation_read",
            access_reason="submit_readiness",
            source="submit_readiness",
            application_id=app.id,
        )
    latest_review = get_latest_fill_review(session, user.id, app.id)
    submits_today_count = get_submits_today_count(session, user.id)

    return evaluate_submit_readiness(
        app=app,
        user=user,
        settings=settings,
        answer_profile=answer_profile,
        latest_review=latest_review,
        submits_today_count=submits_today_count,
    )

@router.post("/applications/{app_id}/submit-confirmation", response_model=ApplicationSubmitConfirmationResponse)
async def create_application_submit_confirmation(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    settings = get_or_create_submit_settings(session, user.id)
    answer_profile = decrypt_application_answer_profile(session.exec(
        select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == user.id)
    ).first())
    if answer_profile:
        audit_application_answer_access(
            session,
            user_id=user.id,
            action="automation_read",
            access_reason="submit_confirmation",
            source="submit_confirmation",
            application_id=app.id,
        )
    latest_review = get_latest_fill_review(session, user.id, app.id)
    readiness = evaluate_submit_readiness(
        app=app,
        user=user,
        settings=settings,
        answer_profile=answer_profile,
        latest_review=latest_review,
        submits_today_count=get_submits_today_count(session, user.id),
    )

    submit_control = unavailable_submit_control(["Resolve readiness blockers before final submit control detection."])
    if readiness["ready"]:
        detection = await ApplicationFillReviewService.detect_final_submit_control(
            application_url=app.resolved_url or app.job_url,
            ats_type=app.ats_type or "",
        )
        submit_control = serialize_submit_control_detection(detection)

    response = build_submit_confirmation_response(app, readiness, submit_control)
    attempt = get_latest_auto_apply_attempt(session, user.id, app.id)
    if not attempt:
        attempt = create_auto_apply_attempt(
            session,
            user_id=user.id,
            app=app,
            mode="submit_confirmation",
            status="confirming",
        )
    if latest_review and not attempt.fill_review_id:
        attempt.fill_review_id = latest_review.id
        attempt.screenshot_path = latest_review.screenshot_path
        attempt.trace_path = latest_review.trace_path
        session.add(attempt)
        session.commit()
        session.refresh(attempt)

    attempt = append_attempt_step(
        session,
        attempt,
        "readiness_checked",
        "success" if readiness.get("ready") else "blocked",
        readiness.get("message"),
        {
            "blockers_count": len(readiness.get("blockers") or []),
            "checks_count": len(readiness.get("checks") or []),
        },
    )
    if submit_control:
        attempt = append_attempt_step(
            session,
            attempt,
            "submit_control_detection",
            submit_control.get("status", "unavailable"),
            (
                "Final submit control inspected without clicking."
                if submit_control.get("detected")
                else blocked_reason_from_lists(submit_control.get("blockers") or []) or "Final submit control was not detected."
            ),
            {
                "detected": bool(submit_control.get("detected")),
                "confidence": submit_control.get("confidence"),
                "label": submit_control.get("label"),
            },
        )
    attempt = update_attempt_from_confirmation(session, attempt, response)
    response["attempt_id"] = attempt.id
    session.add(
        AutoApplyAudit(
            user_id=user.id,
            auto_apply_attempt_id=attempt.id,
            job_url=app.resolved_url or app.job_url,
            job_title=app.job_title,
            company=app.company,
            action="submit_confirmation",
            status="ready" if response["ready"] else "blocked",
            message=response["message"],
        )
    )
    session.commit()
    return response

@router.get("/applications/{app_id}/fill-reviews", response_model=List[ApplicationFillReviewRecordResponse])
def get_application_fill_reviews(
    app_id: int,
    limit: int = 10,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    query = (
        select(ApplicationFillReview)
        .where(ApplicationFillReview.application_id == app.id, ApplicationFillReview.user_id == user.id)
        .order_by(ApplicationFillReview.created_at.desc())
        .limit(min(max(limit, 1), 25))
    )
    return [serialize_fill_review_record(record) for record in session.exec(query).all()]

@router.get("/applications/{app_id}/automation-attempts", response_model=List[AutoApplyAttemptResponse])
def get_application_automation_attempts(
    app_id: int,
    limit: int = 10,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    query = (
        select(AutoApplyAttempt)
        .where(AutoApplyAttempt.application_id == app.id, AutoApplyAttempt.user_id == user.id)
        .order_by(AutoApplyAttempt.created_at.desc())
        .limit(min(max(limit, 1), 25))
    )
    return [serialize_auto_apply_attempt(attempt) for attempt in session.exec(query).all()]

@router.get("/applications/{app_id}/fill-reviews/{review_id}/screenshot")
def get_application_fill_review_screenshot(
    app_id: int,
    review_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    review = session.get(ApplicationFillReview, review_id)
    if (
        not app
        or app.user_id != user.id
        or not review
        or review.user_id != user.id
        or review.application_id != app.id
    ):
        raise HTTPException(status_code=404, detail="Fill-review screenshot not found")
    if not FillReviewArtifactStore.is_readable(review.screenshot_path):
        raise HTTPException(status_code=404, detail="Fill-review screenshot not found")

    return FileResponse(
        review.screenshot_path,
        media_type="image/png",
        filename=f"fill-review-{review.id}-screenshot.png",
    )

@router.get("/applications/{app_id}/fill-reviews/{review_id}/trace")
def get_application_fill_review_trace(
    app_id: int,
    review_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    review = session.get(ApplicationFillReview, review_id)
    if (
        not app
        or app.user_id != user.id
        or not review
        or review.user_id != user.id
        or review.application_id != app.id
    ):
        raise HTTPException(status_code=404, detail="Fill-review trace not found")
    if not FillReviewArtifactStore.is_readable(review.trace_path):
        raise HTTPException(status_code=404, detail="Fill-review trace not found")

    return FileResponse(
        review.trace_path,
        media_type="application/zip",
        filename=f"fill-review-{review.id}-trace.zip",
    )

@router.delete("/applications/{app_id}/fill-reviews", response_model=MessageResponse)
def clear_application_fill_reviews(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    reviews = session.exec(
        select(ApplicationFillReview)
        .where(ApplicationFillReview.application_id == app.id, ApplicationFillReview.user_id == user.id)
    ).all()
    for review in reviews:
        linked_attempts = session.exec(
            select(AutoApplyAttempt).where(
                AutoApplyAttempt.user_id == user.id,
                AutoApplyAttempt.application_id == app.id,
                AutoApplyAttempt.fill_review_id == review.id,
            )
        ).all()
        for attempt in linked_attempts:
            attempt.fill_review_id = None
            attempt.screenshot_path = None
            attempt.trace_path = None
            attempt.updated_at = utc_now()
            session.add(attempt)
        FillReviewArtifactStore.delete(review.screenshot_path)
        FillReviewArtifactStore.delete(review.trace_path)
        session.delete(review)
    session.commit()
    return {"message": f"Cleared {len(reviews)} fill-review record{'' if len(reviews) == 1 else 's'}"}

@router.post("/agent/prepare-application", response_model=ApplicationPackageResponse)
async def prepare_application(
    job_data: ApplicationPackageRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Generates a full application package: tailored cover letter, talking points,
    tailored resume summary, and common Q&A answers for a specific job.
    """
    resume = get_latest_resume(session, user.id)
    profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    prefs = get_latest_preferences(session, user.id)
    package_app = None

    if job_data.app_id:
        package_app = session.get(Application, job_data.app_id)
        if not package_app or package_app.user_id != user.id:
            raise HTTPException(status_code=404, detail="Application not found")
        assert_application_matches_threshold(
            package_app,
            session,
            user.id,
            "application package generation",
        )

    if not resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first")

    import asyncio

    llm = get_llm(model_type="openai")
    parser = JsonOutputParser()

    profile_info = ""
    if profile:
        profile_info = f"Name: {profile.first_name} {profile.last_name}, Email: {profile.email}"
        if profile.phone:
            profile_info += f", Phone: {profile.phone}"
        if profile.linkedin_url:
            profile_info += f", LinkedIn: {profile.linkedin_url}"
        if profile.expected_salary:
            profile_info += f", Expected Salary: {profile.expected_salary}"

    job_title = job_data.title
    company = job_data.company
    description = job_data.description[:5000]
    resume_content = resume.content[:3500]
    prefs_json = json.dumps({
        "experience_level": prefs.experience_level if prefs else [],
        "job_type": prefs.job_type if prefs else []
    })

    # ── Prompt 1: Application package (cover letter, summary, Q&A, talking points) ──
    package_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert career coach and professional writer. Generate a complete application package.

Return a JSON object with exactly these keys:
- "cover_letter": A professional, personalized cover letter (3-4 paragraphs). Address to 'Hiring Manager'. Sign off with candidate's full name.
- "tailored_summary": A 2-3 sentence resume summary tailored to this job, mirroring its keywords.
- "talking_points": A list of 4-5 concise bullet strings — strongest selling points for THIS specific role.
- "qa_answers": A list of 5 objects each with "question" and "answer" covering:
  1. Why do you want to work at {company}?
  2. Describe your most relevant experience for this role.
  3. What is your greatest professional achievement?
  4. Why are you leaving your current role? (answer positively)
  5. What are your salary expectations?"""),
        ("user", "Job: {job_title} at {company}\nDescription: {description}\n\nCandidate: {profile_info}\nResume: {resume_content}\nPrefs: {prefs}\n\nGenerate the package:")
    ])

    # ── Prompt 2: Interview prep + company brief ──
    interview_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert interview coach. Generate interview preparation material and a company brief.

Return a JSON object with exactly these keys:
- "interview_questions": A list of 8 objects each with "question" (likely interview question for this role) and "suggested_answer" (tailored to the candidate's background).
  Include: 2 behavioural (STAR format), 2 technical/role-specific, 2 situational, 1 "tell me about yourself", 1 "do you have any questions for us?" with 3 suggested questions.
- "company_brief": An object with:
  - "overview": 2-3 sentences about what the company does
  - "mission": Their likely mission or values (1-2 sentences)
  - "culture_signals": A list of 3-4 short strings about their culture based on the job description language
  - "questions_to_ask": A list of 3 smart questions the candidate should ask the interviewer"""),
        ("user", "Job: {job_title} at {company}\nDescription: {description}\n\nCandidate Resume: {resume_content}\n\nGenerate interview prep and company brief:")
    ])

    package_chain = package_prompt | llm | parser
    interview_chain = interview_prompt | llm | parser

    # Run both LLM calls in parallel
    package_result, interview_result = await asyncio.gather(
        package_chain.ainvoke({
            "job_title": job_title,
            "company": company,
            "description": description,
            "profile_info": profile_info,
            "resume_content": resume_content,
            "prefs": prefs_json
        }),
        interview_chain.ainvoke({
            "job_title": job_title,
            "company": company,
            "description": description,
            "resume_content": resume_content,
        }),
        return_exceptions=True
    )

    # Merge results safely (one failing shouldn't break the other)
    result: dict = {}
    if isinstance(package_result, dict):
        result.update(package_result)
    if isinstance(interview_result, dict):
        result["interview_questions"] = interview_result.get("interview_questions", [])
        result["company_brief"] = interview_result.get("company_brief", {})

    # Update cover letter on the application record if app_id provided
    if package_app:
        package_app.cover_letter = result.get("cover_letter", "")
        session.add(package_app)
        session.commit()

    return result


@router.get("/applications/{app_id}/cover-letter.pdf")
def download_cover_letter_pdf(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Generates and streams a professionally formatted cover letter PDF.
    """
    from fpdf import FPDF

    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    if not app.cover_letter:
        raise HTTPException(status_code=400, detail="No cover letter available for this application")

    profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()

    # ── Build PDF ──────────────────────────────────────────────────────────
    pdf = FPDF()
    pdf.set_margins(25, 25, 25)
    pdf.add_page()

    # Header — candidate name & contact
    pdf.set_font("Helvetica", "B", 18)
    if profile:
        pdf.cell(0, 10, f"{profile.first_name} {profile.last_name}", ln=True)
        pdf.set_font("Helvetica", "", 10)
        contact_parts = [profile.email]
        if profile.phone:
            contact_parts.append(profile.phone)
        if profile.linkedin_url:
            contact_parts.append(profile.linkedin_url)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, "  |  ".join(contact_parts), ln=True)
        pdf.set_text_color(0, 0, 0)
    else:
        pdf.cell(0, 10, "Cover Letter", ln=True)

    # Divider line
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.4)
    pdf.line(25, pdf.get_y() + 3, 185, pdf.get_y() + 3)
    pdf.ln(8)

    # Date
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, datetime.now().strftime("%B %d, %Y"), ln=True)
    pdf.ln(4)

    # Job info
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, f"Re: {app.job_title} — {app.company}", ln=True)
    pdf.ln(6)

    # Cover letter body — handle encoding & line wrapping
    pdf.set_font("Helvetica", "", 11)
    pdf.set_line_height(1.5)

    clean_text = app.cover_letter.encode("latin-1", errors="replace").decode("latin-1")
    paragraphs = clean_text.split("\n")
    for para in paragraphs:
        para = para.strip()
        if para:
            pdf.multi_cell(0, 7, para)
            pdf.ln(3)
        else:
            pdf.ln(3)

    # Output to bytes
    pdf_bytes = bytes(pdf.output())
    filename = f"cover_letter_{app.company.replace(' ', '_')}_{app.job_title.replace(' ', '_')}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.patch("/applications/{app_id}/status", response_model=ApplicationStatusResponse)
def update_application_status(
    app_id: int,
    payload: ApplicationStatusRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Update the status of an application (e.g. mark as Applied)."""
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    new_status = payload.status
    if not new_status:
        raise HTTPException(status_code=400, detail="Status is required")
    app.status = new_status
    session.add(app)
    session.commit()
    return {"message": "Status updated", "status": new_status}


# ─── Resume Improvement Feedback ───────────────────────────────────────────

@router.post("/agent/resume-feedback", response_model=ResumeFeedbackResponse)
async def get_resume_feedback(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Analyses the user's uploaded resume and returns specific, actionable
    improvement suggestions grouped by category.
    """
    resume = get_latest_resume(session, user.id)
    if not resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first")

    prefs = get_latest_preferences(session, user.id)
    target_roles = ", ".join(prefs.role) if prefs and prefs.role else "not specified"

    llm = get_llm(model_type="openai")
    parser = JsonOutputParser()

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a world-class resume reviewer and career coach.
Analyse the candidate's resume and return a JSON object with exactly these keys:

- "overall_score": An integer 0-100 representing the resume's overall quality.
- "overall_assessment": 2-3 sentences summarising the resume's strengths and biggest gaps.
- "categories": A list of objects, each with:
  - "name": Category name (e.g. "Impact & Quantification", "Action Verbs", "Keywords & ATS", "Structure & Formatting", "Skills Section", "Summary/Objective")
  - "score": Integer 0-100 for this category
  - "issues": A list of specific problems found (strings)
  - "suggestions": A list of specific, actionable fixes (strings)
- "quick_wins": A list of 3-5 short strings — the most impactful single changes to make right now.
- "missing_keywords": A list of skills/keywords commonly expected for the target roles that are absent from the resume."""),
        ("user", "Target Roles: {target_roles}\n\nResume:\n{resume_content}\n\nProvide detailed feedback:")
    ])

    chain = prompt | llm | parser
    result = await chain.ainvoke({
        "target_roles": target_roles,
        "resume_content": resume.content[:6000]
    })
    return result
