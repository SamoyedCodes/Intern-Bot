import datetime
from typing import List, Optional
from sqlmodel import Field, SQLModel, Relationship

class Education(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    institution_name: str
    degree_type: str
    major: str
    gpa: Optional[float] = None
    start_date: Optional[datetime.date] = None
    graduation_date: Optional[datetime.date] = None

    user: Optional["User"] = Relationship(back_populates="educations")

class Experience(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    company_name: str
    job_title: str
    location: Optional[str] = None
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    is_current: bool = False
    responsibilities: str

    user: Optional["User"] = Relationship(back_populates="experiences")

class PlatformCredential(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    platform_name: str
    subdomain: Optional[str] = None
    username: str
    encrypted_password: str

    user: Optional["User"] = Relationship(back_populates="credentials")

class JobApplication(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    platform_name: str
    job_url: str
    status: str = Field(default="pending") # pending, applied, failed, etc.
    date_applied: Optional[datetime.datetime] = None
    error_message: Optional[str] = None

    user: Optional["User"] = Relationship(back_populates="applications")

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    legal_first_name: str
    legal_last_name: str
    preferred_name: Optional[str] = None
    email: str = Field(unique=True, index=True)
    phone_number: str
    physical_address: str
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    gender: Optional[str] = None
    ethnicity: Optional[str] = None
    veteran_status: Optional[str] = None
    disability_status: Optional[str] = None
    master_resume_path: Optional[str] = None
    cover_letter_template: Optional[str] = None

    educations: List[Education] = Relationship(back_populates="user")
    experiences: List[Experience] = Relationship(back_populates="user")
    credentials: List[PlatformCredential] = Relationship(back_populates="user")
    applications: List[JobApplication] = Relationship(back_populates="user")
