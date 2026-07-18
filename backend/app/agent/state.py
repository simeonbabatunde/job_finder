from typing import List, NotRequired, Optional, TypedDict
from app.models import Resume, JobPreference, Profile

class Job(TypedDict):
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str # "api", "mock", "linkedin_scrape"
    fit_score: Optional[float]
    explanation: NotRequired[str]
    cover_letter: Optional[str]
    application_url: NotRequired[str]
    source_url: NotRequired[str]
    resolved_url: NotRequired[str]
    source_type: NotRequired[str]
    ats_type: NotRequired[str]
    resolution_status: NotRequired[str]
    resolution_notes: NotRequired[str]
    pre_screen_status: NotRequired[str]
    pre_screen_reasons: NotRequired[List[str]]

class AgentState(TypedDict):
    resume: str
    resume_bytes: Optional[bytes]
    resume_filename: Optional[str]
    resume_summary: Optional[str]
    extracted_skills: List[str]
    preferences: JobPreference
    profile: Optional[Profile]
    found_jobs: List[Job]
    total_found_jobs: NotRequired[int]
    screened_out_jobs_count: NotRequired[int]
    current_job: Optional[Job]
    application_status: str # "searching", "analyzing", "applying", "completed"
    applications_submitted: List[str] # List of job URLs
    logs: List[str]
    user_id: int
    agent_run_id: Optional[int]
    matching_profile_id: Optional[int]
    auto_apply: bool
    auto_apply_audit: List[dict]
    allowed_companies: NotRequired[List[str]]
