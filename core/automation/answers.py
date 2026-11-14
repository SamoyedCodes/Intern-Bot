from dataclasses import dataclass, replace
from datetime import datetime
import re
from types import SimpleNamespace

from core.automation.fields import FormField
from core.automation.models import CHOICE_KINDS, ApplicantProfile, ApplicationRun, Language, employer_key, normalized, same_choice


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
    "country": "country", "country of residence": "country", "country/region of residence": "country", "country/region": "country", "linkedin": "linkedin_url", "linkedin url": "linkedin_url",
    "github": "github_url", "website": "portfolio_url", "resume": "resume_path",
    "resume/cv": "resume_path",
    "given name(s) - western script": "first_name", "family name - western script": "last_name",
    "street name": "address_line1",
    "preferred name": "preferred_name", "pronouns": "pronouns", "skills": "skills",
    "languages": "languages", "cover letter": "cover_letter_path",
    "linkedin profile": "linkedin_url", "github url": "github_url",
    "portfolio": "portfolio_url", "personal website": "portfolio_url",
    "mobile phone": "phone", "mobile number": "phone", "phone number (with country code)": "phone", "preferred pronouns": "pronouns",
    "resume / cv": "resume_path",
    "gender": "gender", "race/ethnicity": "race_ethnicity",
    "veteran status": "veteran_status", "disability status": "disability_status",
}
# Form numbering ("3. Mobile Number", "17.Where…"), a lead-in ("Please provide your …", "What are your …"), "(optional)" and British
# spelling don't change what a question asks.
LEAD = re.compile(r"^(?:q?\d{1,2}\s*[.)](?!\d)\s*|(?:please\s+)?(?:provide|enter|specify)\s+your\s+|what\s+(?:is|are)\s+your\s+)")


def canonical(label):
    text = normalized(str(label))
    while (shorter := LEAD.sub("", text, count=1)) != text:
        text = shorter
    return re.sub(r"\s*\((?:optional|required)\)$", "", text).replace("authoris", "authoriz").rstrip("?. ")


CANONICAL_ALIASES = {canonical(question): attr for question, attr in ALIASES.items()}
# Self-identification questions an AI never answers come in many wordings. A keyword names your profile fact, used only for a dropdown
# or radio whose option is that exact answer; a bare Yes/No answer could belong to another question ("…accommodation for a disability?").
SELF_ID = [(re.compile(r"\bgender\b"), "gender"), (re.compile(r"\bpronouns?\b"), "pronouns"), (re.compile(r"\brace\b|\bethnicity\b"), "race_ethnicity"),
           (re.compile(r"\bveteran\b"), "veteran_status"), (re.compile(r"\bdisability\b"), "disability_status")]
