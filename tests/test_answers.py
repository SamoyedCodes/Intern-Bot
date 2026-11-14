import pytest

from core.automation.answers import FACTS, fact_catalog, fact_name, linked, resolve
from core.automation.fields import FormField
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, Education, Experience, Language, employer_key

PROFILE = ApplicantProfile(
    first_name='Ada', last_name='Example', country='Singapore', preferred_middle_name='M',
    cover_letter='Dear team', cover_letter_path='/tmp/letter.pdf',
    work_authorized_us=True, requires_sponsorship=False, citizenship='Singapore', nationality='Singaporean',
    language_proficiency=[Language(language='English', proficiency='Advanced', fluent=False)],
    experience=[Experience(start_date='2025-05')])
QUESTION = FormField('q', 'Question', '', 'checkbox', required=True)


@pytest.fixture
def run():
    return ApplicationRun(job_url='https://jobs.lever.co/example/1')


def answer(run, value, **fields):
    return ApprovedAnswer(question=QUESTION.label, value=value, scope_key=run.id, **fields)


def test_application_answer_beats_global_and_false_is_an_answer(run):
    shared = ApprovedAnswer(question=QUESTION.label, value=True, scope='global')
    assert resolve(QUESTION, PROFILE, run, [shared, answer(run, False)]).value is False


def test_a_yes_no_answer_to_a_text_question_is_typed_as_yes_or_no(run):
    text = FormField('q', QUESTION.label, '', 'text')
    assert resolve(text, PROFILE, run, [answer(run, True)]).value == 'Yes'
    assert resolve(QUESTION, PROFILE, run, [answer(run, True)]).value is True


def test_a_recorded_wording_takes_the_same_answer(run):
    saved = answer(run, 'Jan - May 2027', variants=['When is your intended period of internship?'])
    reworded = FormField('k', 'When is your intended period of internship? *', '', 'text')
    assert resolve(reworded, PROFILE, run, [saved]).value == 'Jan - May 2027'
    assert resolve(FormField('k', 'Internship start date', '', 'text'), PROFILE, run, [saved]).value is None


def test_conflicting_answers_in_one_scope_resolve_to_nothing(run):
    assert resolve(QUESTION, PROFILE, run, [answer(run, False), answer(run, True)]).value is None


def test_required_field_cannot_be_omitted(run):
    assert resolve(QUESTION, PROFILE, run, [answer(run, False, omit=True)]).value is None


@pytest.mark.parametrize('country, expected', [('Singapore', False), ('Canada', None)])
def test_country_restricted_answer_needs_the_profile_country(run, country, expected):
    assert resolve(QUESTION, PROFILE, run, [answer(run, False, country=country)]).value is expected


def test_disabled_reuse_ignores_shared_answers(run):
    run.reuse_answers = False
    assert resolve(QUESTION, PROFILE, run, [ApprovedAnswer(question=QUESTION.label, scope='global', value='No')]).value is None
    assert resolve(QUESTION, PROFILE, run, [answer(run, 'Yes')]).value == 'Yes'


def test_answers_belong_to_one_profile(run):
    run.profile_name = 'Engineering'
    assert resolve(QUESTION, PROFILE, run, [answer(run, 'Yes')]).value is None


def test_employer_answers_stay_with_their_tenant(run):
    scoped = ApprovedAnswer(question=QUESTION.label, scope='employer', scope_key=employer_key(run.job_url), value='Yes')
    assert resolve(QUESTION, PROFILE, run, [scoped]).value == 'Yes'
    run.job_url = 'https://jobs.lever.co/another-company/2'
    assert resolve(QUESTION, PROFILE, run, [scoped]).value is None


@pytest.mark.parametrize('label, kind, expected', [
    ('Full name ✱', 'text', 'Ada Example'),
    ('Cover letter', 'text', 'Dear team'),
    ('Cover letter', 'file', '/tmp/letter.pdf'),
    ('Are you authorized to work in the United States?', 'radio', 'Yes'),
    ('Authorized to work in job\'s country', 'radio', 'Yes'),
    ('Are you legally authorized to work in Singapore?', 'select-one', 'Yes'),
    ('Are you authorized to work in the country where this job is located?', 'radio', 'Yes'),
    ('Country of citizenship', 'select-one', 'Singapore'),
    ('Citizenship', 'text', 'Singapore'),
    ('Nationality', 'text', 'Singaporean'),
    ('Do you require sponsorship?', 'select-one', 'No'),
    ('Preferred Middle Name', 'text', 'M'),
])
def test_profile_facts_resolve_by_exact_label(run, label, kind, expected):
    assert resolve(FormField('k', label, '', kind), PROFILE, run, []).value == expected


