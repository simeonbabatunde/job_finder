from fastapi import APIRouter, BackgroundTasks, UploadFile, File, HTTPException, Depends, Header, Response, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import RedirectResponse, StreamingResponse
import base64
import hmac
import io
import os
import re
import secrets
import time
import zipfile
from sqlalchemy import asc, desc, or_, text
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
    MatchingProfile,
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
from app.services.agent_run_control import (
    CANCEL_REQUESTED_STATUS,
    CANCELED_STATUS,
    CANCELABLE_AGENT_RUN_STATUSES,
    mark_run_canceled,
)
from app.services.fill_review_artifacts import FillReviewArtifactStore
from app.services.field_encryption import (
    data_encryption_key_is_configured,
    decrypt_text,
    encrypt_text,
)
from app.observability import log_event, url_host
from app.schemas import (
    AccountDataExportResponse,
    AgentRunResponse,
    AgentRunRecordResponse,
    ApplicationAnswerProfileRequest,
    ApplicationAnswerAuditResponse,
    ApplicationAnswerExportResponse,
    ApplicationAnswerProfileResponse,
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
    BillingSessionResponse,
    BillingStatusResponse,
    AutoApplyAttemptResponse,
    DatabaseHealthResponse,
    EmailRequest,
    HealthResponse,
    JobAnalysisRequest,
    JobAnalysisResponse,
    JobPreferenceRequest,
    JobPreferenceResponse,
    MatchingProfileCreateRequest,
    MatchingProfileRequest,
    MatchingProfileResponse,
    LoginRequest,
    MessageResponse,
    ProfileRequest,
    RefreshTokenRequest,
    ProfileResponse,
    RegisterRequest,
    ResumeFeedbackResponse,
    ResumeLibraryResponse,
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
from app.agent.llm_factory import LLMConfigurationError, get_llm, validate_llm_config
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
import bcrypt
import hashlib
import requests
import stripe
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
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY") or os.getenv("SECRET_KEY") or "jobmatchkit-dev-secret-change-me"
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
PRO_PLAN_PRICE_LABEL = os.getenv("PRO_PLAN_PRICE_LABEL", "$10/mo")
STRIPE_ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
INSECURE_AUTH_SECRET_VALUES = {
    "",
    "change-me-in-production",
    "jobmatchkit-dev-secret-change-me",
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
        "subscription_status": user.subscription_status,
        "subscription_current_period_end": user.subscription_current_period_end,
        "subscription_cancel_at_period_end": user.subscription_cancel_at_period_end,
        "role": user.role,
    }

def get_stripe_secret_key():
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def get_stripe_webhook_secret():
    return os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()


def get_stripe_pro_price_id():
    return os.getenv("STRIPE_PRO_PRICE_ID", "").strip()


def stripe_billing_is_configured():
    return bool(get_stripe_secret_key() and get_stripe_pro_price_id())


def stripe_api_key_or_error():
    secret_key = get_stripe_secret_key()
    if not secret_key or not get_stripe_pro_price_id():
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured for this environment.",
        )
    stripe.api_key = secret_key
    return secret_key


def frontend_billing_url(kind: str):
    configured = os.getenv(f"BILLING_{kind.upper()}_URL", "").strip()
    if configured:
        return configured
    base_url = (os.getenv("FRONTEND_URL", "").strip() or FRONTEND_URL or "http://localhost:5173").rstrip("/")
    return f"{base_url}/settings?billing={kind}"


def stripe_value(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def stripe_metadata_value(obj, key: str):
    metadata = stripe_value(obj, "metadata", {}) or {}
    if isinstance(metadata, dict):
        return metadata.get(key)
    return getattr(metadata, key, None)


def stripe_timestamp_to_datetime(value):
    if not value:
        return None
    try:
        return datetime.utcfromtimestamp(int(value))
    except (TypeError, ValueError, OSError):
        return None


def find_user_for_billing_event(session: Session, *, user_id=None, customer_id=None, subscription_id=None):
    if user_id:
        try:
            user = session.get(User, int(user_id))
            if user:
                return user
        except (TypeError, ValueError):
            pass
    if subscription_id:
        user = session.exec(select(User).where(User.stripe_subscription_id == subscription_id)).first()
        if user:
            return user
    if customer_id:
        return session.exec(select(User).where(User.stripe_customer_id == customer_id)).first()
    return None


def update_user_subscription_from_stripe(
    user: User,
    *,
    customer_id=None,
    subscription_id=None,
    status=None,
    price_id=None,
    current_period_end=None,
    cancel_at_period_end=False,
):
    if customer_id:
        user.stripe_customer_id = customer_id
    if subscription_id:
        user.stripe_subscription_id = subscription_id
    if price_id:
        user.stripe_price_id = price_id
    user.subscription_status = status
    user.subscription_current_period_end = current_period_end
    user.subscription_cancel_at_period_end = bool(cancel_at_period_end)
    user.subscription_tier = "pro" if status in STRIPE_ACTIVE_SUBSCRIPTION_STATUSES else "free"
    user.billing_updated_at = utc_now()


def billing_status_for_user(user: User):
    billing_enabled = stripe_billing_is_configured()
    can_manage = bool(billing_enabled and user.stripe_customer_id)
    return {
        "plan": user.subscription_tier,
        "subscription_status": user.subscription_status,
        "subscription_current_period_end": user.subscription_current_period_end,
        "subscription_cancel_at_period_end": user.subscription_cancel_at_period_end,
        "billing_enabled": billing_enabled,
        "can_upgrade": bool(billing_enabled and user.subscription_tier != "pro"),
        "can_manage_billing": can_manage,
        "pro_price_label": os.getenv("PRO_PLAN_PRICE_LABEL", PRO_PLAN_PRICE_LABEL),
        "message": "Billing is ready." if billing_enabled else "Billing is not configured in this environment.",
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

def extract_subscription_price_id(subscription):
    items = stripe_value(subscription, "items", {}) or {}
    item_data = stripe_value(items, "data", []) or []
    first_item = item_data[0] if item_data else None
    price = stripe_value(first_item, "price", {}) if first_item else {}
    return stripe_value(price, "id") or get_stripe_pro_price_id() or None


def create_or_get_stripe_customer(user: User, session: Session):
    stripe_api_key_or_error()
    if user.stripe_customer_id:
        return user.stripe_customer_id

    try:
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"user_id": str(user.id), "app": "jobmatchkit"},
        )
    except Exception as exc:
        log_event("billing.customer_create_failed", level="error", user_id=user.id, error=str(exc))
        raise HTTPException(status_code=502, detail="Billing provider error. Please try again.")

    customer_id = stripe_value(customer, "id")
    if not customer_id:
        raise HTTPException(status_code=502, detail="Billing provider did not return a customer ID.")
    user.stripe_customer_id = customer_id
    user.billing_updated_at = utc_now()
    session.add(user)
    session.commit()
    session.refresh(user)
    return customer_id


def construct_stripe_event(payload: bytes, signature: Optional[str]):
    webhook_secret = get_stripe_webhook_secret()
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook signing secret is not configured.")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")
    try:
        return stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook payload.")
    except Exception as exc:
        if exc.__class__.__name__ == "SignatureVerificationError":
            raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature.")
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook payload.")


