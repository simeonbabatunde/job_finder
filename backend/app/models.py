from typing import Optional, List
from sqlmodel import Field, SQLModel, Column, JSON
from datetime import datetime

class Resume(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    content: str
    file_content: bytes = Field(default=b"")
    filename: str
    skills: List[str] = Field(default=[], sa_column=Column(JSON))
    summary: Optional[str] = Field(default=None)
    upload_date: datetime = Field(default_factory=datetime.utcnow)

class JobPreference(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    role: List[str] = Field(default=[""], sa_column=Column(JSON))
    experience_level: List[str] = Field(default=["Intermediate"], sa_column=Column(JSON))
    location: List[str] = Field(default=[""], sa_column=Column(JSON))
    job_type: List[str] = Field(default=["Full-time"], sa_column=Column(JSON))
    target_companies: List[str] = Field(default=[], sa_column=Column(JSON))
    min_match_score: int = Field(default=70)
    posted_within_days: int = Field(default=7)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True)
    hashed_password: Optional[str] = Field(default=None)
    subscription_tier: str = Field(default="free")  # "free" or "pro"
    role: str = Field(default="user") # "user" or "admin"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    job_title: str
    company: str
    job_url: str
    source_url: Optional[str] = Field(default=None)
    resolved_url: Optional[str] = Field(default=None)
    source_type: Optional[str] = Field(default=None)
    ats_type: Optional[str] = Field(default=None)
    resolution_status: str = Field(default="unresolved")
    resolution_notes: Optional[str] = Field(default=None)
    status: str = Field(default="Applied") # Applied, Rejected, Interview, Submitted
    fit_score: float
    explanation: Optional[str] = Field(default=None)
    cover_letter: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AgentRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    status: str = Field(default="running")
    auto_apply: bool = Field(default=False)
    logs: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    applications_count: int = Field(default=0)
    found_jobs_count: int = Field(default=0)
    error: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: Optional[datetime] = Field(default=None)

class AutoApplyAudit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    agent_run_id: Optional[int] = Field(default=None, foreign_key="agentrun.id", index=True)
    job_url: str
    job_title: Optional[str] = Field(default=None)
    company: Optional[str] = Field(default=None)
    action: str = Field(default="submit")
    status: str
    message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ApplicationFillReview(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    application_id: int = Field(foreign_key="application.id", index=True)
    ats_type: str
    application_url: str
    status: str
    message: Optional[str] = Field(default=None)
    fields_filled: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    fields_missing: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    blockers: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

class Profile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True)
    first_name: str
    last_name: str
    email: str
    phone: str
    location: str
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    github_url: Optional[str] = None
    years_experience: int = Field(default=0)
    expected_salary: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ApplicationAnswerProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)
    work_authorized_us: str = Field(default="unspecified")
    requires_sponsorship_now: str = Field(default="unspecified")
    requires_sponsorship_future: str = Field(default="unspecified")
    willing_to_relocate: str = Field(default="unspecified")
    remote_preference: str = Field(default="unspecified")
    earliest_start_date: Optional[str] = Field(default=None)
    notice_period: Optional[str] = Field(default=None)
    desired_salary: Optional[str] = Field(default=None)
    work_authorization_notes: Optional[str] = Field(default=None)
    consent_to_use_answers: bool = Field(default=False)
    gender: str = Field(default="prefer_not_to_answer")
    race_ethnicity: str = Field(default="prefer_not_to_answer")
    veteran_status: str = Field(default="prefer_not_to_answer")
    disability_status: str = Field(default="prefer_not_to_answer")
    consent_to_use_demographics: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ScraperConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_names: List[str] = Field(default=["linkedin", "indeed", "glassdoor"], sa_column=Column(JSON))
    results_wanted: int = Field(default=20)
    country_indeed: str = Field(default='USA')
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class PasswordResetToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    token: str = Field(unique=True)
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
