from dataclasses import dataclass, replace
from datetime import datetime
import re

from core.automation.models import ApplicantProfile, ApplicationRun, Language, employer_key, normalized


@dataclass
class Resolution:
    value: str | bool | None = None
    ref: str = ""
    omit: bool = False
    reason: str = ""
    ai: bool = False  # Filled from an AI answer you haven't confirmed.


# Exact aliases only: "country" must never resolve to a combined address.
ALIASES = {
    "are you legally authorized to work in the united states?": "work_authorized_us",
    "are you authorized to work in the united states?": "work_authorized_us",
    "authorized to work in job's country": "work_authorized",
    "are you authorized to work in singapore?": "work_authorized",
    "are you legally authorized to work in singapore?": "work_authorized",
    "are you eligible to work in singapore?": "work_authorized",
    "do you have the right to work in singapore?": "work_authorized",
    "are you legally authorized to work in the country for which you are applying?": "work_authorized",
    "are you authorized to work in the country where this job is located?": "work_authorized",
    "citizenship": "citizenship", "country of citizenship": "citizenship",
    "nationality": "nationality", "what is your nationality?": "nationality",
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
    "language_proficiency": {"language": "language", "proficiency": "proficiency", "fluent": "fluent", "native language": "fluent", "i am fluent in this language": "fluent", "i am fluent in this language.": "fluent"},
    "education": {"school": "school", "school or university": "school", "degree": "degree",
                  "field of study": "major", "major": "major", "gpa": "gpa", "currently attending": "current", "from": "start_date", "to": "end_date",
                  "start date": "start_date", "end date": "end_date"},
    "experience": {"company": "employer", "employer": "employer", "job title": "job_title",
                   "location": "location", "from": "start_date", "to": "end_date",
                   "start date": "start_date", "end date": "end_date", "role description": "description",
                   "description": "description", "i currently work here": "current"},
}


# Profile facts an AI may link a question to, by name only. Demographics, legal status, age, pronouns and documents are never offered.
FACTS = {
    "first_name": "legal first (given) name", "middle_name": "middle name", "last_name": "last (family) name",
    "full_name": "full legal name", "preferred_name": "preferred first name", "name_prefix": "name prefix or title",
    "name_suffix": "name suffix", "email": "email address", "phone": "phone number",
    "phone_country_code": "international calling code", "address_line1": "street address", "address_line2": "address line 2",
    "city": "city", "region": "state or province", "postal_code": "postal or ZIP code", "country": "country of residence",
    "linkedin_url": "LinkedIn profile URL", "github_url": "GitHub profile URL", "portfolio_url": "personal website or portfolio URL",
    "skills": "skills", "languages": "languages spoken",
}
ROW_FACTS = {
    "education": ("education", {"school": "school", "degree": "degree", "major": "field of study", "gpa": "GPA",
                                "start_date": "start date", "end_date": "end or expected graduation date", "current": "currently attending"}),
    "experience": ("job", {"employer": "employer", "job_title": "job title", "location": "location",
                           "start_date": "start date", "end_date": "end date", "current": "currently working here"}),
    "language_proficiency": ("language", {"language": "language", "proficiency": "proficiency", "fluent": "fluent"}),
}
FACT = re.compile(r"(?:(education|experience|language_proficiency)\.(\d+)\.)?(\w+)(?:\.(year|month))?")


def fact_catalog(profile):
    """Names and plain descriptions of the profile facts that have a value; never the values themselves."""
    catalog = {key: text for key, text in FACTS.items()
               if (profile.first_name and profile.last_name if key == "full_name" else getattr(profile, key))}
    for group, (noun, attrs) in ROW_FACTS.items():
        for row, entry in enumerate(profile_rows(profile, group)):
            catalog.update({f"{group}.{row}.{attr}": f"{noun} #{row + 1} {text}" for attr, text in attrs.items()
                            if getattr(entry, attr) not in ("", None)})
    return catalog


def fact_name(fact):
    """'education.0.end_date.year' as 'education #1 end or expected graduation date (year)'."""
    match = FACT.fullmatch(fact)
    if match[1]:
        noun, attrs = ROW_FACTS[match[1]]
        text = f"{noun} #{int(match[2]) + 1} {attrs.get(match[3], match[3])}"
    else:
        text = FACTS.get(match[3], match[3])
    return text + (f" ({match[4]})" if match[4] else "")


def fact_allowed(fact, catalog):
    """A key from the catalog, or a date key from it with a .year or .month part."""
    base, _, part = fact.rpartition(".")
    return fact in catalog or (part in {"year", "month"} and base in catalog and base.endswith(("start_date", "end_date")))


def linked(field, profile, fact):
    """Resolve a link to a profile fact exactly as if the form had used that fact's own label."""
    match = FACT.fullmatch(fact)
    group, row, attr, part = match[1] or "", int(match[2] or 0), match[3], match[4]
    if group and row >= len(profile_rows(profile, group)):
        return Resolution(reason="The profile entry this answer links to no longer exists. Update the profile or delete the answer.")
    label = "full name" if attr == "full_name" else next(l for l, a in (ROW_ALIASES[group] if group else ALIASES).items() if a == attr)
    return profile_fact(replace(field, label=f"{label} {part}" if part else label, group=group, row=row), profile)