def handle_checkout_session_completed(checkout_session, db_session: Session):
    user_id = stripe_metadata_value(checkout_session, "user_id") or stripe_value(checkout_session, "client_reference_id")
    customer_id = stripe_value(checkout_session, "customer")
    subscription_id = stripe_value(checkout_session, "subscription")
    payment_status = stripe_value(checkout_session, "payment_status")
    user = find_user_for_billing_event(
        db_session,
        user_id=user_id,
        customer_id=customer_id,
        subscription_id=subscription_id,
    )
    if not user:
        log_event("billing.checkout_user_not_found", level="warning", customer_id=customer_id, subscription_id=subscription_id)
        return

    status = "active" if payment_status in {"paid", "no_payment_required"} else "incomplete"
    update_user_subscription_from_stripe(
        user,
        customer_id=customer_id,
        subscription_id=subscription_id,
        status=status,
        price_id=get_stripe_pro_price_id() or user.stripe_price_id,
    )
    db_session.add(user)
    db_session.commit()


def handle_subscription_event(subscription, db_session: Session, *, deleted: bool = False):
    customer_id = stripe_value(subscription, "customer")
    subscription_id = stripe_value(subscription, "id")
    user_id = stripe_metadata_value(subscription, "user_id")
    user = find_user_for_billing_event(
        db_session,
        user_id=user_id,
        customer_id=customer_id,
        subscription_id=subscription_id,
    )
    if not user:
        log_event("billing.subscription_user_not_found", level="warning", customer_id=customer_id, subscription_id=subscription_id)
        return

    status = "canceled" if deleted else stripe_value(subscription, "status")
    update_user_subscription_from_stripe(
        user,
        customer_id=customer_id,
        subscription_id=subscription_id,
        status=status,
        price_id=extract_subscription_price_id(subscription),
        current_period_end=stripe_timestamp_to_datetime(stripe_value(subscription, "current_period_end")),
        cancel_at_period_end=stripe_value(subscription, "cancel_at_period_end", False),
    )
    db_session.add(user)
    db_session.commit()



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

@router.get("/billing/status", response_model=BillingStatusResponse)
def get_billing_status(user: User = Depends(get_current_user)):
    return billing_status_for_user(user)


@router.post("/billing/checkout-session", response_model=BillingSessionResponse)
def create_billing_checkout_session(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stripe_api_key_or_error()
    if user.subscription_tier == "pro" and user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="You are already on Pro. Use Manage billing instead.")

    customer_id = create_or_get_stripe_customer(user, session)
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            client_reference_id=str(user.id),
            line_items=[{"price": get_stripe_pro_price_id(), "quantity": 1}],
            success_url=frontend_billing_url("success"),
            cancel_url=frontend_billing_url("cancelled"),
            allow_promotion_codes=True,
            metadata={"user_id": str(user.id), "plan": "pro"},
            subscription_data={"metadata": {"user_id": str(user.id), "plan": "pro"}},
        )
    except Exception as exc:
        log_event("billing.checkout_create_failed", level="error", user_id=user.id, error=str(exc))
        raise HTTPException(status_code=502, detail="Billing provider error. Please try again.")

    checkout_url = stripe_value(checkout_session, "url")
    if not checkout_url:
        raise HTTPException(status_code=502, detail="Billing provider did not return a checkout URL.")
    return {"url": checkout_url}


@router.post("/billing/customer-portal", response_model=BillingSessionResponse)
def create_billing_customer_portal(user: User = Depends(get_current_user)):
    stripe_api_key_or_error()
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Upgrade to Pro before opening billing management.")

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=frontend_billing_url("portal_return"),
        )
    except Exception as exc:
        log_event("billing.portal_create_failed", level="error", user_id=user.id, error=str(exc))
        raise HTTPException(status_code=502, detail="Billing provider error. Please try again.")

    portal_url = stripe_value(portal_session, "url")
    if not portal_url:
        raise HTTPException(status_code=502, detail="Billing provider did not return a portal URL.")
    return {"url": portal_url}


@router.post("/billing/webhook", response_model=MessageResponse)
async def handle_stripe_billing_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    session: Session = Depends(get_session),
):
    event = construct_stripe_event(await request.body(), stripe_signature)
    event_type = stripe_value(event, "type")
    event_data = stripe_value(event, "data", {}) or {}
    event_object = stripe_value(event_data, "object", {}) or {}

    if event_type == "checkout.session.completed":
        handle_checkout_session_completed(event_object, session)
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        handle_subscription_event(event_object, session)
    elif event_type == "customer.subscription.deleted":
        handle_subscription_event(event_object, session, deleted=True)
    elif event_type == "invoice.payment_failed":
        log_event("billing.invoice_payment_failed", level="warning", customer_id=stripe_value(event_object, "customer"))
    elif event_type == "invoice.paid":
        log_event("billing.invoice_paid", customer_id=stripe_value(event_object, "customer"))

    return {"message": "Webhook received."}


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

def serialize_resume_status(resume: Optional[Resume]):
    if not resume:
        return None
    return {
        "id": resume.id,
        "filename": resume.filename,
        "uploaded_at": resume.upload_date,
        "skills": resume.skills or [],
        "summary": resume.summary,
    }


def matching_profile_payload(profile: MatchingProfile) -> dict:
    return {
        "role": profile.role or [],
        "experience_level": profile.experience_level or ["Intermediate"],
        "location": profile.location or [],
        "job_type": profile.job_type or ["Full-time"],
        "target_companies": profile.target_companies or [],
        "min_match_score": profile.min_match_score or 70,
        "posted_within_days": profile.posted_within_days or 7,
    }


def matching_profile_has_saved_targets(profile: Optional[MatchingProfile]) -> bool:
    if not profile:
        return False
    payload = matching_profile_payload(profile)
    return bool(payload["role"] or payload["location"] or payload["target_companies"])


def apply_matching_profile_payload(profile: MatchingProfile, payload: MatchingProfileRequest, user_id: int, session: Session) -> None:
    resume_id = payload.resume_id
    if resume_id is not None:
        resume = session.get(Resume, resume_id)
        if not resume or resume.user_id != user_id:
            raise HTTPException(status_code=404, detail="Resume not found")
    profile.name = (payload.name or "Untitled profile").strip()[:120] or "Untitled profile"
    profile.resume_id = resume_id
    profile.role = normalize_policy_list(payload.role)
    profile.experience_level = normalize_policy_list(payload.experience_level) or ["Intermediate"]
    profile.location = normalize_policy_list(payload.location)
    profile.job_type = normalize_policy_list(payload.job_type) or ["Full-time"]
    profile.target_companies = normalize_policy_list(payload.target_companies)
    profile.min_match_score = max(0, min(int(payload.min_match_score or 70), 100))
    profile.posted_within_days = max(1, min(int(payload.posted_within_days or 7), 90))
    profile.updated_at = utc_now()


def serialize_matching_profile(profile: MatchingProfile, session: Optional[Session] = None):
    resume = session.get(Resume, profile.resume_id) if session and profile.resume_id else None
    return {
        "id": profile.id,
        "name": profile.name,
        "resume_id": profile.resume_id,
        **matching_profile_payload(profile),
        "is_default": bool(profile.is_default),
        "is_archived": bool(profile.is_archived),
        "last_used_at": profile.last_used_at,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "resume": serialize_resume_status(resume),
    }


