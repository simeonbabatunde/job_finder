from typing import TypedDict, List, Optional
from app.models import Resume, JobPreference

class Job(TypedDict):
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str # "api", "mock", "linkedin_scrape"

class AgentState(TypedDict):
    resume: str
    preferences: JobPreference
    found_jobs: List[Job]
    current_job: Optional[Job]
    application_status: str # "searching", "analyzing", "applying", "completed"
    applications_submitted: List[str] # List of job URLs
    logs: List[str]
    user_id: int
