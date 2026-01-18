from typing import Optional, List
from sqlmodel import Field, SQLModel, Column, JSON
from datetime import datetime

class Resume(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    filename: str
    upload_date: datetime = Field(default_factory=datetime.utcnow)

class JobPreference(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    role: List[str] = Field(default=[""], sa_column=Column(JSON))
    experience_level: List[str] = Field(default=["Intermediate"], sa_column=Column(JSON))
    location: List[str] = Field(default=[""], sa_column=Column(JSON))
    job_type: List[str] = Field(default=["Full-time"], sa_column=Column(JSON))
    min_match_score: int = Field(default=70)
    posted_within_days: int = Field(default=7)
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
