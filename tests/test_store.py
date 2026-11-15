from core.automation.models import ApplicantProfile, ApplicationRun, FieldAssessment
from core.storage.local_store import LocalStore

URL = 'https://a.wd1.myworkdayjobs.com/job/R1'


def test_secrets_stay_in_the_keychain_and_never_reach_sqlite(store):
    store._vault().save_credential('a.wd1.myworkdayjobs.com', 'alias@example.test', 'UniqueSecret123')
    store.put('verified_profile', ApplicantProfile(first_name='Ada').model_dump())
    store.save_run(ApplicationRun(job_url=URL))
    assert store._vault().credential('a.wd1.myworkdayjobs.com')['password'] == 'UniqueSecret123'
    assert b'UniqueSecret123' not in store.path.read_bytes()
    assert store.get('verified_profile')['first_name'] == 'Ada'


def test_saved_run_restores_checkpoints_in_a_new_store(store):
    run = ApplicationRun(job_url=URL, completed_sections=['information'], status='needs_input')
    store.save_run(run)
    assert LocalStore(store.path).get_run(run.id) == run


def test_events_are_kept_in_order_and_deleted_with_their_run(store):
    run = ApplicationRun(job_url=URL)
    store.save_run(run)
    store.record_event(run.id, 'verification', 'sign_in', 'Manual activation required')
    store.record_event(run.id, 'answer', 'questions')
    assert [e['kind'] for e in store.events(run.id)] == ['verification', 'answer']
    store.delete_run(run.id)
    assert store.get_run(run.id) is None and store.events(run.id) == []


def test_version_1_profile_loads_and_survives_a_resave(store):
    store.put('verified_profile', {'schema_version': 1, 'first_name': 'Ada', 'education': [{'school': 'Example'}]})
    profile = store.profiles()['Default']
    assert profile.first_name == 'Ada' and profile.work_authorized_us is None
    store.save_profile('Default', profile)
    assert store.profiles()['Default'].education[0].school == 'Example'


def test_named_profiles_keep_the_default_and_run_snapshots(store):
    store.put('verified_profile', ApplicantProfile(first_name='Ada').model_dump())
    store.save_profile('Engineering', ApplicantProfile(first_name='Grace', skills='Python'))
    assert store.profiles()['Default'].first_name == 'Ada'
    assert store.get('verified_profile')['first_name'] == 'Grace'
    run = ApplicationRun(job_url='https://jobs.lever.co/example/123', profile_snapshot=store.profiles()['Engineering'])
    store.save_run(run)
    store.save_profile('Engineering', ApplicantProfile(first_name='Updated'))
    assert store.get_run(run.id).profile_snapshot.first_name == 'Grace'
    assert LocalStore(store.path).profiles()['Engineering'].first_name == 'Updated'


def test_engine_migration_runs_once_and_resets_only_unsubmitted_checks(store):
    field = FieldAssessment(key='old', label='Old', disposition='verified')
    pending = ApplicationRun(job_url='https://jobs.example.test/1', status='ready_for_review', browser='firefox',
                             fields={'old': field}, completed_sections=['old'], submission_attempted=True)
    submitted = ApplicationRun(job_url='https://jobs.example.test/2', fields={'old': field}, submission_confirmed=True)
    store.save_run(pending)
    store.save_run(submitted)
    store.record_event(pending.id, 'old_event', 'old')
    store.migrate_local_engine()
    store.migrate_local_engine()
    restored = store.get_run(pending.id)
    assert restored.status == 'needs_input' and restored.fields == {} and restored.completed_sections == []
    assert restored.submission_attempted and restored.browser == 'firefox'
    assert store.get_run(submitted.id).fields == {'old': field}
    assert [e['kind'] for e in store.events(pending.id)] == ['old_event', 'engine_migration']


def test_stop_report_groups_reasons_by_site_and_counts_runs_not_events(store):
    from tools.stops import stops
    stuck, done = ApplicationRun(job_url=URL), ApplicationRun(job_url=URL)
    other = ApplicationRun(job_url='https://careers.example.test/apply/1')
    for run in (stuck, done, other):
        store.save_run(run)
    for _ in range(2):  # the same stop after a resume is still one run
        store.record_event(stuck.id, 'answer', 'Workday:0cbd052d2e', 'No value will be guessed. [Visa status]')
    store.record_event(stuck.id, 'browser', 'Workday:0cbd052d2e', 'Paused by you. Resume when ready.')
    store.record_event(done.id, 'ready_for_review', 'Workday:ffe52ed68d')
    store.record_event(other.id, 'failed', 'start', 'TimeoutError')
    report = stops(store.path)
    assert (report['Workday']['runs'], report['Workday']['reviewed']) == (2, 1)
    assert report['Workday']['reasons'] == {('answer', 'Workday', 'No value will be guessed. [Visa status]'): 1}
    assert report['careers.example.test']['reasons'] == {('failed', 'start', 'TimeoutError'): 1}


def test_event_detail_keeps_where_an_error_was_raised_and_the_form_without_what_was_entered(store):
    from core.automation.fields import form_snapshot
    from tools.stops import details
    run = ApplicationRun(job_url=URL)
    scanned = [{'key': 'k1', 'label': 'Visa status', 'kind': 'select', 'selector': '#visa', 'value': 'Student Pass',
                'options': ['Citizen', 'Student Pass'], 'option': 'Student Pass', 'required': True, 'file_digest': 'abc123'}]
    message = 'fill("Unique' + 'Secret123") timed out'  # split so the quoted source line cannot satisfy the check below
    try:
        raise TimeoutError(message)
    except TimeoutError:
        store.record_event(run.id, 'browser', 'Workday:0cbd052d2e', 'Inspect the draft.', form_snapshot(URL + '?token=t0k3n', scanned))
    store.record_event(run.id, 'ready_for_review', 'Workday:ffe52ed68d')
    stop, quiet = store.events(run.id)
    assert quiet['detail'] == ''
    assert 'test_store.py' in stop['detail'] and 'TimeoutError' in stop['detail'] and '"label": "Visa status"' in stop['detail']
    assert '"filled": true' in stop['detail'] and '"options": ["Citizen", "Student Pass"]' in stop['detail']
    for private in ('UniqueSecret123', 't0k3n', 'abc123', '"value"', '"option"'):
        assert private not in stop['detail']
    assert [row[5] for row in details(store.path)] == [stop['detail']]


def test_a_database_from_before_event_detail_gains_the_column(tmp_path, vault):
    import sqlite3
    path = tmp_path / 'old.sqlite3'
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, stage TEXT NOT NULL, note TEXT NOT NULL)")
    db.execute("INSERT INTO events(run_id,at,kind,stage,note) VALUES ('r','2026-01-01','old','start','')")
    db.commit()
    db.close()
    assert LocalStore(path, vault).events('r')[0]['detail'] == ''
