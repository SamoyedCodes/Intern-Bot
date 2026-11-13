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


CHOICE_KINDS = {"combobox", "select-one", "select-multiple", "radio"}


def same_choice(a, b) -> bool:
    """Two wordings of one listed option: equal, or equal once punctuation is ignored ("Mr" is "Mr.")."""
    loose = lambda text: re.sub(r"[\W_]+", "", normalized(str(text)))
    return normalized(str(a)) == normalized(str(b)) or bool(loose(b)) and loose(a) == loose(b)


def site_key(url: str) -> str:
    return (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()


def job_identity(url: str) -> str:
    parsed = urlsplit(url)
    # Workday requisitions usually form the final suffix of the job slug.
    match = re.search(r"(?:_|/)(R[-_]?\d+[\w-]*)/?$", parsed.path, re.I)
    path = match.group(1).upper() if match else parsed.path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in {"source", "ref", "referral", "gh_src"} and not k.lower().startswith("utm_")))
    return site_key(url) + ":" + path + ("?" + query if query else "") + ("#" + parsed.fragment if parsed.fragment else "")


# Extracted vendor adapters, then hand-written ones (extension/adapters/).
ADAPTER_REGISTRY = [entry for name in ("generated", "adapters") for entry in json.loads((Path(__file__).resolve().parents[2] / "extension" / name / "registry.json").read_text())]


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


# Sign-in stages; the task view shows these over the site's step list, which a re-sign-in leaves in place.
ACCOUNT_STAGES = CHECKING_LOGIN, SAVING_LOGIN, CREATING_ACCOUNT, SIGNING_IN = (
    "Checking employer login", "Saving new login in 1Password", "Creating employer account", "Signing in")


class AccountContext(BaseModel):
    provider: str
    tenant: str
    login_url: str
    return_url: str = ""
    item_id: str = ""

    @property
    def key(self):
        return self.provider + ":" + self.tenant


def account_context(url: str) -> AccountContext | None:
    """Account identity excludes job IDs, locale and expiring authentication parameters."""
    url = canonical_url(url if "://" in url else "https://" + url)
    p, name = urlsplit(url), ats_name(url)
    if name == "Workday":
        if p.hostname.endswith('.myworkdaysite.com'):
            match = re.search(r'/recruiting/([^/]+)(/[^/]+)?', p.path)
            return AccountContext(provider='workday', tenant=p.hostname + '/' + match[1], login_url='https://' + p.hostname + match[0]) if match else None
        if p.hostname.endswith('.myworkday.com') or p.hostname == 'myworkday.com':
            return None
        return AccountContext(provider="workday", tenant=p.hostname, login_url="https://" + p.hostname)
    if name == "SAP SuccessFactors":
        company = parse_qsl(p.query, keep_blank_values=True)
        companies = [value for key, value in company if key == "company"]
        if len(companies) != 1 or not companies[0]:
            return None
        return AccountContext(provider="sap-successfactors", tenant=p.hostname + "/" + companies[0],
                              login_url="https://" + p.hostname + "/career?" + urlencode({"company": companies[0]}))
    # Shared hiring/identity providers cannot safely fall back to a hostname-only login.
    if name or re.search(r"(^|\.)(google|microsoftonline|live|apple|linkedin|auth0|okta)\.com$", p.hostname):
        return None
    if any(key.casefold() in {'tenant', 'company', 'organization', 'realm', 'client_id'} for key, _ in parse_qsl(p.query)):
        return None
    return AccountContext(provider="generic", tenant=p.hostname, login_url="https://" + p.hostname)


def application_scope(url: str) -> str:
    context = account_context(url)
    return context.key if context else employer_key(url)


def stable_application_url(url: str) -> str:
    p = urlsplit(canonical_url(url))
    if ats_name(url) == "SAP SuccessFactors":
        query = dict(parse_qsl(p.query))
        stable = {k: query[k] for k in ("company", "career_job_req_id") if k in query}
        if 'career_job_req_id' in stable:
            stable['career_ns'] = 'job_listing'
        return p._replace(query=urlencode(stable), fragment="").geturl()
    return url


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
    work_authorized: bool | None = True
    requires_sponsorship: bool | None = None
    citizenship: str = ""
    # Your own plain statements ("I have no relatives at any employer I apply to"); an AI provider reads them to answer declarations.
    standing_answers: str = ""
    nationality: str = ""
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

    @property
    def has_preferred_name(self) -> bool:
        # A preferred name identical to the legal first name is not a different name to declare.
        return bool(self.preferred_name) and normalized(self.preferred_name) != normalized(self.first_name)



