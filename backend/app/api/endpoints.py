from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Header
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from app.models import Resume, JobPreference, User, Application, Profile, ScraperConfig, PasswordResetToken
from app.database import get_session
from typing import List, Optional
from app.services.resume_parser import ResumeService
from app.services.job_search import JobSearchService
from app.services.email import send_reset_email
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

# Helper to get user from email header
def get_current_user(session: Session = Depends(get_session), x_user_email: str = Header(None)):
    if not x_user_email:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = session.exec(select(User).where(User.email == x_user_email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.post("/auth/login")
def login(payload: dict, session: Session = Depends(get_session)):
    email = payload.get("email")
    password = payload.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please register.")
    
    if not user.hashed_password:
        raise HTTPException(status_code=400, detail="User account has no password set (possibly social login).")

    if not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    return {"user": user}

@router.post("/auth/register")
def register_user(payload: dict, session: Session = Depends(get_session)):
    email = payload.get("email")
    password = payload.get("password")
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
    profile_data = payload.get("profile", {})
    new_profile = Profile(
        user_id=user.id,
        first_name=profile_data.get("first_name", ""),
        last_name=profile_data.get("last_name", ""),
        email=email,
        phone=profile_data.get("phone", ""),
        location=profile_data.get("location", ""),
        linkedin_url=profile_data.get("linkedin_url"),
        portfolio_url=profile_data.get("portfolio_url"),
        years_experience=profile_data.get("years_experience", 0)
    )
    session.add(new_profile)
    session.commit()
    
    return {"user": user, "message": "User registered successfully"}

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
                phone=""
            )
            session.add(profile)
            session.commit()
        
        return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?email={email}")
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
                phone=""
            )
            session.add(profile)
            session.commit()
        
        return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?email={email}")
    except Exception as e:
        print(f"Error in LinkedIn callback: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/oauth-callback?error=Internal server error during LinkedIn login")

@router.post("/auth/social")
def legacy_social_login(payload: dict, session: Session = Depends(get_session)):
    # Kept for compatibility but we now use redirect flow
    email = payload.get("email")
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        user = User(email=email, subscription_tier="free")
        session.add(user)
        session.commit()
        session.refresh(user)
    return {"user": user}

@router.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...), session: Session = Depends(get_session)):
    content = await file.read()
    try:
        text_content = ResumeService.parse_resume(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing resume: {str(e)}")

    resume = Resume(content=text_content, file_content=content, filename=file.filename)
    session.add(resume)
    session.commit()
    session.refresh(resume)
    return {"id": resume.id, "filename": resume.filename, "message": "Resume uploaded successfully"}

@router.get("/search-jobs")
def search_jobs(query: str, location: str):
    return JobSearchService.search_jobs(query, location)

@router.post("/preferences")
def create_preferences(prefs: JobPreference, session: Session = Depends(get_session)):
    session.add(prefs)
    session.commit()
    session.refresh(prefs)
    return prefs

@router.get("/profile")
def get_profile(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    return profile

@router.post("/profile")
def update_profile(profile_data: Profile, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    existing_profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    if existing_profile:
        for key, value in profile_data.model_dump(exclude={"id", "user_id"}).items():
            setattr(existing_profile, key, value)
        existing_profile.updated_at = datetime.utcnow()
        session.add(existing_profile)
    else:
        profile_data.user_id = user.id
        session.add(profile_data)
    session.commit()
    return {"message": "Profile updated successfully"}

@router.post("/agent/run")
async def run_agent(auto_apply: bool = False, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    # Get latest resume, preferences and profile
    resume = session.exec(select(Resume).order_by(Resume.upload_date.desc())).first()
    prefs = session.exec(select(JobPreference).order_by(JobPreference.created_at.desc())).first()
    profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()

    if not resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first")
    
    # Initialize state
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
        "user_id": user.id,
        "auto_apply": auto_apply
    }

    # Run the graph
    result = await agent_graph.ainvoke(initial_state)

    # Update resume with extracted info
    if result.get("extracted_skills") or result.get("resume_summary"):
        resume.skills = result.get("extracted_skills", [])
        resume.summary = result.get("resume_summary")
    # Resume is updated if configured
    session.add(resume)
    session.commit()

    return {
        "status": "success",
        "logs": result.get("logs", []),
        "applications_count": len(result.get("applications_submitted", []))
    }

@router.get("/applications", response_model=List[Application])
def get_applications(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return session.exec(select(Application).where(Application.user_id == user.id)).all()
@router.post("/agent/analyze-single")
async def analyze_single_job(job_data: dict, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    resume = session.exec(select(Resume).order_by(Resume.upload_date.desc())).first()
    prefs = session.exec(select(JobPreference).order_by(JobPreference.created_at.desc())).first()
    
    if not resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first")

    # Use Gemini to analyze just this job
    llm = get_llm(model_type="gemini")
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
        "job_title": job_data.get("title"),
        "company": job_data.get("company"),
        "description": job_data.get("description"),
        "resume_summary": resume.content[:5000], # Use raw content if summary not yet generated
        "prefs": json.dumps(criteria)
    })
    
    return result

@router.get("/user/status")
def get_user_status(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    resume = session.exec(select(Resume).order_by(Resume.upload_date.desc())).first()
    return {
        "user": user,
        "resume": {
            "filename": resume.filename, 
            "uploaded_at": resume.upload_date,
            "skills": resume.skills,
            "summary": resume.summary
        } if resume else None
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

@router.put("/admin/config")
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

@router.post("/auth/forgot-password")
def forgot_password(payload: dict, session: Session = Depends(get_session)):
    email = payload.get("email")
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

@router.post("/auth/reset-password")
def reset_password(payload: dict, session: Session = Depends(get_session)):
    token = payload.get("token")
    new_password = payload.get("password")
    
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

