from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlmodel import Session
from app.models import Resume, JobPreference
from app.database import get_session
from typing import List
from app.services.resume_parser import ResumeService
from app.services.job_search import JobSearchService

router = APIRouter()

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
