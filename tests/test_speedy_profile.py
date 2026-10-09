from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, Education, Language
from core.automation.speedy_profile import translate


def test_profile_transport_keeps_unknowns_documents_names_and_proficiency(tmp_path):
    resume = tmp_path / 'resume.docx'
    resume.write_bytes(b'word data stays word data')
    cover = tmp_path / 'letter.txt'
    cover.write_text('An explicitly selected cover letter.')
    profile = ApplicantProfile(first_name='Ada', middle_name='M', last_name='Example', name_suffix='Jr',
        phone_country_code='+65', phone_number='5551234567', phone_device_type='Mobile',
        education=[Education(school='Fictional', gpa='3.8', current=None)], languages='English',
        language_proficiency=[Language(language='English', proficiency='Advanced', fluent=None)],
        resume_path=str(resume), cover_letter_path=str(cover), work_authorized_us=None, requires_sponsorship=False,
        skills=','.join('skill' + str(i) for i in range(30)))
    config = translate(profile, ApplicationRun(job_url='https://boards.greenhouse.io/example/1'), [])
    data = config['profile']
    assert data['employmentData']['eligibilityUS'] is None
    assert data['employmentData']['sponsorship'] is False
    assert data['educationData'][0]['currentlyAttending'] is None
    assert data['educationData'][0]['gpa'] == '3.8'
    assert data['languageData'] == [{'language': 'English', 'proficiency': 'Advanced', 'fluent': None}]
    assert len(data['skillsData']) == 30
    assert data['nameData']['middleName'] == 'M'
    assert config['files'][str(resume)]['mime'] == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert config['files'][str(cover)]['mime'] == 'text/plain'


def test_only_answers_scoped_to_this_run_and_profile_are_transported():
    run = ApplicationRun(job_url='https://jobs.lever.co/example/1/apply')
    answers = [ApprovedAnswer(question='Exact question', value='Approved', scope_key=run.id),
               ApprovedAnswer(question='Wrong scope', value='Do not use', scope_key='other'),
               ApprovedAnswer(question='Other profile', value='Do not use', scope='global', profile_name='Other')]
    config = translate(ApplicantProfile(first_name='Ada'), run, answers)
    assert config['answers']['exact question']['value'] == 'Approved'
    assert config['answers']['wrong scope']['value'] is None
    assert config['answers']['other profile']['value'] is None


def test_language_list_splits_into_entries():
    config = translate(ApplicantProfile(languages='English; French'), ApplicationRun(job_url='https://jobs.lever.co/example/1'), [])
    assert [entry['language'] for entry in config['profile']['languageData']] == ['English', 'French']
