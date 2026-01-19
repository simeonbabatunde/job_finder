from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlmodel import Session, select
from app.models import Resume, JobPreference, User, Application
from app.database import get_session
from typing import List
from app.services.resume_parser import ResumeService
from app.services.job_search import JobSearchService
from app.agent.graph import agent_graph
from datetime import datetime

router = APIRouter()

# Helper to get or create a demo user
def get_demo_user(session: Session):
    user = session.exec(select(User).where(User.email == "demo@example.com")).first()
    if not user:
        user = User(email="demo@example.com", subscription_tier="pro")
        session.add(user)
        session.commit()
        session.refresh(user)
    return user

@router.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...), session: Session = Depends(get_session)):
    content = await file.read()
    try:
        text_content = ResumeService.parse_resume(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing resume: {str(e)}")

    resume = Resume(content=text_content, filename=file.filename)
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

@router.post("/agent/run")
async def run_agent(session: Session = Depends(get_session)):
    user = get_demo_user(session)
    # Get latest resume and preferences
    resume = session.exec(select(Resume).order_by(Resume.upload_date.desc())).first()
    prefs = session.exec(select(JobPreference).order_by(JobPreference.created_at.desc())).first()

    if not resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first")
    
    # Initialize state
    initial_state = {
        "resume": resume.content,
        "preferences": prefs,
        "found_jobs": [],
        "current_job": None,
        "application_status": "searching",
        "applications_submitted": [],
        "logs": ["Agent workflow started"],
        "user_id": user.id
    }

    # Run the graph
    result = await agent_graph.ainvoke(initial_state)

    # In a real app, the agent nodes would update the DB. 
    # For this prototype, we'll sync the 'applied' jobs here.
    for job_url in result.get("applications_submitted", []):
        # Find the job details from found_jobs
        job_details = next((j for j in result["found_jobs"] if j["url"] == job_url), None)
        if job_details:
            app = Application(
                user_id=user.id,
                job_title=job_details["title"],
                company=job_details["company"],
                job_url=job_url,
                fit_score=job_details.get("fit_score", 0.0),  # Use score from agent analysis
                status="Applied"
            )
            session.add(app)
    
    session.commit()

    return {
        "status": "success",
        "logs": result.get("logs", []),
        "applications_count": len(result.get("applications_submitted", []))
    }

@router.get("/applications", response_model=List[Application])
def get_applications(session: Session = Depends(get_session)):
    user = get_demo_user(session)
    return session.exec(select(Application).where(Application.user_id == user.id)).all()

@router.get("/user/status")
def get_user_status(session: Session = Depends(get_session)):
    user = get_demo_user(session)
    resume = session.exec(select(Resume).order_by(Resume.upload_date.desc())).first()
    return {
        "user": user,
        "resume": {"filename": resume.filename, "uploaded_at": resume.upload_date} if resume else None
    }

