from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime

class Resume(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    filename: str
    upload_date: datetime = Field(default_factory=datetime.utcnow)

class JobPreference(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    role: str
    experience_level: str = Field(default="Intermediate") # e.g., "Entry-level", "Intermediate", "Senior", "Lead"
    location: str
    job_type: str  # e.g., "Full-time", "Contract"
    min_salary: Optional[int] = None
    posted_within_weeks: int = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True)
    subscription_tier: str = Field(default="free")  # "free" or "pro"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    job_title: str
    company: str
    job_url: str
    status: str = Field(default="Applied") # Applied, Rejected, Interview
    fit_score: float
    created_at: datetime = Field(default_factory=datetime.utcnow)
