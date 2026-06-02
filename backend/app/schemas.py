from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterProfileRequest(BaseModel):
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    github_url: Optional[str] = None
    years_experience: int = 0
    expected_salary: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    profile: RegisterProfileRequest = Field(default_factory=RegisterProfileRequest)


class SocialAuthRequest(BaseModel):
    email: str
    provider: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class EmailRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class ProfileRequest(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    github_url: Optional[str] = None
    years_experience: int = 0
    expected_salary: Optional[str] = None


class JobPreferenceRequest(BaseModel):
    role: List[str] = Field(default_factory=lambda: [""])
    experience_level: List[str] = Field(default_factory=lambda: ["Intermediate"])
    location: List[str] = Field(default_factory=lambda: [""])
    job_type: List[str] = Field(default_factory=lambda: ["Full-time"])
    target_companies: List[str] = Field(default_factory=list)
    min_match_score: int = 70
    posted_within_days: int = 7


class JobAnalysisRequest(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    description: Optional[str] = None


class ApplicationPackageRequest(BaseModel):
    app_id: Optional[int] = None
    title: str = "Unknown Role"
    company: str = "the company"
    description: str = ""


class ApplicationStatusRequest(BaseModel):
    status: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    email: str
    subscription_tier: str
    role: str


class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    message: Optional[str] = None


class MessageResponse(BaseModel):
    message: str


class ResumeUploadResponse(BaseModel):
    id: Optional[int] = None
    filename: str
    message: str


class ResumeStatusResponse(BaseModel):
    filename: str
    uploaded_at: datetime
    skills: List[str] = Field(default_factory=list)
    summary: Optional[str] = None


class JobPreferenceResponse(JobPreferenceRequest):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    created_at: Optional[datetime] = None


class ProfileResponse(ProfileRequest):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    updated_at: Optional[datetime] = None


class ApplicationAnswerProfileRequest(BaseModel):
    work_authorized_us: str = "unspecified"
    requires_sponsorship_now: str = "unspecified"
    requires_sponsorship_future: str = "unspecified"
    willing_to_relocate: str = "unspecified"
    remote_preference: str = "unspecified"
    earliest_start_date: Optional[str] = None
    notice_period: Optional[str] = None
    desired_salary: Optional[str] = None
    work_authorization_notes: Optional[str] = None
    consent_to_use_answers: bool = False
    gender: str = "prefer_not_to_answer"
    race_ethnicity: str = "prefer_not_to_answer"
    veteran_status: str = "prefer_not_to_answer"
    disability_status: str = "prefer_not_to_answer"
    consent_to_use_demographics: bool = False


class ApplicationAnswerProfileResponse(ApplicationAnswerProfileRequest):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    updated_at: Optional[datetime] = None


class AgentQuotaResponse(BaseModel):
    agent_runs_used_today: int
    agent_run_limit: int
    agent_runs_remaining: int
    auto_apply_enabled: bool


class UserStatusResponse(BaseModel):
    user: UserResponse
    resume: Optional[ResumeStatusResponse] = None
    preferences: Optional[JobPreferenceRequest] = None
    profile: Optional[ProfileRequest] = None
    application_profile: Optional[ApplicationAnswerProfileResponse] = None
    quota: Optional[AgentQuotaResponse] = None


class AgentRunResponse(BaseModel):
    status: str
    logs: List[str] = Field(default_factory=list)
    applications_count: int
    found_jobs_count: int = 0
    agent_run_id: Optional[int] = None
    quota_limit: Optional[int] = None
    quota_remaining: Optional[int] = None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    job_title: str
    company: str
    job_url: str
    source_url: Optional[str] = None
    resolved_url: Optional[str] = None
    source_type: Optional[str] = None
    ats_type: Optional[str] = None
    resolution_status: str = "unresolved"
    resolution_notes: Optional[str] = None
    status: str
    fit_score: float
    explanation: Optional[str] = None
    cover_letter: Optional[str] = None
    created_at: datetime


class JobAnalysisResponse(BaseModel):
    score: Optional[float] = None
    explanation: Optional[str] = None
    cover_letter: Optional[str] = None


class ApplicationPackageResponse(BaseModel):
    cover_letter: Optional[str] = None
    tailored_summary: Optional[str] = None
    talking_points: List[str] = Field(default_factory=list)
    qa_answers: List[Dict[str, Any]] = Field(default_factory=list)
    interview_questions: List[Dict[str, Any]] = Field(default_factory=list)
    company_brief: Dict[str, Any] = Field(default_factory=dict)


class ApplicationStatusResponse(BaseModel):
    message: str
    status: str


class ApplicationFillReviewResponse(BaseModel):
    review_id: Optional[int] = None
    status: str
    ats_type: str
    application_url: str
    fields_filled: List[str] = Field(default_factory=list)
    fields_missing: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    message: str
    application_status: str = "Needs Review"
    screenshot_base64: Optional[str] = None


class ApplicationFillReviewRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    application_id: int
    ats_type: str
    application_url: str
    status: str
    message: Optional[str] = None
    fields_filled: List[str] = Field(default_factory=list)
    fields_missing: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    created_at: datetime


class AutoApplyAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    job_url: str
    job_title: Optional[str] = None
    company: Optional[str] = None
    action: str
    status: str
    message: Optional[str] = None
    created_at: datetime


class AgentRunRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    status: str
    auto_apply: bool
    logs: List[str] = Field(default_factory=list)
    applications_count: int
    found_jobs_count: int
    error: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    auto_apply_audit: List[AutoApplyAuditResponse] = Field(default_factory=list)


class ResumeFeedbackCategoryResponse(BaseModel):
    name: str
    score: int
    issues: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class ResumeFeedbackResponse(BaseModel):
    overall_score: Optional[int] = None
    overall_assessment: Optional[str] = None
    categories: List[ResumeFeedbackCategoryResponse] = Field(default_factory=list)
    quick_wins: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
