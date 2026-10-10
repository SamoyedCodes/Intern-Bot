"""Lossless local profile transport. Unknown facts are never inferred as false."""
import base64
import hashlib
import mimetypes
import re
from pathlib import Path

from core.automation.answers import resolve
from core.automation.models import normalized
from core.automation.fields import FormField


def file_payload(path):
    source = Path(path).expanduser()
    if source.suffix.lower() not in {'.pdf', '.doc', '.docx', '.txt', '.rtf'}:
        raise ValueError('Choose a PDF, Word, text or RTF document; files are never converted.')
    data = source.read_bytes()
    if len(data) > 25 * 1024 * 1024:
        raise ValueError('The selected document exceeds the 25 MB local transport limit.')
    return dict(resumeBase64=base64.b64encode(data).decode(), fileName=source.name,
                fileSize=len(data), mime=mimetypes.guess_type(source.name)[0] or 'application/octet-stream',
                digest=hashlib.sha256(data).hexdigest())


def translate(profile, run, answers):
    phone = re.fullmatch(r'(\+\d{1,3})[\s-]+([\d\s()-]+)', profile.phone.strip())
    def boolean(value):
        return {'yes': True, 'no': False, 'i choose not to disclose': 'undisclosed'}.get(normalized(value))
    files = {p: file_payload(p) for p in (profile.resume_path, profile.cover_letter_path) if p}
    languages = [dict(language=l.language, proficiency=l.proficiency, fluent=l.fluent) for l in profile.language_proficiency]
    for language in re.split(r'[,;\n]', profile.languages):
        if language.strip() and not any(normalized(l['language']) == normalized(language) for l in languages):
            languages.append(dict(language=language.strip(), proficiency='', fluent=None))
    translated = {
        'profileName': run.profile_name,
        'nameData': dict(prefix=profile.name_prefix,firstName=profile.first_name,middleName=profile.middle_name,
                         lastName=profile.last_name,suffix=profile.name_suffix,preferredName=profile.has_preferred_name,
                         preferredFirstName=profile.preferred_name,preferredMiddleName=profile.preferred_middle_name,
                         preferredLastName=profile.preferred_last_name),
        'addressData': dict(line1=profile.address_line1,line2=profile.address_line2,city=profile.city,state=profile.region,
                            postalCode=profile.postal_code,country=profile.country),
        'contactData': dict(email=profile.email,phoneDeviceType=profile.phone_device_type,
                            phoneCountryCode=profile.phone_country_code or (phone[1] if phone else ''),
                            phoneNumber=profile.phone_number or (re.sub(r'\D','',phone[2]) if phone else profile.phone)),
        'jobData': [dict(jobTitle=e.job_title,company=e.employer,location=e.location,startDate=e.start_date,
                         currentlyWorkHere=e.current,endDate=e.end_date,description=e.description) for e in profile.experience],
        'educationData': [dict(school=e.school,degree=e.degree,fieldOfStudy=e.major,startDate=e.start_date,
                               currentlyAttending=e.current,endDate=e.end_date,gpa=e.gpa) for e in profile.education],
        'languageData': languages,
        'skillsData': [s.strip() for s in re.split(r'[,;\n]', profile.skills) if s.strip()] or None,
        'resumeData': files.get(profile.resume_path, {}),
        'websiteData': dict(websites=[profile.portfolio_url] if profile.portfolio_url else [],github=profile.github_url,
                            linkedin=profile.linkedin_url,personal=profile.portfolio_url),
        'employmentData': dict(eligibilityUS=profile.work_authorized_us,sponsorship=profile.requires_sponsorship,
                               gender=profile.gender,ethnicity=profile.race_ethnicity,veteran=boolean(profile.veteran_status),
                               disability=boolean(profile.disability_status),age=profile.employment_age,
                               hispanicOrLatino=profile.hispanic_or_latino),
    }
    approved = {}
    for answer in answers:
        field = FormField('',answer.question,'','text')
        resolution = resolve(field,profile,run,answers)
        approved[normalized(answer.question)] = dict(value=resolution.value,omit=resolution.omit,ref=resolution.ref)
    return dict(profile=translated,files=files,answers=approved)