def test_false_row_fact_is_an_answer(run):
    fluent = FormField('k', 'Fluent', '', 'checkbox', group='language_proficiency')
    assert resolve(fluent, PROFILE, run, []).value is False


def test_missing_facts_are_never_guessed(run):
    assert resolve(FormField('k', 'Are you Hispanic or Latino?', '', 'radio'), PROFILE, run, []).value is None


@pytest.mark.parametrize('choice, expected', [(True, 'Yes'), (False, 'No'), (None, None)])
def test_work_authorization_respects_no_and_unknown(run, choice, expected):
    profile = ApplicantProfile(work_authorized=choice)
    field = FormField('k', 'Are you legally authorized to work in Singapore?', '', 'select-one')
    assert resolve(field, profile, run, []).value == expected


@pytest.mark.parametrize('question', [
    'Are you authorized to work in the United States?',
    'Are you legally authorized to work in Australia?',
    'Are you a Singapore citizen?', 'Citizenship', 'Nationality',
])
def test_singapore_authorization_does_not_imply_other_legal_facts(run, question):
    assert resolve(FormField('k', question, '', 'text'), ApplicantProfile(), run, []).value is None


@pytest.mark.parametrize('label, expected', [('From Month', '5'), ('From Year', '2025'), ('From Day', None)])
def test_date_components_never_invent_a_missing_day(run, label, expected):
    field = FormField('date', label, '', 'spinbutton', group='experience')
    assert resolve(field, PROFILE, run, []).value == expected


@pytest.mark.parametrize('start, expected', [('2025-05', '2025-05'), ('2025-05-14', '2025-05'), ('May 2025', '2025-05'), ('August 2025', '2025-08'), ('soon', None)])
def test_month_picker_reads_any_profile_date_as_year_and_month(run, start, expected):
    profile = PROFILE.model_copy(update={'experience': [Experience(start_date=start)]})
    assert resolve(FormField('date', 'Start date', '', 'month', group='experience'), profile, run, []).value == expected


@pytest.mark.parametrize('preferred, expected', [('', False), ('ada', False), ('Addie', True)])
def test_preferred_name_checkbox_follows_the_profile(run, preferred, expected):
    field = FormField('p', 'I have a preferred name', '', 'checkbox')
    assert resolve(field, PROFILE.model_copy(update={'preferred_name': preferred}), run, []).value is expected


@pytest.mark.parametrize('phone', [dict(phone_country_code='+65', phone_number='55512345'), dict(phone='+65 5551 2345')])
def test_country_phone_code_uses_the_pickers_label(run, phone):
    field = FormField('c', 'Country Phone Code', '', 'text')
    assert resolve(field, PROFILE.model_copy(update=phone), run, []).value == 'Singapore (+65)'


def test_each_language_row_uses_its_own_answer_and_profile_facts(run):
    profile = PROFILE.model_copy(update={'language_proficiency': [Language(language='English', fluent=True), Language(language='Chinese (Mandarin)', fluent=False)]})
    said = lambda question, value: ApprovedAnswer(question=question, value=value, scope_key=run.id)
    rows = lambda label, kind='select-one': [FormField('k', label, '', kind, group='language_proficiency', row=r) for r in (0, 1)]
    # Bare-label answers were given for the first row; later rows keep their own profile facts.
    first = [said('Language', 'English (UK)'), said('I am fluent in this language.', True), said('Speaking', '3 - Fluent')]
    assert [resolve(f, profile, run, first).value for f in rows('Language')] == ['English (UK)', 'Chinese (Mandarin)']
    assert [resolve(f, profile, run, first).value for f in rows('I am fluent in this language.', 'checkbox')] == [True, False]
    assert [resolve(f, profile, run, first).value for f in rows('Speaking')] == ['3 - Fluent', None]
    # A row's own answer names the row.
    own = first + [said('Speaking — Chinese (Mandarin)', '2 - Fair')]
    assert [resolve(f, profile, run, own).value for f in rows('Speaking')] == ['3 - Fluent', '2 - Fair']


