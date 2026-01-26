from typing import TypedDict, List, Optional
from app.models import Resume, JobPreference, Profile

class Job(TypedDict):
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str # "api", "mock", "linkedin_scrape"
    fit_score: Optional[float]
    cover_letter: Optional[str]

class AgentState(TypedDict):
    resume: str
    resume_bytes: Optional[bytes]
    resume_filename: Optional[str]
    resume_summary: Optional[str]
    extracted_skills: List[str]
    preferences: JobPreference
    profile: Optional[Profile]
    found_jobs: List[Job]
    current_job: Optional[Job]
    application_status: str # "searching", "analyzing", "applying", "completed"
    applications_submitted: List[str] # List of job URLs
    logs: List[str]
    user_id: int
    auto_apply: bool