def field_value(field, value):
    # Only a checkbox holds a Boolean; anything else shows "Yes"/"No" (a text box would otherwise be typed "true" and never verify).
    if isinstance(value, bool) and field.kind != "checkbox":
        return "Yes" if value else "No"
    return value


UNANSWERED = "Approve an answer or update the profile; no value will be guessed."


def asks(answer, label):
    """Whether this label is the answer's question or one of its recorded wordings."""
    return normalized(label) in {normalized(q) for q in (answer.question, *answer.variants)}


def applicable(answers, profile: ApplicantProfile, run: ApplicationRun):
    """Approved answers within this run's profile, scope and country, whatever they ask."""
    usable = []
    for answer in answers:
        if answer.profile_name != run.profile_name:
            continue
        if not run.reuse_answers and answer.scope != "application":
            continue
        if answer.country and normalized(answer.country) != normalized(profile.country):
            continue
        key = run.id if answer.scope == "application" else employer_key(run.job_url) if answer.scope == "employer" else ""
        if answer.scope_key == key:
            usable.append(answer)
    return usable


ROW_NAMES = {"language_proficiency": "language", "education": "school", "experience": "employer"}


def profile_rows(profile, group):
    rows = getattr(profile, group, [])
    if group == 'language_proficiency' and not rows:
        return [Language(language=name.strip()) for name in re.split(r'[,;\n]', profile.languages) if name.strip()]
    return rows


def question_for(field, profile: ApplicantProfile):
    """A row question names its row ("Speaking — English"), so each language, school or employer keeps its own answer."""
    entries = profile_rows(profile, field.group) if field.group in ROW_NAMES else []
    name = getattr(entries[field.row], ROW_NAMES[field.group]) if field.row < len(entries) else ""
    return f"{field.label} — {name}" if name else field.label


def approved(field, matches, profile):
    """The most specific approved answer among matches, or None when nothing matched."""
    if not matches:
        return None
    priority = {"application": 0, "employer": 1, "global": 2}
    best = min(priority[a.scope] for a in matches)
    matches = [a for a in matches if priority[a.scope] == best]
    matches = [a for a in matches if a.origin == "you"] or matches  # Your own answer outranks the AI's.
    if len({(str(a.value), a.fact, a.omit) for a in matches}) != 1:
        return Resolution(reason="Conflicting approved answers; edit the answer bank.")
    a = matches[-1]
    if a.omit and field.required:
        return Resolution(reason="A required field cannot be omitted.")
    if a.fact:
        found = linked(field, profile, a.fact)
        return found if found.value is None else Resolution(found.value, "answer:" + a.id, ai=a.origin == "ai")
    return Resolution(field_value(field, a.value), "answer:" + a.id, a.omit, ai=a.origin == "ai")


def resolve(field, profile: ApplicantProfile, run: ApplicationRun, answers) -> Resolution:
    usable = applicable(answers, profile, run)
    if not field.group:
        return approved(field, [a for a in usable if asks(a, field.label)], profile) or profile_fact(field, profile)
    if field.row >= len(profile_rows(profile, field.group)):
        return Resolution(reason="The browser contains an extra row; reconcile it with your profile.")
    # An answer to a bare row label ("Speaking") was given for the first row, where the question used to be asked;
    # other rows have their own named answer ("Speaking — Chinese (Mandarin)") or their own profile facts.
    named = question_for(field, profile)
    for question in dict.fromkeys(q for q in (named, field.label if field.row == 0 else None) if q):
        found = approved(field, [a for a in usable if asks(a, question)], profile)
        if found:
            return found
    return profile_fact(field, profile)


def profile_fact(field, profile: ApplicantProfile) -> Resolution:
    attr = None
    source = profile
    if field.group:
        source = profile_rows(profile, field.group)[field.row]
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
                code, ref = profile.phone_country_code, "profile:phone_country_code"
            else:
                phone = re.fullmatch(r"(\+\d{1,3})[\s-]+([\d\s()-]+)", profile.phone.strip())
                if not phone:
                    return Resolution(reason="Separate the international calling code from the phone number with a space in the profile.")
                if field.split_phone:
                    return Resolution(re.sub(r"\D", "", phone[2]), "profile:phone")
                code, ref = phone[1], "profile:phone"
            # Calling-code pickers label each option "Country (+code)".
            options = [o for o in field.options if o.endswith(f"({code})")]
            if len(options) == 1:
                return Resolution(options[0], ref)
            if profile.country:
                return Resolution(f"{profile.country} ({code})", ref)
            return Resolution(reason="Select the country calling code explicitly.")
        if normalized(field.label) == "i have a preferred name":
            return Resolution(profile.has_preferred_name, "profile:preferred_name")
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
        if field.kind == "month" and attr in {"start_date", "end_date"} and value:
            # A month picker reads YYYY-MM, like <input type=month>.
            for fmt in ("%Y-%m-%d", "%Y-%m", "%b %Y", "%B %Y"):
                try:
                    value = datetime.strptime(value, fmt).strftime("%Y-%m")
                    break
                except ValueError:
                    continue
            else:
                return Resolution(reason="Enter this date in the profile as YYYY-MM or YYYY-MM-DD.")
        if value is not None and value != "":
            prefix = f"{field.group}.{field.row}." if field.group else ""
            return Resolution(field_value(field, value), "profile:" + prefix + attr)
    return Resolution(reason=UNANSWERED)
