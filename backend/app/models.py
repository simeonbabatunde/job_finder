from typing import Any, Dict, Optional, List
from sqlmodel import Field, SQLModel, Column, JSON
from datetime import datetime
from app.time_utils import utc_now

class Resume(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    content: str
    file_content: bytes = Field(default=b"")
    filename: str
    skills: List[str] = Field(default=[], sa_column=Column(JSON))
    summary: Optional[str] = Field(default=None)
    upload_date: datetime = Field(default_factory=utc_now)

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
    created_at: datetime = Field(default_factory=utc_now)

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True)
    hashed_password: Optional[str] = Field(default=None)
    subscription_tier: str = Field(default="free")  # "free" or "pro"
    role: str = Field(default="user") # "user" or "admin"
    created_at: datetime = Field(default_factory=utc_now)

class AuthSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    token_id: str = Field(unique=True, index=True)
    refresh_token_hash: Optional[str] = Field(default=None, index=True)
    expires_at: datetime = Field(index=True)
    refresh_expires_at: Optional[datetime] = Field(default=None, index=True)
    revoked_at: Optional[datetime] = Field(default=None, index=True)
    rotated_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)

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
    pre_screen_status: str = Field(default="not_screened", index=True)
    pre_screen_reasons: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)

class AgentRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    status: str = Field(default="running")
    auto_apply: bool = Field(default=False)
    logs: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    applications_count: int = Field(default=0)
    found_jobs_count: int = Field(default=0)
    error: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=utc_now, index=True)
    claimed_at: Optional[datetime] = Field(default=None, index=True)
    completed_at: Optional[datetime] = Field(default=None)

class WorkerHeartbeat(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    worker_id: str = Field(unique=True, index=True)
    status: str = Field(default="starting", index=True)
    last_seen_at: datetime = Field(default_factory=utc_now, index=True)
    current_agent_run_id: Optional[int] = Field(default=None, foreign_key="agentrun.id", index=True)
    details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

class AutoApplyAttempt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    application_id: int = Field(foreign_key="application.id", index=True)
    agent_run_id: Optional[int] = Field(default=None, foreign_key="agentrun.id", index=True)
    fill_review_id: Optional[int] = Field(default=None, foreign_key="applicationfillreview.id", index=True)
    job_url: str
    job_title: Optional[str] = Field(default=None)
    company: Optional[str] = Field(default=None)
    ats_type: Optional[str] = Field(default=None)
    mode: str = Field(default="fill_for_review")
    status: str = Field(default="queued", index=True)
    confidence_score: float = Field(default=0.0)
    blocked_reason: Optional[str] = Field(default=None)
    filled_fields: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    missing_fields: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    blockers: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    readiness_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    submit_control: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    steps: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    screenshot_path: Optional[str] = Field(default=None)
    trace_path: Optional[str] = Field(default=None)
    submitted_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)

class AutoApplyAudit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    agent_run_id: Optional[int] = Field(default=None, foreign_key="agentrun.id", index=True)
    auto_apply_attempt_id: Optional[int] = Field(default=None, foreign_key="autoapplyattempt.id", index=True)
    job_url: str
    job_title: Optional[str] = Field(default=None)
    company: Optional[str] = Field(default=None)
    action: str = Field(default="submit")
    status: str
    message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)

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
    screenshot_path: Optional[str] = Field(default=None)
    trace_path: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)

class ApplicationSubmitSettings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)
    true_submit_enabled: bool = Field(default=False)
    require_human_confirmation: bool = Field(default=True)
    min_fit_score: int = Field(default=80)
    max_submits_per_day: int = Field(default=5)
    allowed_companies: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    denied_companies: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    allowed_domains: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    denied_domains: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    allowed_job_title_keywords: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    consented_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=utc_now)

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
    updated_at: datetime = Field(default_factory=utc_now)

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
    updated_at: datetime = Field(default_factory=utc_now)

class ScraperConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_names: List[str] = Field(default=["linkedin", "indeed", "glassdoor"], sa_column=Column(JSON))
    results_wanted: int = Field(default=20)
    country_indeed: str = Field(default='USA')
    updated_at: datetime = Field(default_factory=utc_now)

class PasswordResetToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    token: str = Field(unique=True)
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)
