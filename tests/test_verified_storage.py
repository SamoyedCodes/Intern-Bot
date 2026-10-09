import json

import pytest

from core.automation.answers import resolve
from core.automation.models import ApplicantProfile, ApprovedAnswer, ApplicationRun, canonical_url, job_identity
from core.automation.fields import FormField
from core.storage.local_store import LocalStore
from core.storage.vault import CredentialVault


class MemoryKeychain:
    def __init__(self):
        self.values = {}
    def set_password(self, service, key, value):
        self.values[(service, key)] = value
    def get_password(self, service, key):
        return self.values.get((service, key))


def test_credentials_only_enter_keychain_and_old_json_is_ignored(tmp_path):
    source = tmp_path / 'app_state.json'
    source.write_text('{"profile":{"first_name":"Old"}}')
    vault = CredentialVault(MemoryKeychain())
    store = LocalStore(tmp_path / 'state.db', vault)
    vault.save_credential('a.wd1.myworkdayjobs.com', 'alias@example.test', 'UniqueSecret123')
    store.put('verified_profile', ApplicantProfile(first_name='Ada').model_dump())
    store.save_run(ApplicationRun(job_url='https://a.wd1.myworkdayjobs.com/job/R1'))
    assert store._vault().credential('a.wd1.myworkdayjobs.com')['password'] == 'UniqueSecret123'
    assert b'UniqueSecret123' not in store.path.read_bytes()
    assert store.get('verified_profile')['first_name'] == 'Ada'
    assert source.read_text() == '{"profile":{"first_name":"Old"}}'
    assert not store.get('desktop')


def test_answers_scope_country_conflicts_and_false_value(tmp_path):
    store = LocalStore(tmp_path / 'state.db')
    run = ApplicationRun(job_url='https://a.wd1.myworkdayjobs.com/job/R1')
    profile = ApplicantProfile(country='Singapore')
    field = FormField('q', 'Require sponsorship?', '', 'checkbox', required=True)
    global_answer = ApprovedAnswer(question=field.label, value=True, scope='global')
    local = ApprovedAnswer(question=field.label, value=False, scope_key=run.id, country='Singapore')
    assert resolve(field, profile, run, [global_answer, local]).value is False
    conflict = local.model_copy(update={'id':'other', 'value':True})
    assert resolve(field, profile, run, [local, conflict]).value is None
    omit = local.model_copy(update={'omit':True})
    assert resolve(field, profile, run, [omit]).value is None
    other_country = local.model_copy(update={'country':'Canada'})
    assert resolve(field, profile, run, [other_country]).value is None
    store.save_answer(local)
    assert store.answers() == [local]


def test_job_identity_and_url_boundary():
    assert job_identity('https://a.wd1.myworkdayjobs.com/en-US/job/Intern_R123') == job_identity('https://a.wd1.myworkdayjobs.com/job/Different_R123')
    for url in ['http://a.myworkdayjobs.com/job', 'https://user:secret@a.myworkdayjobs.com/job', 'https://a.myworkdayjobs.com:8080/job']:
        with pytest.raises(ValueError):
            canonical_url(url)


def test_saved_run_restores_checkpoints(tmp_path):
    store = LocalStore(tmp_path/'state.db')
    run = ApplicationRun(job_url='https://a.wd1.myworkdayjobs.com/job/R1', completed_sections=['information'], status='needs_input')
    store.save_run(run)
    restored = LocalStore(store.path).get_run(run.id)
    assert restored == run
    assert restored.status != 'ready_for_review'
    store.record_event(run.id, 'verification', 'sign_in', 'Manual activation required')
    assert store.events(run.id)[0]['kind'] == 'verification'


def test_date_components_do_not_invent_missing_day():
    from core.automation.models import Experience
    profile = ApplicantProfile(experience=[Experience(start_date='2025-05')])
    run = ApplicationRun(job_url='https://a.wd1.myworkdayjobs.com/job/R1')
    field = FormField('date', 'From Month', '', 'spinbutton', group='experience')
    assert resolve(field, profile, run, []).value == '5'
    field.label = 'From Year'
    assert resolve(field, profile, run, []).value == '2025'
    field.label = 'From Day'
    assert resolve(field, profile, run, []).value is None