def create_default_matching_profile(session: Session, user_id: int) -> MatchingProfile:
    resume = get_latest_resume(session, user_id)
    prefs = get_latest_preferences(session, user_id)
    profile = MatchingProfile(
        user_id=user_id,
        name="Default profile",
        resume_id=resume.id if resume else None,
        role=(prefs.role if prefs else []),
        experience_level=(prefs.experience_level if prefs else ["Intermediate"]),
        location=(prefs.location if prefs else []),
        job_type=(prefs.job_type if prefs else ["Full-time"]),
        target_companies=(getattr(prefs, "target_companies", []) if prefs else []),
        min_match_score=(prefs.min_match_score if prefs else 70),
        posted_within_days=(prefs.posted_within_days if prefs else 7),
        is_default=True,
        is_archived=False,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def get_default_matching_profile(session: Session, user_id: int, create: bool = True) -> Optional[MatchingProfile]:
    profile = session.exec(
        select(MatchingProfile)
        .where(
            MatchingProfile.user_id == user_id,
            MatchingProfile.is_default == True,
            MatchingProfile.is_archived == False,
        )
        .order_by(MatchingProfile.updated_at.desc())
    ).first()
    if profile:
        return profile
    profile = session.exec(
        select(MatchingProfile)
        .where(MatchingProfile.user_id == user_id, MatchingProfile.is_archived == False)
        .order_by(MatchingProfile.updated_at.desc())
    ).first()
    if profile:
        profile.is_default = True
        profile.updated_at = utc_now()
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile
    return create_default_matching_profile(session, user_id) if create else None


def get_matching_profile_or_404(session: Session, user_id: int, profile_id: int) -> MatchingProfile:
    profile = session.get(MatchingProfile, profile_id)
    if not profile or profile.user_id != user_id:
        raise HTTPException(status_code=404, detail="Matching profile not found")
    return profile


def set_default_matching_profile(session: Session, user_id: int, profile: MatchingProfile) -> None:
    profiles = session.exec(select(MatchingProfile).where(MatchingProfile.user_id == user_id)).all()
    for existing in profiles:
        existing.is_default = existing.id == profile.id
        session.add(existing)
    profile.is_archived = False
    profile.updated_at = utc_now()


def resolve_run_matching_profile(session: Session, user_id: int, profile_id: Optional[int]) -> MatchingProfile:
    profile = get_matching_profile_or_404(session, user_id, profile_id) if profile_id else get_default_matching_profile(session, user_id)
    if not profile or profile.is_archived:
        raise HTTPException(status_code=404, detail="Matching profile not found")
    return profile


def resolve_profile_resume(session: Session, user_id: int, profile: MatchingProfile, require_attached: bool = True) -> Optional[Resume]:
    resume = session.get(Resume, profile.resume_id) if profile.resume_id else None
    if resume and resume.user_id == user_id:
        return resume
    latest_resume = get_latest_resume(session, user_id)
    if latest_resume and profile.is_default:
        profile.resume_id = latest_resume.id
        profile.updated_at = utc_now()
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return latest_resume
    if require_attached:
        raise HTTPException(status_code=400, detail="Attach a resume to this matching profile before starting matching.")
    return None


def get_min_match_score(session: Session, user_id: int, matching_profile_id: Optional[int] = None):
    if matching_profile_id:
        profile = session.get(MatchingProfile, matching_profile_id)
        if profile and profile.user_id == user_id:
            return profile.min_match_score
    profile = get_default_matching_profile(session, user_id)
    if profile:
        return profile.min_match_score
    prefs = get_latest_preferences(session, user_id)
    return prefs.min_match_score if prefs else 70

def assert_application_matches_threshold(app: Application, session: Session, user_id: int, action: str):
    if app.pre_screen_status == "reject" or app.status == "Screened Out":
        raise HTTPException(
            status_code=400,
            detail=f"Screened-out jobs are review-only and cannot be used for {action}.",
        )

    min_match_score = get_min_match_score(session, user_id, app.matching_profile_id)
    if app.fit_score * 100 < min_match_score:
        raise HTTPException(
            status_code=400,
            detail=f"This job is below your {min_match_score}% minimum match score and cannot be used for {action}.",
        )

def trackable_application_filter():
    aggregator_sources = tuple(ApplicationLinkResolver.AGGREGATOR_DOMAINS.keys())
    return (
        or_(Application.pre_screen_status.is_(None), Application.pre_screen_status != "reject"),
        Application.status != "Screened Out",
        or_(
            Application.source_type.is_(None),
            Application.source_type.notin_(aggregator_sources),
            Application.resolution_status == "resolved",
        ),
    )

def get_daily_agent_run_limit(user: User):
    if user.role == "admin":
        return PRO_DAILY_AGENT_RUN_LIMIT
    if user.subscription_tier == "pro":
        return PRO_DAILY_AGENT_RUN_LIMIT
    return FREE_DAILY_AGENT_RUN_LIMIT

def can_auto_apply(user: User):
    return False


def raise_browser_automation_retired():
    raise HTTPException(
        status_code=410,
        detail=(
            "Apply with assistant and Application Prep have been removed. "
            "Use the generated package and open the employer application link manually."
        ),
    )


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
            AgentRun.status.in_(["running", CANCEL_REQUESTED_STATUS]),
            AgentRun.claimed_at.is_not(None),
            AgentRun.claimed_at < stale_before,
        )
    ).all()
    for run in stale_runs:
        if run.status == CANCEL_REQUESTED_STATUS:
            mark_run_canceled(session, run)
            event_name = "agent_run.stale_canceled"
        else:
            run.status = "failed"
            run.error = "Agent run timed out while claimed by a worker."
            run.logs = (run.logs or []) + [run.error]
            run.completed_at = utc_now()
            session.add(run)
            event_name = "agent_run.stale_failed"
        log_event(
            event_name,
            level="warning",
            agent_run_id=run.id,
            user_id=run.user_id,
            claimed_at=run.claimed_at,
            stale_minutes=get_agent_run_stale_minutes(),
        )
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
        run.logs = (run.logs or []) + ["Matching workflow claimed by worker"]
        session.add(run)
        session.commit()
        session.refresh(run)
        log_event(
            "agent_run.claimed",
            agent_run_id=run.id,
            user_id=run.user_id,
            auto_apply=run.auto_apply,
        )
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
        select(AgentRun).where(AgentRun.status.in_(["running", CANCEL_REQUESTED_STATUS]))
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
        "service": "jobmatchkit-api",
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
        "service": "jobmatchkit-api",
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
        "service": "jobmatchkit-api",
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