ROW_ALIASES = {
    # Workday asks a level per skill on its own scale ("2 - Fair"); the row's one level answers each, and the AI repair rewords it
    # into that scale once per employer.
    "language_proficiency": {"language": "language", "proficiency": "proficiency", "fluent": "fluent", "native language": "fluent", "i am fluent in this language": "fluent", "i am fluent in this language.": "fluent",
                             "speaking": "proficiency", "writing": "proficiency", "reading": "proficiency", "comprehension": "proficiency", "overall": "proficiency"},
    "education": {"school": "school", "school or university": "school", "degree": "degree",
                  "field of study": "major", "major": "major", "gpa": "gpa", "currently attending": "current", "from": "start_date", "to": "end_date",
                  "start date": "start_date", "end date": "end_date"},
    "websites": {"url": "url"},
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


# Offered only alongside a personal or legal question, which an AI may point at one of these but never answer in its own words.
PERSONAL_FACTS = {
    "gender": "gender", "pronouns": "pronouns", "race_ethnicity": "race or ethnicity", "hispanic_or_latino": "Hispanic or Latino",
    "veteran_status": "veteran status", "disability_status": "disability status", "citizenship": "country of citizenship",
    "nationality": "nationality", "work_authorized": "authorized to work in the country of the job",
    "work_authorized_us": "authorized to work in the United States", "requires_sponsorship": "requires visa sponsorship",
}


def fact_catalog(profile, personal=False):
    """Names and plain descriptions of the profile facts that have a value; never the values themselves."""
    catalog = {key: text for key, text in FACTS.items()
               if (profile.first_name and profile.last_name if key == "full_name" else getattr(profile, key))}
    if personal:
        catalog.update({key: text for key, text in PERSONAL_FACTS.items() if getattr(profile, key) not in ("", None)})
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
        text = FACTS.get(match[3]) or PERSONAL_FACTS.get(match[3], match[3])
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
    return canonical(label) in {canonical(q) for q in (answer.question, *answer.variants)}


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
    if group == 'websites':
        # The order Workday's adapter adds website rows in (speedy_profile's websiteData).
        return [SimpleNamespace(url=url) for url in (profile.linkedin_url, profile.github_url, profile.portfolio_url) if url]
    return rows


def names_row(question, profile):
    """Whether a saved question carries one of your schools, employers or languages ("Speaking — English"): career data, not form wording."""
    return any(str(question).endswith(f" — {name}") for group, attr in ROW_NAMES.items() for entry in profile_rows(profile, group) if (name := getattr(entry, attr)))


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
    mine = [a for a in matches if a.origin == "you"]
    # Your own answer outranks the AI's, except an AI answer that only rewords it into the form's option; changing yours ends that.
    reworded = [a for a in matches if a.rewords and any(normalized(a.rewords) == normalized(str(m.value)) for m in mine)]
    matches = reworded or mine or matches
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
        label = canonical(field.label)
        if label == "i have a preferred name":
            return Resolution(profile.has_preferred_name, "profile:preferred_name")
        if label in {"full name", "name"} and profile.first_name and profile.last_name:
            return Resolution(" ".join(part for part in (profile.first_name, profile.middle_name, profile.last_name, profile.name_suffix) if part), "profile:full_name")
        attr = CANONICAL_ALIASES.get(label)
        if not attr and field.kind in CHOICE_KINDS:
            attr = next((a for pattern, a in SELF_ID if pattern.search(label)), None)
            held = str(getattr(profile, attr, "") or "") if attr else ""
            if not held or normalized(held) in {"yes", "no"} or field.options and not any(same_choice(o, held) for o in field.options):
                attr = None
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


CATEGORIES = ["Contact", "Education", "Experience", "Work eligibility", "Availability", "Diversity", "Employer-specific", "Other"]


@dataclass
class Tidy:
    """One change to the answer library that organising proposes; nothing changes until tidy() applies it."""
    text: str
    ids: list  # The answers concerned; the first is kept and the others are folded into it.
    scope: str = ""  # "global" to use the kept answer for any application.
    fact: str = ""  # A profile fact to link the kept answer to.
    conflict: bool = False  # The answers disagree: shown for you to settle, never applied.


def plan_organise(answers, profile, advice):
    """Check an AI's advice about question wordings (assistant.organise) against the answers themselves, which it never saw.

    Returns ({answer id: category}, [Tidy]). Answers are merged only when their values already agree, linked to a profile fact only
    when it holds the same value, and never widened over a different answer. Only your own confirmed answers are changed."""
    cluster = {}
    for group in advice["same"]:
        merged = set(group).union(*(cluster.get(t, ()) for t in group))
        cluster.update(dict.fromkeys(merged, merged))
    generic, quoted = set(advice["generic"]), lambda a: f"“{a.question}”"
    categories = {a.id: advice["category"][canonical(a.question)] for a in answers
                  if advice["category"].get(canonical(a.question), a.category) != a.category}
    groups = {}
    for a in answers:
        if a.origin == "you" and not a.omit and not a.rewords:
            topic = canonical(a.question)
            groups.setdefault((min(cluster.get(topic, {topic})), a.profile_name), []).append(a)
    text_field = FormField("", "", "", "text")

    def link(a, topics):
        """The profile fact advised for these wordings, when it holds this answer's value today."""
        for key in dict.fromkeys(advice["facts"][t] for t in topics if t in advice["facts"]):
            found = linked(replace(text_field, label=a.question), profile, key).value
            if not a.fact and found is not None and same_choice(found, field_value(text_field, a.value)):
                return key
        return ""

    proposals = []
    for (root, _), members in groups.items():
        topics = cluster.get(root, {root})
        everywhere = bool(topics & generic)
        value = lambda a: (normalized(str(field_value(text_field, a.value))), a.fact)
        if len({(value(a), normalized(a.country)) for a in members}) > 1:
            # Different answers per employer are normal ("Why us?"); they are a conflict only where one answer should serve everywhere.
            # Answers that differ only in the country they were given for are left as they are.
            if everywhere and len({value(a) for a in members}) > 1:
                proposals.append(Tidy(f"{len(members)} answers to {quoted(members[0])} disagree. Decide which one is right.", [a.id for a in members], conflict=True))
            continue
        # A question asked the same everywhere becomes one answer for any application; otherwise only duplicates in one place are merged.
        places = {}
        for a in members:
            places.setdefault(None if everywhere else (a.scope, a.scope_key), []).append(a)
        for same in places.values():
            same.sort(key=lambda a: a.scope != "global")  # An answer already used everywhere is the one kept.
            keep, widen, fact = same[0], everywhere and same[0].scope != "global", link(same[0], topics)
            if len(same) == 1 and not widen and not fact:
                continue
            parts = ([f"Merge {len(same)} answers to {quoted(keep)} into one"] if len(same) > 1 else []) \
                + ([("and use it" if len(same) > 1 else f"Use your answer to {quoted(keep)}") + " for any application"] if widen else []) \
                + ([("and link it" if len(same) > 1 or widen else f"Link {quoted(keep)}") + f" to your profile ({fact_name(fact)})"] if fact else [])
            proposals.append(Tidy(" ".join(parts) + ".", [a.id for a in same], "global" if widen else "", fact))
    return categories, proposals


def tidy(store, proposal):
    """Apply one proposal to the stored answers as they are now; one whose answers have since gone is skipped."""
    held = {a.id: a for a in store.answers()}
    found = [held[i] for i in proposal.ids if i in held]
    if proposal.conflict or not found:
        return False
    keep, rest = found[0], found[1:]
    wordings = [w for a in found for w in (a.question, *a.variants)]
    keep.variants = [w for w in dict.fromkeys(wordings) if normalized(w) != normalized(keep.question)]
    if proposal.scope:
        keep.scope, keep.scope_key = proposal.scope, ""
    keep.fact = proposal.fact or keep.fact
    for a in rest:
        store.delete_answer(a.id)
    store.save_answer(keep)
    return True
