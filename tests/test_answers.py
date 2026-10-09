import pytest

from core.automation.answers import resolve
from core.automation.fields import FormField
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, Experience, Language, employer_key

PROFILE = ApplicantProfile(
    first_name='Ada', last_name='Example', country='Singapore', preferred_middle_name='M',
    cover_letter='Dear team', cover_letter_path='/tmp/letter.pdf',
    work_authorized_us=True, requires_sponsorship=False,
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


@pytest.mark.parametrize('label, expected', [('From Month', '5'), ('From Year', '2025'), ('From Day', None)])
def test_date_components_never_invent_a_missing_day(run, label, expected):
    field = FormField('date', label, '', 'spinbutton', group='experience')
    assert resolve(field, PROFILE, run, []).value == expected
