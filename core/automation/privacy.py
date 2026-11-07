"""Disable third-party telemetry and mask the applicant's identity in anything sent to an AI provider."""
import calendar
import os
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LINK = re.compile(r"\b(?:https?://|www\.)[^\s\"']+|\b(?:linkedin|github)\.com/[^\s\"']+", re.I)
MONTHS = {m for m in (*calendar.month_name, *calendar.month_abbr) if m}


def configure_privacy():
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
    os.environ["DO_NOT_TRACK"] = "1"


def redact(text, profile):
    """Replace the applicant's names, contact details and address in outgoing text with placeholders."""
    text = LINK.sub("[link]", EMAIL.sub("[email]", text))
    digits = re.sub(r"\D", "", profile.phone_number or profile.phone)[-8:]
    if len(digits) >= 6:
        # ponytail: matches the last 8 digits with any separators; parse with a phone library if numbers appear in other forms.
        text = re.sub(r"[\s().-]?".join(digits), "[phone]", text)
    for value in (profile.address_line1, profile.address_line2, profile.postal_code):
        if len(value) > 2:
            text = text.replace(value, "[address]")
    names = {profile.first_name, profile.middle_name, profile.last_name, profile.preferred_name,
             profile.preferred_middle_name, profile.preferred_last_name}
    # A name that is also a month ("May", "June") would corrupt dates, so it is left alone.
    for name in sorted((n for n in names if len(n) > 1 and n not in MONTHS), key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "[name]", text)
    return text
