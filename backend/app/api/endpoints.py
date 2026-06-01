from fastapi import APIRouter, BackgroundTasks, UploadFile, File, HTTPException, Depends, Header
from fastapi.responses import RedirectResponse, StreamingResponse
import base64
import hmac
import io
import os
import time
from sqlalchemy import asc, desc
from sqlmodel import Session, select
from app.models import (
    AgentRun,
    Application,
    AutoApplyAudit,
    JobPreference,
    PasswordResetToken,
    Profile,
    Resume,
    ScraperConfig,
    User,
)
from app.database import engine, get_session
from typing import List, Optional
from app.services.resume_parser import ResumeService
from app.services.job_search import JobSearchService
from app.services.email import send_reset_email
from app.schemas import (
    AgentRunResponse,
    AgentRunRecordResponse,
    ApplicationPackageRequest,
    ApplicationPackageResponse,
    ApplicationResponse,
    ApplicationStatusRequest,
    ApplicationStatusResponse,
    AuthResponse,
    EmailRequest,
    JobAnalysisRequest,
    JobAnalysisResponse,
    JobPreferenceRequest,
    JobPreferenceResponse,
    LoginRequest,
    MessageResponse,
    ProfileRequest,
    ProfileResponse,
    RegisterRequest,
    ResumeFeedbackResponse,
    ResumeUploadResponse,
    ResetPasswordRequest,
    SocialAuthRequest,
    UserStatusResponse,
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
from urllib.parse import urlencode, quote
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

AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY") or os.getenv("SECRET_KEY") or "job-finder-dev-secret-change-me"
AUTH_TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 7)))
FREE_DAILY_AGENT_RUN_LIMIT = int(os.getenv("FREE_DAILY_AGENT_RUN_LIMIT", "3"))
PRO_DAILY_AGENT_RUN_LIMIT = int(os.getenv("PRO_DAILY_AGENT_RUN_LIMIT", "50"))

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

def create_access_token(user: User):
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "exp": int(time.time()) + AUTH_TOKEN_TTL_SECONDS,
    }
    body = b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        AUTH_SECRET_KEY.encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{body}.{b64url_encode(signature)}"

def decode_access_token(token: str):
    try:
        body, signature = token.split(".", 1)
        expected_signature = hmac.new(
            AUTH_SECRET_KEY.encode("utf-8"),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual_signature = b64url_decode(signature)
        if not hmac.compare_digest(expected_signature, actual_signature):
            return None

        payload = json.loads(b64url_decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None

def auth_response(user: User):
    return {
        "user": serialize_user(user),
        "access_token": create_access_token(user),
        "token_type": "bearer",
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
    try:
        user = session.get(User, int(user_id))
    except (TypeError, ValueError):
        user = None

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

def get_daily_agent_run_limit(user: User):
    if user.role == "admin":
        return PRO_DAILY_AGENT_RUN_LIMIT
    if user.subscription_tier == "pro":
        return PRO_DAILY_AGENT_RUN_LIMIT
    return FREE_DAILY_AGENT_RUN_LIMIT

def can_auto_apply(user: User):
    return user.role == "admin" or user.subscription_tier == "pro"

def get_agent_runs_today(session: Session, user_id: int):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
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
                job_url=job_url,
                job_title=record.get("job_title"),
                company=record.get("company"),
                action=record.get("action", "submit"),
                status=record.get("status", "unknown"),
                message=record.get("message"),
            )
        )

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

async def execute_agent_run(agent_run_id: int, user_id: int, auto_apply: bool):
    with Session(engine) as session:
        agent_run = session.get(AgentRun, agent_run_id)
        user = session.get(User, user_id)
        if not agent_run or not user:
            return

        try:
            agent_run.status = "running"
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
            agent_run.found_jobs_count = len(result.get("found_jobs", []))
            agent_run.completed_at = datetime.utcnow()
            persist_auto_apply_audit(session, user_id, agent_run.id, result.get("auto_apply_audit", []))
            session.add(agent_run)
            session.commit()
        except Exception as e:
            agent_run.status = "failed"
            agent_run.error = str(e)
            agent_run.logs = (agent_run.logs or []) + [f"Agent failed: {e}"]
            agent_run.completed_at = datetime.utcnow()
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
    
    return auth_response(user)

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
    
    response = auth_response(user)
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
        
        params = urlencode({"token": create_access_token(user), "email": email})
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
        
        params = urlencode({"token": create_access_token(user), "email": email})
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
    return auth_response(user)

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
        existing_profile.updated_at = datetime.utcnow()
        session.add(existing_profile)
    else:
        session.add(Profile(**profile_data.model_dump(), user_id=user.id))
    session.commit()
    return {"message": "Profile updated successfully"}

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
            detail="Auto-submit requires a pro plan.",
        )

    quota_limit, quota_remaining_before_run = ensure_agent_quota(session, user)
    agent_run = AgentRun(
        user_id=user.id,
        status="queued",
        auto_apply=auto_apply,
        logs=["Agent workflow queued"],
    )
    session.add(agent_run)
    session.commit()
    session.refresh(agent_run)

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
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    query = select(Application).where(Application.user_id == user.id)

    if status:
        query = query.where(Application.status == status)

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
        config.updated_at = datetime.utcnow()
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
        expires_at=datetime.utcnow() + timedelta(hours=1)
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
        
    if reset_record.expires_at < datetime.utcnow():
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
    app_id = job_data.app_id
    if app_id:
        app = session.get(Application, app_id)
        if app and app.user_id == user.id:
            app.cover_letter = result.get("cover_letter", "")
            session.add(app)
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
