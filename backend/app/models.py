from typing import Optional, List
from sqlmodel import Field, SQLModel, Column, JSON
from datetime import datetime

class Resume(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    file_content: bytes = Field(default=b"")
    filename: str
    skills: List[str] = Field(default=[], sa_column=Column(JSON))
    summary: Optional[str] = Field(default=None)
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
    hashed_password: Optional[str] = Field(default=None)
    subscription_tier: str = Field(default="free")  # "free" or "pro"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    job_title: str
    company: str
    job_url: str
    status: str = Field(default="Applied") # Applied, Rejected, Interview, Submitted
    fit_score: float
    explanation: Optional[str] = Field(default=None)
    cover_letter: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
