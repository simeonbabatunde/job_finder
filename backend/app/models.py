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
    location: str
    job_type: str  # e.g., "Full-time", "Contract"
    min_salary: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
