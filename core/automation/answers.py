from dataclasses import dataclass
from datetime import datetime
import re

from core.automation.models import ApplicantProfile, ApplicationRun, employer_key, normalized


@dataclass
class Resolution:
    value: str | bool | None = None
    ref: str = ""
    omit: bool = False
    reason: str = ""


# Exact aliases only: "country" must never resolve to a combined address.
ALIASES = {
    "are you legally authorized to work in the united states?": "work_authorized_us",
    "are you authorized to work in the united states?": "work_authorized_us",
    "will you require sponsorship?": "requires_sponsorship",
    "do you require sponsorship?": "requires_sponsorship",
    "middle name": "middle_name", "prefix": "name_prefix", "suffix": "name_suffix",
    "name prefix": "name_prefix", "name suffix": "name_suffix",
    "preferred first name": "preferred_name", "preferred middle name": "preferred_middle_name",
    "preferred last name": "preferred_last_name", "age": "employment_age",
    "are you hispanic or latino?": "hispanic_or_latino",
    "phone country code": "phone_country_code", "phone device type": "phone_device_type",
    "first name": "first_name", "given name": "first_name", "last name": "last_name",
    "family name": "last_name", "email": "email", "email address": "email",
    "phone": "phone", "phone number": "phone", "address line 1": "address_line1",
    "address line 2": "address_line2", "city": "city", "state": "region", "province": "region",
    "state/province": "region", "postal code": "postal_code", "zip code": "postal_code",
    "country": "country", "linkedin": "linkedin_url", "linkedin url": "linkedin_url",
    "github": "github_url", "website": "portfolio_url", "resume": "resume_path",
    "resume/cv": "resume_path",
    "given name(s) - western script": "first_name", "family name - western script": "last_name",
    "street name": "address_line1",
    "preferred name": "preferred_name", "pronouns": "pronouns", "skills": "skills",
    "languages": "languages", "cover letter": "cover_letter_path",
    "linkedin profile": "linkedin_url", "github url": "github_url",
    "portfolio": "portfolio_url", "personal website": "portfolio_url",
    "mobile phone": "phone", "phone number (with country code)": "phone",
    "resume / cv": "resume_path",
    "gender": "gender", "race/ethnicity": "race_ethnicity",
    "veteran status": "veteran_status", "disability status": "disability_status",
}
ROW_ALIASES = {
    "language_proficiency": {"language": "language", "proficiency": "proficiency", "fluent": "fluent", "native language": "fluent", "i am fluent in this language": "fluent"},
    "education": {"school": "school", "school or university": "school", "degree": "degree",
                  "field of study": "major", "major": "major", "gpa": "gpa", "currently attending": "current", "from": "start_date", "to": "end_date",
                  "start date": "start_date", "end date": "end_date"},
    "experience": {"company": "employer", "employer": "employer", "job title": "job_title",
                   "location": "location", "from": "start_date", "to": "end_date",
                   "start date": "start_date", "end date": "end_date", "role description": "description",
                   "description": "description", "i currently work here": "current"},
}


def field_value(field, value):
    if isinstance(value, bool) and field.kind in {"radio", "select-one", "select-multiple", "combobox"}:
        return "Yes" if value else "No"
    return value


def resolve(field, profile: ApplicantProfile, run: ApplicationRun, answers) -> Resolution:
    matches = []
    for answer in answers:
        if answer.profile_name != run.profile_name:
            continue
        if not run.reuse_answers and answer.scope != "application":
            continue
        if normalized(answer.question) != normalized(field.label):
            continue
        if answer.country and normalized(answer.country) != normalized(profile.country):
            continue
        key = run.id if answer.scope == "application" else employer_key(run.job_url) if answer.scope == "employer" else ""
        if answer.scope_key == key:
            matches.append(answer)
    if matches:
        priority = {"application": 0, "employer": 1, "global": 2}
        best = min(priority[a.scope] for a in matches)
        matches = [a for a in matches if priority[a.scope] == best]
        if len({(str(a.value), a.omit) for a in matches}) != 1:
            return Resolution(reason="Conflicting approved answers; edit the answer bank.")
        a = matches[-1]
        if a.omit and field.required:
            return Resolution(reason="A required field cannot be omitted.")
        return Resolution(field_value(field, a.value), "answer:" + a.id, a.omit)
    attr = None
    source = profile
    if field.group:
        entries = getattr(profile, field.group, [])
        if field.row >= len(entries):
            return Resolution(reason="The browser contains an extra row; reconcile it with your profile.")
        source = entries[field.row]
        label = normalized(field.label)
        component = re.fullmatch(r"(from|to|start date|end date) (month|day|year)", label)
        if component:
            date_key = "start_date" if component[1] in {"from", "start date"} else "end_date"
            raw = getattr(source, date_key)
            for fmt in ("%Y-%m-%d", "%Y-%m", "%b %Y", "%B %Y"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                except ValueError:
                    continue
                if component[2] == "day" and fmt != "%Y-%m-%d":
                    return Resolution(reason="The profile does not specify a day; enter it explicitly.")
                value = str(getattr(parsed, component[2]))
                return Resolution(value, f"profile:{field.group}.{field.row}.{date_key}.{component[2]}")
            return Resolution(reason="Enter this date in the profile as YYYY-MM or YYYY-MM-DD.")
        attr = ROW_ALIASES.get(field.group, {}).get(label)
    else:
        if normalized(field.label) == "country phone code" or field.split_phone:
            # ponytail: require an explicit separator; use a phone library if unseparated numbers must be parsed.
            if profile.phone_country_code and profile.phone_number:
                if field.split_phone:
                    return Resolution(profile.phone_number, "profile:phone_number")
                return Resolution(profile.phone_country_code, "profile:phone_country_code")
            phone = re.fullmatch(r"(\+\d{1,3})[\s-]+([\d\s()-]+)", profile.phone.strip())
            if not phone:
                return Resolution(reason="Separate the international calling code from the phone number with a space in the profile.")
            if field.split_phone:
                return Resolution(re.sub(r"\D", "", phone[2]), "profile:phone")
            options = [o for o in field.options if o.endswith(f"({phone[1]})")]
            if len(options) == 1:
                return Resolution(options[0], "profile:phone")
            if profile.country:
                return Resolution(f"{profile.country} ({phone[1]})", "profile:phone")
            return Resolution(reason="Select the country calling code explicitly.")
        if normalized(field.label) in {"full name", "name"} and profile.first_name and profile.last_name:
            return Resolution(" ".join(part for part in (profile.first_name, profile.middle_name, profile.last_name, profile.name_suffix) if part), "profile:full_name")
        attr = ALIASES.get(normalized(field.label))
        if attr == "phone" and profile.phone_number:
            return Resolution(profile.phone_number, "profile:phone_number")
        if attr == "cover_letter_path" and field.kind != "file":
            attr = "cover_letter"
        if attr == "resume_path" and field.kind != "file":
            return Resolution(reason="The resume control is not a file upload. Inspect it manually.")
    if attr:
        value = getattr(source, attr)
        if value is not None and value != "":
            prefix = f"{field.group}.{field.row}." if field.group else ""
            return Resolution(field_value(field, value), "profile:" + prefix + attr)
    return Resolution(reason="Approve an answer or update the profile; no value will be guessed.")
