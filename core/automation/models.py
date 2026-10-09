from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from pydantic import BaseModel, Field


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip("*:✱✳ ")).casefold()


def site_key(url: str) -> str:
    return (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()


def job_identity(url: str) -> str:
    parsed = urlsplit(url)
    # Workday requisitions usually form the final suffix of the job slug.
    match = re.search(r"(?:_|/)(R[-_]?\d+[\w-]*)/?$", parsed.path, re.I)
    path = match.group(1).upper() if match else parsed.path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in {"source", "ref", "referral", "gh_src"} and not k.lower().startswith("utm_")))
    return site_key(url) + ":" + path + ("?" + query if query else "") + ("#" + parsed.fragment if parsed.fragment else "")


ADAPTER_REGISTRY = json.loads((Path(__file__).resolve().parents[2] / "extension/generated/registry.json").read_text())


def ats_name(url: str) -> str:
    url = url if "://" in url else "https://" + url
    if not urlsplit(url).path:
        url += "/"
    for adapter in ADAPTER_REGISTRY:
        pattern = adapter.get("pattern")
        if pattern and re.search(pattern[0], url, re.I if len(pattern) > 1 and "i" in pattern[1] else 0):
            return adapter["name"]
    # Retain employer scoping for saved job-detail URLs before their application route opens.
    legacy = {"Workday": ("myworkdayjobs.com", "myworkday.com"), "Greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"), "Lever": ("jobs.lever.co",), "Ashby": ("jobs.ashbyhq.com",)}
    host = site_key(url)
    return next((name for name, domains in legacy.items() if any(host == d or host.endswith("." + d) for d in domains)), "")


def employer_key(url: str) -> str:
    if ats_name(url) in {"ADP", "Paylocity", "SEEK", "SAP SuccessFactors", "UltiPro", "Dayforce"}:
        return job_identity(url)
    if ats_name(url) in {"Greenhouse", "Lever", "Ashby", "Workable", "Rippling", "Dover", "Comeet", "Gusto", "Polymer", "Jobvite", "SmartRecruiters"}:
        if ats_name(url) in {"Rippling", "Dover", "Comeet", "Gusto", "SmartRecruiters"}:
            return job_identity(url)
        tenant = urlsplit(url).path.strip("/").split("/")[0]
        # Embedded boards identify the job through query parameters, not an employer path.
        return job_identity(url) if tenant == "embed" else site_key(url) + "/" + tenant
    return site_key(url)


def canonical_url(url: str, *, supported_only=True) -> str:
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Use an HTTPS job URL without embedded credentials or a custom port.")
    host = p.hostname.lower()
    return urlunsplit((p.scheme, host, p.path, p.query, p.fragment))


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str = ""
    current: bool | None = None


class Experience(BaseModel):
    employer: str = ""
    job_title: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""
    current: bool | None = None


class Language(BaseModel):
    language: str = ""
    proficiency: str = ""
    fluent: bool | None = None


class ApplicantProfile(BaseModel):
    schema_version: int = 2
    name_prefix: str = ""
    middle_name: str = ""
    name_suffix: str = ""
    preferred_middle_name: str = ""
    preferred_last_name: str = ""
    phone_country_code: str = ""
    phone_number: str = ""
    phone_device_type: str = ""
    work_authorized_us: bool | None = None
    requires_sponsorship: bool | None = None
    hispanic_or_latino: bool | None = None
    employment_age: int | None = None
    language_proficiency: list[Language] = Field(default_factory=list)
    first_name: str = ""
    last_name: str = ""
    preferred_name: str = ""
    pronouns: str = ""
    gender: str = ""
    race_ethnicity: str = ""
    veteran_status: str = ""
    disability_status: str = ""
    skills: str = ""
    languages: str = ""
    summary: str = ""
    email: str = ""
    phone: str = ""
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    resume_path: str = ""
    cover_letter_path: str = ""
    cover_letter: str = ""
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)

    @property
    def revision(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]



class ApprovedAnswer(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    profile_name: str = "Default"
    value: str | bool = ""
    scope: Literal["application", "employer", "global"] = "application"
    scope_key: str = ""
    country: str = ""
    omit: bool = False
    approved_at: str = Field(default_factory=now)


class FieldAssessment(BaseModel):
    group: str = ""
    row: int = 0
    kind: str = "text"
    key: str
    label: str
    section: str = ""
    required: bool = False
    answer_ref: str = ""
    disposition: Literal["verified", "needs_input", "blocked", "intentionally_omitted"]
    reason: str = ""
    # Evidence records the verification method, never credentials or observed PII.
    evidence: str = ""
    attempts: int = 0


class InterventionRequest(BaseModel):
    kind: Literal["answer", "conflict", "browser", "profile", "verification", "validation"]
    message: str
    field_key: str = ""
    question: str = ""
    required: bool = False
    options: list[str] = Field(default_factory=list)


class ApplicationRun(BaseModel):
    schema_version: int = 1
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_url: str
    company: str = ""
    role: str = "Internship"
    profile_name: str = "Default"
    browser: Literal["chromium", "chrome", "firefox"] = "chromium"
    auto_advance: bool = True
    reuse_answers: bool = True
    auto_submit: bool = False
    pipeline: Literal["saved", "applied", "screen", "interviewing", "offer", "rejected", "archived"] = "saved"
    notes: str = ""
    job_description: str = ""
    created_at: str = Field(default_factory=now)
    submitted_at: str = ""
    submission_attempted: bool = False
    submission_confirmed: bool = False
    profile_revision: str = ""
    profile_snapshot: ApplicantProfile | None = None
    resume_digest: str = ""
    documents_digest: str = ""
    status: Literal["queued", "running", "needs_input", "ready_for_review", "failed", "cancelled"] = "queued"
    stage: str = "start"
    fields: dict[str, FieldAssessment] = Field(default_factory=dict)
    interventions: list[InterventionRequest] = Field(default_factory=list)
    completed_sections: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=now)
    elapsed_seconds: float = 0
    intervention_count: int = 0
    ai_requests: int = 0
    engine_version: str = ""
    authentication_attempted: bool = False
    submitted_by_user: bool = False

    @property
    def is_submitted(self) -> bool:
        return self.submitted_by_user or self.submission_confirmed