def test_an_ai_link_follows_the_profile_and_is_flagged(run):
    link = ApprovedAnswer(question='Graduation year', fact='education.0.end_date.year', scope='global', origin='ai')
    field = FormField('g', 'Graduation year', '', 'text')
    profile = PROFILE.model_copy(update={'education': [Education(school='Example U', end_date='2027-05')]})
    found = resolve(field, profile, run, [link])
    assert (found.value, found.ref, found.ai) == ('2027', 'answer:' + link.id, True)
    later = profile.model_copy(update={'education': [Education(school='Example U', end_date='2028-01')]})
    assert resolve(field, later, run, [link]).value == '2028'
    assert resolve(field, PROFILE, run, [link]).value is None  # The linked education entry is gone.


def test_your_answer_outranks_the_ais_in_the_same_scope(run):
    mine, ai = answer(run, False), answer(run, True, origin='ai')
    found = resolve(QUESTION, PROFILE, run, [ai, mine])
    assert found.value is False and not found.ai


def test_every_offered_fact_links_to_its_profile_value():
    profile = ApplicantProfile(**{key: 'x' for key in FACTS if key != 'full_name'},
                               education=[Education(school='U', degree='BSc', major='CS', gpa='4', start_date='2024-08', end_date='2027-05', current=True)],
                               experience=[Experience(employer='Co', job_title='Intern', location='SG', start_date='2025-05', end_date='2025-08', current=False)])
    field = FormField('k', 'Anything', '', 'text')
    catalog = fact_catalog(profile)
    assert {'full_name', 'education.0.end_date', 'experience.0.current', 'language_proficiency.0.language'} <= catalog.keys()
    assert not {'gender', 'work_authorized_us', 'work_authorized', 'citizenship', 'nationality', 'employment_age', 'resume_path', 'pronouns'} & catalog.keys()
    for key in catalog:
        assert linked(field, profile, key).value not in (None, ''), key
    assert fact_name('education.0.end_date.year') == 'education #1 end or expected graduation date (year)'


def test_a_qualified_option_is_the_answer_but_a_longer_one_is_not():
    from core.automation.models import same_choice, same_choices
    assert same_choice('Singapore, SGP', 'Singapore') and same_choice('Yes - I am authorised', 'Yes') and same_choice('Python (Programming Language)', 'Python')
    assert not same_choice('Singapore Permanent Resident', 'Singapore') and not same_choice('Yesterday', 'Yes')
    assert same_choices('Python (Programming Language), SQL', 'Python, SQL') and not same_choices('Python (Programming Language)', 'Python, SQL')


@pytest.mark.parametrize('label, value', [('3. Mobile Number', '+65 9123 4567'), ('17.Email Address', 'ada@example.com'),
                                          ('Are you authorised to work in Singapore?', 'Yes'), ('What are your preferred pronouns?', 'she/her'),
                                          ('Please provide your LinkedIn URL (optional)', 'https://linkedin.com/in/ada')])
def test_numbered_reworded_and_british_questions_find_the_profile_fact(run, label, value):
    profile = PROFILE.model_copy(update=dict(phone='+65 9123 4567', email='ada@example.com', pronouns='she/her', linkedin_url='https://linkedin.com/in/ada'))
    assert resolve(FormField('q', label, '', 'text'), profile, run, []).value == value


def test_a_saved_answer_covers_the_same_question_numbered_or_without_its_question_mark(run):
    saved = ApprovedAnswer(question='How did you hear about us?', value='LinkedIn', scope='global')
    assert resolve(FormField('q', '4. How did you hear about us', '', 'text'), PROFILE, run, [saved]).value == 'LinkedIn'


@pytest.mark.parametrize('kind, options, gender, expected', [
    ('radio', ['Male', 'Female', 'Prefer not to say'], 'Female', 'Female'),
    ('combobox', [], 'Female', 'Female'),  # Options listed only while open: the page picks only that exact option.
    ('text', [], 'Female', None),  # A free-text box could ask anything that mentions gender.
    ('radio', ['Man', 'Woman'], 'Female', None),  # Not one of the form's options: asked.
])
def test_self_identification_reworded_fills_only_a_listed_option(run, kind, options, gender, expected):
    field = FormField('q', 'Which gender do you identify with?', '', kind, options=options)
    assert resolve(field, PROFILE.model_copy(update=dict(gender=gender)), run, []).value == expected


def test_a_bare_yes_or_no_self_identification_is_never_borrowed(run):
    field = FormField('q', 'Do you need an accommodation for a disability?', '', 'radio', options=['Yes', 'No'])
    assert resolve(field, PROFILE.model_copy(update=dict(disability_status='No')), run, []).value is None