def serialize_agent_run(run: AgentRun, audit_records: Optional[list[AutoApplyAudit]] = None, session: Optional[Session] = None):
    matching_profile = session.get(MatchingProfile, run.matching_profile_id) if session and run.matching_profile_id else None
    return {
        "id": run.id,
        "status": run.status,
        "auto_apply": run.auto_apply,
        "matching_profile_id": run.matching_profile_id,
        "matching_profile_name": matching_profile.name if matching_profile else None,
        "resume_id": run.resume_id,
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

def serialize_application_response(app: Application, session: Optional[Session] = None):
    matching_profile = session.get(MatchingProfile, app.matching_profile_id) if session and app.matching_profile_id else None
    return {
        "id": app.id,
        "job_title": app.job_title,
        "company": app.company,
        "job_url": app.job_url,
        "source_url": app.source_url,
        "resolved_url": app.resolved_url,
        "source_type": app.source_type,
        "ats_type": app.ats_type,
        "resolution_status": app.resolution_status or "unresolved",
        "resolution_notes": app.resolution_notes,
        "status": app.status,
        "matching_profile_id": app.matching_profile_id,
        "matching_profile_name": matching_profile.name if matching_profile else None,
        "matching_profile_min_match_score": matching_profile.min_match_score if matching_profile else None,
        "agent_run_id": app.agent_run_id,
        "fit_score": app.fit_score,
        "explanation": app.explanation,
        "cover_letter": app.cover_letter,
        "pre_screen_status": app.pre_screen_status or "not_screened",
        "pre_screen_reasons": app.pre_screen_reasons or [],
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

def normalize_policy_list(values: Optional[list[str]]) -> list[str]:
    if not values:
        return []
    normalized = []
    seen = set()
    for value in values:
        for raw_item in re.split(r"[,;\n\r\t]+|\s{2,}", str(value or "")):
            item = re.sub(r"\s+", " ", raw_item).strip()
            key = item.casefold()
            if not item or key in seen:
                continue
            normalized.append(item)
            seen.add(key)
            if len(normalized) >= 50:
                return normalized
    return normalized[:50]

def truthy_env(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}

def split_env_list(name: str) -> list[str]:
    return [
        item.strip().lower()
        for item in os.getenv(name, "").split(",")
        if item.strip()
    ]

def get_true_submit_pilot_status(user: Optional[User], app: Optional[Application] = None):
    global_enabled = truthy_env("ENABLE_TRUE_AUTO_SUBMIT")
    pilot_emails = split_env_list("TRUE_SUBMIT_PILOT_USER_EMAILS")
    pilot_ats_types = split_env_list("TRUE_SUBMIT_PILOT_ATS_TYPES")
    blockers: list[str] = []

    if not global_enabled:
        blockers.append("True-submit pilot flag is off for this environment.")

    user_allowed = False
    if user:
        user_email = (user.email or "").lower()
        user_allowed = user.role == "admin" or user_email in pilot_emails
    if global_enabled and not user_allowed:
        blockers.append("This account is not approved for the true-submit pilot.")

    ats_allowed = True
    if app and pilot_ats_types:
        ats_allowed = (app.ats_type or "").lower() in pilot_ats_types
        if not ats_allowed:
            blockers.append("This ATS is not approved for the true-submit pilot.")

    return {
        "global_enabled": global_enabled,
        "user_allowed": user_allowed,
        "ats_allowed": ats_allowed,
        "approved": global_enabled and user_allowed and ats_allowed,
        "blockers": blockers,
        "allowed_ats_types": pilot_ats_types,
    }

def serialize_submit_settings(settings: ApplicationSubmitSettings, user: Optional[User] = None):
    pilot_status = get_true_submit_pilot_status(user)
    effective_true_submit_enabled = bool(settings.true_submit_enabled and pilot_status["approved"])
    return {
        "id": settings.id,
        "true_submit_enabled": effective_true_submit_enabled,
        "true_submit_pilot_enabled": pilot_status["global_enabled"],
        "true_submit_pilot_approved": pilot_status["approved"],
        "true_submit_pilot_blockers": pilot_status["blockers"],
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

def clear_application_records(session: Session, user_id: int) -> int:
    applications = session.exec(select(Application).where(Application.user_id == user_id)).all()
    app_ids = [app.id for app in applications if app.id is not None]
    if not app_ids:
        return 0

    attempts = session.exec(
        select(AutoApplyAttempt).where(
            AutoApplyAttempt.application_id.in_(app_ids),
        )
    ).all()
    attempt_ids = [attempt.id for attempt in attempts if attempt.id is not None]

    if attempt_ids:
        attempt_audits = session.exec(
            select(AutoApplyAudit).where(
                AutoApplyAudit.auto_apply_attempt_id.in_(attempt_ids),
            )
        ).all()
        for audit in attempt_audits:
            session.delete(audit)

    answer_audits = session.exec(
        select(ApplicationAnswerAudit).where(
            ApplicationAnswerAudit.application_id.in_(app_ids),
        )
    ).all()
    for audit in answer_audits:
        audit.application_id = None
        session.add(audit)

    for attempt in attempts:
        FillReviewArtifactStore.delete(attempt.screenshot_path)
        FillReviewArtifactStore.delete(attempt.trace_path)
        session.delete(attempt)
    session.flush()

    reviews = session.exec(
        select(ApplicationFillReview).where(
            ApplicationFillReview.application_id.in_(app_ids),
        )
    ).all()
    for review in reviews:
        FillReviewArtifactStore.delete(review.screenshot_path)
        FillReviewArtifactStore.delete(review.trace_path)
        session.delete(review)
    session.flush()

    for app in applications:
        session.delete(app)

    session.commit()
    return len(applications)

def update_submit_settings_from_payload(
    session: Session,
    settings: ApplicationSubmitSettings,
    payload: ApplicationSubmitSettingsRequest,
    user: User,
):
    pilot_status = get_true_submit_pilot_status(user)
    settings.true_submit_enabled = payload.true_submit_enabled and payload.consent_to_submit and pilot_status["approved"]
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
    if payload.true_submit_enabled and payload.consent_to_submit and not settings.true_submit_enabled:
        log_event(
            "true_submit_pilot.setting_blocked",
            level="warning",
            user_id=user.id,
            blockers=pilot_status["blockers"],
        )
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

    pilot_status = get_true_submit_pilot_status(user, app)
    if not pilot_status["approved"]:
        blockers.extend(pilot_status["blockers"])
    elif not settings.true_submit_enabled:
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
        blockers.append("Run application prep before final-submit readiness can be evaluated.")
    else:
        if latest_review.blockers:
            blockers.append("Latest application prep attempt still has blockers.")
        if latest_review.fields_missing:
            blockers.append("Latest application prep attempt still has missing fields.")
        if not latest_review.blockers and not latest_review.fields_missing:
            checks.append("Latest application prep attempt has no saved blockers or missing fields.")

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


def friendly_agent_error(message: str):
    if "You didn't provide an API key" in message or "missing OPENAI_API_KEY" in message:
        return "LLM provider openai is missing OPENAI_API_KEY. Add it to your local .env and restart Docker Compose before starting matching."
    if "Incorrect API key" in message or "invalid_api_key" in message or "Error code: 401" in message:
        return "The LLM provider rejected the configured API key. Check your local .env value and restart Docker Compose."
    return message


def agent_result_error(logs: list[str]):
    for log in logs:
        if log.startswith(("Error parsing resume:", "Error analyzing jobs:")):
            return friendly_agent_error(log)
    return None


async def execute_agent_run(agent_run_id: int, user_id: int, auto_apply: bool):
    with Session(engine) as session:
        agent_run = session.get(AgentRun, agent_run_id)
        user = session.get(User, user_id)
        if not agent_run or not user:
            return

        if agent_run.status in {CANCEL_REQUESTED_STATUS, CANCELED_STATUS}:
            mark_run_canceled(session, agent_run)
            session.commit()
            log_event(
                "agent_run.canceled_before_start",
                agent_run_id=agent_run.id,
                user_id=user_id,
                auto_apply=auto_apply,
            )
            return

        try:
            agent_run.status = "running"
            agent_run.claimed_at = agent_run.claimed_at or utc_now()
            agent_run.logs = ["Matching workflow started"]
            session.add(agent_run)
            session.commit()
            log_event(
                "agent_run.started",
                agent_run_id=agent_run.id,
                user_id=user_id,
                auto_apply=auto_apply,
                runner_mode=get_agent_runner_mode(),
            )

            matching_profile = resolve_run_matching_profile(session, user_id, agent_run.matching_profile_id)
            resume = resolve_profile_resume(session, user_id, matching_profile)
            profile = session.exec(select(Profile).where(Profile.user_id == user_id)).first()
            allowed_companies = normalize_policy_list(matching_profile.target_companies or [])

            if not resume:
                raise ValueError("Please attach a resume to this matching profile first")

            matching_profile.last_used_at = utc_now()
            matching_profile.updated_at = utc_now()
            agent_run.matching_profile_id = matching_profile.id
            agent_run.resume_id = resume.id
            session.add(matching_profile)
            session.add(agent_run)
            session.commit()

            initial_state = {
                "resume": resume.content,
                "resume_bytes": resume.file_content,
                "resume_filename": resume.filename,
                "resume_summary": None,
                "extracted_skills": [],
                "preferences": matching_profile,
                "profile": profile,
                "found_jobs": [],
                "current_job": None,
                "application_status": "searching",
                "applications_submitted": [],
                "logs": [f"Matching workflow started for {matching_profile.name}"],
                "user_id": user_id,
                "agent_run_id": agent_run_id,
                "matching_profile_id": matching_profile.id,
                "auto_apply": auto_apply,
                "auto_apply_audit": [],
                "allowed_companies": allowed_companies,
            }

            result = await agent_graph.ainvoke(initial_state)

            if result.get("extracted_skills") or result.get("resume_summary"):
                resume.skills = result.get("extracted_skills", [])
                resume.summary = result.get("resume_summary")
                session.add(resume)

            result_logs = result.get("logs", [])
            result_error = agent_result_error(result_logs)
            session.refresh(agent_run)
            if agent_run.status == CANCEL_REQUESTED_STATUS or result.get("application_status") == CANCELED_STATUS:
                agent_run.logs = result_logs
                mark_run_canceled(session, agent_run)
            else:
                agent_run.status = "failed" if result_error else result.get("application_status", "completed")
                agent_run.error = result_error
                agent_run.logs = result_logs
                agent_run.completed_at = utc_now()
            agent_run.applications_count = len(result.get("applications_submitted", []))
            agent_run.found_jobs_count = result.get("total_found_jobs", len(result.get("found_jobs", [])))
            persist_auto_apply_audit(session, user_id, agent_run.id, result.get("auto_apply_audit", []))
            session.add(agent_run)
            session.commit()
            duration_seconds = (
                (agent_run.completed_at - agent_run.claimed_at).total_seconds()
                if agent_run.completed_at and agent_run.claimed_at
                else None
            )
            log_event(
                "agent_run.completed",
                agent_run_id=agent_run.id,
                user_id=user_id,
                auto_apply=auto_apply,
                status=agent_run.status,
                applications_count=agent_run.applications_count,
                found_jobs_count=agent_run.found_jobs_count,
                duration_seconds=duration_seconds,
                audit_records_count=len(result.get("auto_apply_audit", [])),
            )
        except Exception as e:
            session.refresh(agent_run)
            if agent_run.status == CANCEL_REQUESTED_STATUS:
                mark_run_canceled(session, agent_run)
                event_name = "agent_run.canceled"
                event_level = "info"
            else:
                agent_run.status = "failed"
                agent_run.error = str(e)
                agent_run.logs = (agent_run.logs or []) + [f"Agent failed: {e}"]
                agent_run.completed_at = utc_now()
                event_name = "agent_run.failed"
                event_level = "error"
            session.add(agent_run)
            session.commit()
            log_event(
                event_name,
                level=event_level,
                agent_run_id=agent_run.id,
                user_id=user_id,
                auto_apply=auto_apply,
                error=str(e),
            )

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
        log_event("oauth.google_callback_failed", level="error", error=str(e))
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
        log_event("oauth.linkedin_callback_failed", level="error", error=str(e))
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
    matching_profile_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    profile = resolve_run_matching_profile(session, user.id, matching_profile_id)
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
    profile.resume_id = resume.id
    profile.updated_at = utc_now()
    session.add(profile)
    session.commit()
    return {"id": resume.id, "filename": resume.filename, "message": "Resume uploaded successfully"}


@router.get("/resumes", response_model=List[ResumeLibraryResponse])
def list_resumes(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    resumes = session.exec(
        select(Resume)
        .where(Resume.user_id == user.id)
        .order_by(Resume.upload_date.desc())
    ).all()
    return [serialize_resume_status(resume) for resume in resumes]


@router.get("/matching-profiles", response_model=List[MatchingProfileResponse])
def list_matching_profiles(
    include_archived: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    get_default_matching_profile(session, user.id)
    query = select(MatchingProfile).where(MatchingProfile.user_id == user.id)
    if not include_archived:
        query = query.where(MatchingProfile.is_archived == False)
    query = query.order_by(MatchingProfile.is_default.desc(), MatchingProfile.updated_at.desc())
    return [serialize_matching_profile(profile, session) for profile in session.exec(query).all()]


@router.post("/matching-profiles", response_model=MatchingProfileResponse)
def create_matching_profile(
    payload: MatchingProfileCreateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    existing_profiles = session.exec(select(MatchingProfile).where(MatchingProfile.user_id == user.id)).all()
    duplicate = None
    if payload.duplicate_from_id:
        duplicate = get_matching_profile_or_404(session, user.id, payload.duplicate_from_id)

    profile = MatchingProfile(
        user_id=user.id,
        is_default=payload.is_default or not existing_profiles,
        is_archived=False,
    )
    if duplicate:
        profile.name = payload.name if "name" in payload.model_fields_set else f"{duplicate.name} copy"
        profile.resume_id = duplicate.resume_id
        profile.role = list(duplicate.role or [])
        profile.experience_level = list(duplicate.experience_level or ["Intermediate"])
        profile.location = list(duplicate.location or [])
        profile.job_type = list(duplicate.job_type or ["Full-time"])
        profile.target_companies = list(duplicate.target_companies or [])
        profile.min_match_score = duplicate.min_match_score
        profile.posted_within_days = duplicate.posted_within_days
        override_fields = {
            "resume_id", "role", "experience_level", "location", "job_type",
            "target_companies", "min_match_score", "posted_within_days",
        }
        if payload.model_fields_set & override_fields:
            apply_matching_profile_payload(profile, payload, user.id, session)
        else:
            profile.name = (profile.name or "Untitled profile").strip()[:120] or "Untitled profile"
            profile.updated_at = utc_now()
    else:
        apply_matching_profile_payload(profile, payload, user.id, session)
    if profile.is_default:
        set_default_matching_profile(session, user.id, profile)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return serialize_matching_profile(profile, session)


@router.patch("/matching-profiles/{profile_id}", response_model=MatchingProfileResponse)
def update_matching_profile(
    profile_id: int,
    payload: MatchingProfileRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    profile = get_matching_profile_or_404(session, user.id, profile_id)
    apply_matching_profile_payload(profile, payload, user.id, session)
    if payload.is_default:
        set_default_matching_profile(session, user.id, profile)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return serialize_matching_profile(profile, session)


@router.delete("/matching-profiles/{profile_id}", response_model=MatchingProfileResponse)
def archive_matching_profile(
    profile_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    profile = get_matching_profile_or_404(session, user.id, profile_id)
    active_count = session.exec(
        select(MatchingProfile).where(
            MatchingProfile.user_id == user.id,
            MatchingProfile.is_archived == False,
        )
    ).all()
    if len(active_count) <= 1:
        raise HTTPException(status_code=400, detail="At least one matching profile must remain active.")
    was_default = bool(profile.is_default)
    profile.is_archived = True
    profile.is_default = False
    profile.updated_at = utc_now()
    session.add(profile)
    session.commit()
    if was_default:
        replacement = get_default_matching_profile(session, user.id)
        if replacement and replacement.id != profile.id:
            set_default_matching_profile(session, user.id, replacement)
            session.commit()
    session.refresh(profile)
    return serialize_matching_profile(profile, session)


@router.post("/matching-profiles/{profile_id}/resume", response_model=MatchingProfileResponse)
async def upload_matching_profile_resume(
    profile_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    await upload_resume(file=file, matching_profile_id=profile_id, user=user, session=session)
    profile = get_matching_profile_or_404(session, user.id, profile_id)
    return serialize_matching_profile(profile, session)

@router.get("/search-jobs")
def search_jobs(query: str, location: str):
    return JobSearchService.search_jobs(query, location, use_ranked_companies=False)

@router.post("/preferences", response_model=JobPreferenceResponse)
def create_preferences(
    prefs: JobPreferenceRequest,
    matching_profile_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    preference_data = prefs.model_dump()
    scoped_preferences = JobPreference(**preference_data, user_id=user.id)
    session.add(scoped_preferences)

    profile = resolve_run_matching_profile(session, user.id, matching_profile_id)
    profile.role = normalize_policy_list(prefs.role)
    profile.experience_level = normalize_policy_list(prefs.experience_level) or ["Intermediate"]
    profile.location = normalize_policy_list(prefs.location)
    profile.job_type = normalize_policy_list(prefs.job_type) or ["Full-time"]
    profile.target_companies = normalize_policy_list(prefs.target_companies)
    profile.min_match_score = max(0, min(int(prefs.min_match_score or 70), 100))
    profile.posted_within_days = max(1, min(int(prefs.posted_within_days or 7), 90))
    profile.updated_at = utc_now()
    session.add(profile)

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
        .where(Application.user_id == user_id, *trackable_application_filter())
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
        "submission_settings": serialize_submit_settings(submission_settings, user) if submission_settings else None,
        "applications": [serialize_application_response(application, session) for application in applications],
        "generated_packages": generated_packages,
        "agent_runs": [
            serialize_agent_run(run, audit_by_run.get(run.id or 0, []), session)
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
    return serialize_submit_settings(settings, user)

@router.post("/submission-settings", response_model=ApplicationSubmitSettingsResponse)
def update_submission_settings(
    payload: ApplicationSubmitSettingsRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    settings = get_or_create_submit_settings(session, user.id)
    updated = update_submit_settings_from_payload(session, settings, payload, user)
    return serialize_submit_settings(updated, user)

@router.delete("/submission-settings", response_model=ApplicationSubmitSettingsResponse)
def reset_submission_settings(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    existing = session.exec(
        select(ApplicationSubmitSettings).where(ApplicationSubmitSettings.user_id == user.id)
    ).first()
    if existing:
        session.delete(existing)
        session.commit()
    settings = get_or_create_submit_settings(session, user.id)
    return serialize_submit_settings(settings, user)

@router.post("/agent/run", response_model=AgentRunResponse)
async def run_agent(
    background_tasks: BackgroundTasks,
    auto_apply: bool = False,
    matching_profile_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    matching_profile = resolve_run_matching_profile(session, user.id, matching_profile_id)
    resume = resolve_profile_resume(session, user.id, matching_profile)

    if not resume:
        raise HTTPException(status_code=400, detail="Please attach a resume to this matching profile first")

    if auto_apply:
        raise_browser_automation_retired()

    try:
        validate_llm_config()
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    quota_limit, quota_remaining_before_run = ensure_agent_quota(session, user)
    agent_run = AgentRun(
        user_id=user.id,
        matching_profile_id=matching_profile.id,
        resume_id=resume.id,
        status="queued",
        auto_apply=auto_apply,
        logs=[
            f"Matching workflow queued for {matching_profile.name}"
            if get_agent_runner_mode() == "worker"
            else f"Matching workflow queued for {matching_profile.name}"
        ],
    )
    session.add(agent_run)
    session.commit()
    session.refresh(agent_run)
    log_event(
        "agent_run.queued",
        agent_run_id=agent_run.id,
        user_id=user.id,
        auto_apply=auto_apply,
        matching_profile_id=matching_profile.id,
        resume_id=resume.id,
        runner_mode=get_agent_runner_mode(),
        quota_limit=quota_limit,
        quota_remaining=max(quota_remaining_before_run - 1, 0),
    )

    if should_schedule_background_agent_run():
        background_tasks.add_task(execute_agent_run, agent_run.id, user.id, auto_apply)

    return {
        "status": "queued",
        "logs": agent_run.logs,
        "applications_count": 0,
        "found_jobs_count": 0,
        "agent_run_id": agent_run.id,
        "matching_profile_id": matching_profile.id,
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
    return [serialize_agent_run(run, session=session) for run in runs]

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
    return serialize_agent_run(run, audit_records, session)

@router.post("/agent/runs/{run_id}/cancel", response_model=AgentRunRecordResponse)
def cancel_agent_run(
    run_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    run = session.get(AgentRun, run_id)
    if not run or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="Agent run not found")

    if run.status == CANCELED_STATUS:
        return serialize_agent_run(run, session=session)

    if run.status not in CANCELABLE_AGENT_RUN_STATUSES:
        raise HTTPException(status_code=400, detail="This matching run has already finished.")

    if run.status == "queued":
        mark_run_canceled(session, run)
        event_name = "agent_run.queued_canceled"
    else:
        message = "Stop requested. Matching will stop after the current step finishes."
        run.status = CANCEL_REQUESTED_STATUS
        if not run.logs or run.logs[-1] != message:
            run.logs = (run.logs or []) + [message]
        session.add(run)
        event_name = "agent_run.cancel_requested"

    session.commit()
    session.refresh(run)
    log_event(
        event_name,
        agent_run_id=run.id,
        user_id=user.id,
        auto_apply=run.auto_apply,
        status=run.status,
    )
    return serialize_agent_run(run, session=session)

def application_threshold_for_profile(session: Session, user_id: int, app: Application, cache: dict[Optional[int], int]) -> float:
    cache_key = app.matching_profile_id
    if cache_key not in cache:
        cache[cache_key] = get_min_match_score(session, user_id, app.matching_profile_id)
    return cache[cache_key] / 100


@router.get("/applications/summary")
def get_application_summary(
    matching_profile_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    selected_profile = resolve_run_matching_profile(session, user.id, matching_profile_id) if matching_profile_id else get_default_matching_profile(session, user.id)
    min_match_score = selected_profile.min_match_score if selected_profile else 70
    threshold = min_match_score / 100

    query = select(Application).where(Application.user_id == user.id, *trackable_application_filter())
    if matching_profile_id:
        query = query.where(Application.matching_profile_id == selected_profile.id)
    applications = session.exec(query).all()
    threshold_cache: dict[Optional[int], int] = {}
    strong_count = sum(
        1
        for app in applications
        if app.pre_screen_status != "reject"
        and app.status != "Screened Out"
        and (app.fit_score or 0) >= (threshold if matching_profile_id else application_threshold_for_profile(session, user.id, app, threshold_cache))
    )
    below_threshold_count = sum(
        1
        for app in applications
        if app.pre_screen_status != "reject"
        and app.status != "Screened Out"
        and 0 < (app.fit_score or 0) < (threshold if matching_profile_id else application_threshold_for_profile(session, user.id, app, threshold_cache))
    )
    latest_run_query = select(AgentRun).where(AgentRun.user_id == user.id)
    if matching_profile_id and selected_profile:
        latest_run_query = latest_run_query.where(AgentRun.matching_profile_id == selected_profile.id)
    latest_run = session.exec(
        latest_run_query.order_by(desc(AgentRun.started_at))
    ).first()

    return {
        "strong_count": strong_count,
        "below_threshold_count": below_threshold_count,
        "visible_count": len(applications),
        "min_match_score": min_match_score,
        "latest_run": serialize_agent_run(latest_run, session=session) if latest_run else None,
    }


@router.get("/applications", response_model=List[ApplicationResponse])
def get_applications(
    limit: Optional[int] = None,
    sort: str = "date",
    direction: str = "desc",
    status: Optional[str] = None,
    match_bucket: str = "all",
    matching_profile_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    selected_profile = resolve_run_matching_profile(session, user.id, matching_profile_id) if matching_profile_id else None
    query = select(Application).where(Application.user_id == user.id, *trackable_application_filter())
    if selected_profile:
        query = query.where(Application.matching_profile_id == selected_profile.id)

    if status:
        query = query.where(Application.status == status)

    if match_bucket not in {"all", "strong", "below_threshold"}:
        raise HTTPException(status_code=400, detail="match_bucket must be one of: all, strong, below_threshold")

    defer_profile_bucket_filter = match_bucket != "all" and selected_profile is None
    if match_bucket != "all" and selected_profile:
        threshold = selected_profile.min_match_score / 100

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

    sort_columns = {
        "date": Application.created_at,
        "score": Application.fit_score,
        "company": Application.company,
        "role": Application.job_title,
    }
    sort_column = sort_columns.get(sort, Application.created_at)
    sort_direction = asc if direction == "asc" else desc
    query = query.order_by(sort_direction(sort_column))

    if limit and limit > 0 and not defer_profile_bucket_filter:
        query = query.limit(min(limit, 100))

    applications = session.exec(query).all()
    if defer_profile_bucket_filter:
        threshold_cache: dict[Optional[int], int] = {}
        if match_bucket == "strong":
            applications = [
                app for app in applications
                if app.pre_screen_status != "reject"
                and app.status != "Screened Out"
                and (app.fit_score or 0) >= application_threshold_for_profile(session, user.id, app, threshold_cache)
            ]
        elif match_bucket == "below_threshold":
            applications = [
                app for app in applications
                if app.pre_screen_status != "reject"
                and app.status != "Screened Out"
                and 0 < (app.fit_score or 0) < application_threshold_for_profile(session, user.id, app, threshold_cache)
            ]
        if limit and limit > 0:
            applications = applications[:min(limit, 100)]

    return [serialize_application_response(application, session) for application in applications]

@router.post("/applications/{app_id}/resolve-link", response_model=ApplicationResponse)
async def resolve_application_link(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    resolution = await ApplicationLinkResolver.resolve_url(
        app.source_url or app.job_url,
        company=app.company,
        job_title=app.job_title,
    )
    app.source_url = resolution.original_url
    app.resolved_url = resolution.resolved_url
    app.source_type = resolution.source_type
    app.ats_type = resolution.ats_type
    app.resolution_status = resolution.resolution_status
    app.resolution_notes = resolution.notes

    session.add(app)
    session.commit()
    session.refresh(app)
    return serialize_application_response(app, session)

@router.delete("/applications", response_model=MessageResponse)
def clear_applications(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    cleared_count = clear_application_records(session, user.id)
    label = "application" if cleared_count == 1 else "applications"
    return {"message": f"Cleared {cleared_count} saved {label} across all matching profiles."}

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

    llm = get_llm()
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
    selected_profile = get_default_matching_profile(session, user.id)
    resume = resolve_profile_resume(session, user.id, selected_profile, require_attached=False) if selected_profile else get_latest_resume(session, user.id)
    prefs = selected_profile
    matching_profiles = session.exec(
        select(MatchingProfile)
        .where(MatchingProfile.user_id == user.id, MatchingProfile.is_archived == False)
        .order_by(MatchingProfile.is_default.desc(), MatchingProfile.updated_at.desc())
    ).all()
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
        "resume": serialize_resume_status(resume),
        "preferences": matching_profile_payload(prefs) if matching_profile_has_saved_targets(prefs) else None,
        "matching_profiles": [serialize_matching_profile(item, session) for item in matching_profiles],
        "selected_matching_profile": serialize_matching_profile(selected_profile, session) if selected_profile else None,
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

@router.post("/applications/{app_id}/assistant-session", response_model=MessageResponse)
def create_apply_assistant_session(app_id: int):
    raise_browser_automation_retired()


@router.get("/assistant/session/{token}", response_model=MessageResponse)
def get_apply_assistant_payload(token: str):
    raise_browser_automation_retired()


@router.post("/assistant/session/{token}/plan", response_model=MessageResponse)
async def plan_apply_assistant_form_step(token: str):
    raise_browser_automation_retired()


@router.post("/applications/{app_id}/fill-review", response_model=MessageResponse)
async def fill_application_for_review(app_id: int):
    raise_browser_automation_retired()

@router.post("/applications/{app_id}/submit-readiness", response_model=MessageResponse)
def check_application_submit_readiness(app_id: int):
    raise_browser_automation_retired()


@router.post("/applications/{app_id}/submit-confirmation", response_model=MessageResponse)
async def create_application_submit_confirmation(app_id: int):
    raise_browser_automation_retired()


@router.get("/applications/{app_id}/fill-reviews", response_model=MessageResponse)
def get_application_fill_reviews(app_id: int):
    raise_browser_automation_retired()


@router.get("/applications/{app_id}/automation-attempts", response_model=MessageResponse)
def get_application_automation_attempts(app_id: int):
    raise_browser_automation_retired()


@router.get("/applications/{app_id}/fill-reviews/{review_id}/screenshot", response_model=MessageResponse)
def get_application_fill_review_screenshot(app_id: int, review_id: int):
    raise_browser_automation_retired()


@router.get("/applications/{app_id}/fill-reviews/{review_id}/trace", response_model=MessageResponse)
def get_application_fill_review_trace(app_id: int, review_id: int):
    raise_browser_automation_retired()


@router.delete("/applications/{app_id}/fill-reviews", response_model=MessageResponse)
def clear_application_fill_reviews(app_id: int):
    raise_browser_automation_retired()

@router.post("/agent/prepare-application", response_model=ApplicationPackageResponse)
async def prepare_application(
    job_data: ApplicationPackageRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Generates a full application package: tailored cover letter, resume improvement
    checklist, talking points, and common Q&A answers for a specific job.
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

    llm = get_llm()
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
- "resume_improvements": A list of 8-10 detailed bullet strings describing exactly what should be improved in the candidate's resume for THIS role. Each item should name the resume area, explain why it matters for the job, and give a concrete rewrite/addition suggestion. Do not invent experience; frame gaps as honest improvements.
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


def package_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (value or "").strip()).strip("_")
    return cleaned[:64] or "application"


def pdf_safe_text(value: Optional[str]) -> str:
    return (value or "").encode("latin-1", errors="replace").decode("latin-1")


def pdf_multi_cell(pdf, height: float, text: str) -> None:
    pdf.multi_cell(0, height, text, new_x="LMARGIN", new_y="NEXT")


def add_package_pdf_header(pdf, title: str, app: Application, profile: Optional[Profile]) -> None:
    pdf.set_margins(22, 22, 22)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 17)
    pdf_multi_cell(pdf, 8, pdf_safe_text(title))
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf_multi_cell(pdf, 6, pdf_safe_text(f"{app.job_title} at {app.company}"))
    contact_parts = []
    if profile:
        contact_parts.append(f"{profile.first_name} {profile.last_name}")
        if profile.email:
            contact_parts.append(profile.email)
        if profile.phone:
            contact_parts.append(profile.phone)
        if profile.linkedin_url:
            contact_parts.append(profile.linkedin_url)
    if contact_parts:
        pdf_multi_cell(pdf, 5, pdf_safe_text("  |  ".join(contact_parts)))
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.35)
    pdf.line(22, pdf.get_y() + 3, 188, pdf.get_y() + 3)
    pdf.ln(9)


def add_pdf_section(pdf, title: str, body: Optional[str]) -> None:
    if not body:
        return
    pdf.set_font("Helvetica", "B", 12)
    pdf_multi_cell(pdf, 7, pdf_safe_text(title))
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 10.5)
    for paragraph in str(body).split("\n"):
        paragraph = paragraph.strip()
        if paragraph:
            pdf_multi_cell(pdf, 6.5, pdf_safe_text(paragraph))
            pdf.ln(2)
    pdf.ln(2)


def add_pdf_bullets(pdf, title: str, items: Optional[List[str]]) -> None:
    if not items:
        return
    pdf.set_font("Helvetica", "B", 12)
    pdf_multi_cell(pdf, 7, pdf_safe_text(title))
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 10.5)
    for item in items:
        if str(item).strip():
            pdf_multi_cell(pdf, 6.5, pdf_safe_text(f"- {item}"))
    pdf.ln(4)


def add_pdf_qa_items(pdf, title: str, items: Optional[List[dict]], answer_key: str) -> None:
    if not items:
        return
    pdf.set_font("Helvetica", "B", 12)
    pdf_multi_cell(pdf, 7, pdf_safe_text(title))
    pdf.ln(1)
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get(answer_key) or "").strip()
        if not question and not answer:
            continue
        pdf.set_font("Helvetica", "B", 10.5)
        pdf_multi_cell(pdf, 6.5, pdf_safe_text(f"{index}. {question}" if question else f"{index}."))
        if answer:
            pdf.set_font("Helvetica", "", 10.5)
            pdf_multi_cell(pdf, 6.5, pdf_safe_text(answer))
        pdf.ln(3)
    pdf.ln(2)


def build_pdf_bytes(title: str, app: Application, profile: Optional[Profile], sections: List[dict]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    add_package_pdf_header(pdf, title, app, profile)
    for section in sections:
        kind = section.get("kind")
        if kind == "text":
            add_pdf_section(pdf, section.get("title", ""), section.get("body"))
        elif kind == "bullets":
            add_pdf_bullets(pdf, section.get("title", ""), section.get("items"))
        elif kind == "qa":
            add_pdf_qa_items(pdf, section.get("title", ""), section.get("items"), section.get("answer_key", "answer"))
    return bytes(pdf.output())


def build_copy_paste_fields(app: Application, package_data: ApplicationPackageResponse) -> str:
    lines = [
        f"Application package: {app.job_title} at {app.company}",
        f"Generated: {utc_now().isoformat()}",
        "",
    ]
    if package_data.cover_letter:
        lines.extend(["Cover letter", "============", package_data.cover_letter.strip(), ""])
    if package_data.tailored_summary:
        lines.extend(["Tailored resume summary", "=======================", package_data.tailored_summary.strip(), ""])
    if package_data.resume_improvements:
        lines.extend(["Resume improvements", "==================="])
        lines.extend([f"- {item}" for item in package_data.resume_improvements if str(item).strip()])
        lines.append("")
    if package_data.qa_answers:
        lines.extend(["Application answers", "==================="])
        for index, qa in enumerate(package_data.qa_answers, start=1):
            question = str(qa.get("question") or "").strip()
            answer = str(qa.get("answer") or "").strip()
            lines.extend([f"{index}. {question}", answer, ""])
    if package_data.talking_points:
        lines.extend(["Talking points", "=============="])
        lines.extend([f"- {point}" for point in package_data.talking_points])
        lines.append("")
    company_brief = package_data.company_brief or {}
    questions_to_ask = company_brief.get("questions_to_ask") if isinstance(company_brief, dict) else None
    if questions_to_ask:
        lines.extend(["Questions to ask", "================"])
        lines.extend([f"- {question}" for question in questions_to_ask])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


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


@router.post("/applications/{app_id}/package.zip")
def download_application_package_zip(
    app_id: int,
    package_data: ApplicationPackageResponse,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    app = session.get(Application, app_id)
    if not app or app.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    assert_application_matches_threshold(app, session, user.id, "application package download")

    profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    cover_letter = package_data.cover_letter or app.cover_letter or "No cover letter was generated for this package."
    summary = package_data.tailored_summary or "No tailored resume summary was generated for this package."
    resume_improvements = [str(item).strip() for item in package_data.resume_improvements if str(item).strip()]
    if not resume_improvements:
        resume_improvements = [
            f"Add a targeted summary for {app.job_title} that mirrors the role's most important keywords while staying truthful to your experience.",
            "Rewrite the most relevant experience bullets to show scope, tools, business impact, and measurable outcomes instead of only listing responsibilities.",
            "Move the strongest role-matching skills into an easy-to-scan skills section so recruiters can find them in the first few seconds.",
            f"Add one or two bullets that connect your recent work directly to the responsibilities described by {app.company} for this role.",
            "Remove or compress older, less relevant details so the resume gives more space to the experience that supports this application.",
        ]
    company_brief = package_data.company_brief or {}

    cover_pdf = build_pdf_bytes(
        "Cover Letter",
        app,
        profile,
        [
            {"kind": "text", "title": datetime.now().strftime("%B %d, %Y"), "body": f"Re: {app.job_title} at {app.company}"},
            {"kind": "text", "title": "Letter", "body": cover_letter},
        ],
    )
    resume_improvements_pdf = build_pdf_bytes(
        "Resume Improvements",
        app,
        profile,
        [
            {"kind": "text", "title": "How to use this", "body": "Use this checklist to revise your resume before submitting the application. Keep every change truthful and grounded in your actual experience."},
            {"kind": "text", "title": "Tailored summary draft", "body": summary},
            {"kind": "bullets", "title": "Recommended resume improvements", "items": resume_improvements},
        ],
    )

    prep_sections = [
        {"kind": "qa", "title": "Application Answers", "items": package_data.qa_answers, "answer_key": "answer"},
    ]
    if isinstance(company_brief, dict):
        prep_sections.extend(
            [
                {"kind": "text", "title": "Company Overview", "body": company_brief.get("overview")},
                {"kind": "text", "title": "Mission and Values", "body": company_brief.get("mission")},
                {"kind": "bullets", "title": "Culture Signals", "items": company_brief.get("culture_signals")},
                {"kind": "bullets", "title": "Questions to Ask", "items": company_brief.get("questions_to_ask")},
            ]
        )
    prep_sections.extend(
        [
            {"kind": "qa", "title": "Interview Prep", "items": package_data.interview_questions, "answer_key": "suggested_answer"},
            {"kind": "bullets", "title": "Talking Points", "items": package_data.talking_points},
        ]
    )
    if not any(section.get("body") or section.get("items") for section in prep_sections):
        prep_sections.append({"kind": "text", "title": "Application Notes", "body": "No application notes were generated for this package."})

    prep_pdf = build_pdf_bytes("Application Notes", app, profile, prep_sections)
    copy_payload = package_data.model_copy(
        update={
            "cover_letter": cover_letter,
            "tailored_summary": summary,
            "resume_improvements": resume_improvements,
        }
    )
    copy_paste_text = build_copy_paste_fields(app, copy_payload)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as package_zip:
        package_zip.writestr("01-cover-letter.pdf", cover_pdf)
        package_zip.writestr("02-resume-improvements.pdf", resume_improvements_pdf)
        package_zip.writestr("03-application-notes.pdf", prep_pdf)
        package_zip.writestr("copy-paste-fields.txt", copy_paste_text)
    zip_buffer.seek(0)

    filename = "JobMatchKit_{}_{}.zip".format(
        package_filename_part(app.company),
        package_filename_part(app.job_title),
    )
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

    llm = get_llm()
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