class ApprovedAnswer(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    # Other wordings employers used for the same question; each takes this answer.
    variants: list[str] = Field(default_factory=list)
    profile_name: str = "Default"
    value: str | bool = ""
    scope: Literal["application", "employer", "global"] = "application"
    scope_key: str = ""
    country: str = ""
    omit: bool = False
    # A live link to a profile fact ("email", "education.0.end_date.year"): the answer is that fact's current value.
    fact: str = ""
    # An AI answer that rewords this answer of yours into the form's own option ("Company careers page" as "Company Website").
    rewords: str = ""
    # "ai" answers fill forms but block sending until you confirm them (approving a review that shows them does), which makes them yours.
    origin: Literal["you", "ai"] = "you"
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
    # What the form showed when it was verified, kept locally for the review you approve. Password fields are never assessed.
    value: str | bool = ""
    option: str = ""  # A radio button's own choice; value says whether it was selected.
    attempts: int = 0


class InterventionRequest(BaseModel):
    kind: Literal["answer", "conflict", "browser", "profile", "verification", "validation", "activation", "link"]
    message: str
    field_key: str = ""
    question: str = ""
    required: bool = False
    options: list[str] = Field(default_factory=list)
    field_kind: str = ""  # the form control's kind (text, combobox, file…), so the answer dialog offers the same type
    # What the answer dialog starts from: the value the form holds now, else the saved answer the form didn't take.
    value: str | bool = ""


class ApplicationRun(BaseModel):
    schema_version: int = 1
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_url: str
    # The careers-page listing you pasted, when its Apply link led to job_url on a hiring platform.
    listing_url: str = ""
    company: str = ""
    role: str = "Internship"
    profile_name: str = "Default"
    browser: Literal["chromium", "chrome", "firefox"] = "chromium"
    # Request mode prepares Workday's questions through its API before the shared browser completion flow.
    mode: Literal["classic", "request"] = "classic"
    auto_advance: bool = True
    reuse_answers: bool = True
    pipeline: Literal["saved", "applied", "screen", "interviewing", "offer", "rejected", "archived"] = "saved"
    notes: str = ""
    job_description: str = ""
    created_at: str = Field(default_factory=now)
    submitted_at: str = ""
    submission_attempted: bool = False
    # The review you approved (review_values); Send clicks only while the rechecked form still matches it exactly.
    approved_review: dict[str, str] = Field(default_factory=dict)
    submission_confirmed: bool = False
    profile_revision: str = ""
    profile_snapshot: ApplicantProfile | None = None
    resume_digest: str = ""
    documents_digest: str = ""
    status: Literal["queued", "running", "needs_input", "ready_for_review", "failed", "cancelled"] = "queued"
    # Live presentation telemetry. A saved/restarted application has no active worker.
    work_phase: Literal["intake", "fill", "verify", "dispatch"] = Field(default="intake", exclude=True)
    stage: str = "start"
    fields: dict[str, FieldAssessment] = Field(default_factory=dict)
    interventions: list[InterventionRequest] = Field(default_factory=list)
    completed_sections: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)  # the site's own step names, when it shows a step list
    step: int = -1
    updated_at: str = Field(default_factory=now)
    elapsed_seconds: float = 0
    intervention_count: int = 0
    ai_requests: int = 0
    ai_asked: list[str] = Field(default_factory=list)  # Questions already sent to the AI for this application, normalized.
    engine_version: str = ""
    authentication_attempted: bool = False
    account: AccountContext | None = None
    registration_attempted: bool = False
    login_attempted: bool = False
    verification_continued: bool = False
    submitted_by_user: bool = False

    @property
    def is_submitted(self) -> bool:
        return self.submitted_by_user or self.submission_confirmed
