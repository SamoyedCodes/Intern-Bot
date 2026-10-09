from core.automation.models import ApplicantProfile,ApplicationRun,ApprovedAnswer,Education,Language
from core.automation.speedy_profile import translate
from core.storage.local_store import LocalStore


def test_profile_transport_keeps_unknowns_documents_names_and_proficiency(tmp_path):
    resume=tmp_path/'resume.docx';resume.write_bytes(b'word data stays word data')
    cover=tmp_path/'letter.txt';cover.write_text('An explicitly selected cover letter.')
    profile=ApplicantProfile(first_name='Ada',middle_name='M',last_name='Example',name_suffix='Jr',
        phone_country_code='+65',phone_number='5551234567',phone_device_type='Mobile',
        education=[Education(school='Fictional',gpa='3.8',current=None)],languages='English',
        language_proficiency=[Language(language='English',proficiency='Advanced',fluent=None)],
        resume_path=str(resume),cover_letter_path=str(cover),work_authorized_us=None,requires_sponsorship=False,
        skills=','.join('skill'+str(i) for i in range(30)))
    config=translate(profile,ApplicationRun(job_url='https://boards.greenhouse.io/example/1'),[])
    assert config['profile']['employmentData']['eligibilityUS'] is None
    assert config['profile']['employmentData']['sponsorship'] is False
    assert config['profile']['educationData'][0]['currentlyAttending'] is None
    assert config['profile']['educationData'][0]['gpa']=='3.8'
    assert config['profile']['languageData']==[{'language':'English','proficiency':'Advanced','fluent':None}]
    assert len(config['profile']['skillsData'])==30
    assert config['profile']['nameData']['middleName']=='M'
    assert config['files'][str(resume)]['mime']=='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert config['files'][str(cover)]['mime']=='text/plain'


def test_profile_migration_and_scoped_answer_transport_preserve_existing_data(tmp_path):
    store=LocalStore(tmp_path/'state.db')
    store.put('verified_profile',{'schema_version':1,'first_name':'Ada','languages':'English; French','education':[{'school':'Example'}]})
    profile=store.profiles()['Default']
    assert profile.first_name=='Ada' and profile.work_authorized_us is None
    run=ApplicationRun(job_url='https://jobs.lever.co/example/1/apply')
    answers=[ApprovedAnswer(question='Exact question',value='Approved',scope_key=run.id),
             ApprovedAnswer(question='Wrong scope',value='Do not use',scope_key='other'),
             ApprovedAnswer(question='Other profile',value='Do not use',scope='global',profile_name='Other')]
    config=translate(profile,run,answers)
    assert config['answers']['exact question']['value']=='Approved'
    assert config['answers']['wrong scope']['value'] is None
    assert config['answers']['other profile']['value'] is None
    assert [l['language'] for l in config['profile']['languageData']]==['English','French']
    store.save_profile('Default',profile)
    assert store.profiles()['Default'].education[0].school=='Example'


def test_first_use_invalidates_pending_checks_but_retains_history_and_attempts(tmp_path):
    from core.automation.models import FieldAssessment
    store=LocalStore(tmp_path/'state.db')
    field=FieldAssessment(key='old',label='Old',disposition='verified')
    pending=ApplicationRun(job_url='https://jobs.example.test/1',status='ready_for_review',browser='firefox',fields={'old':field},completed_sections=['old'],submission_attempted=True)
    submitted=ApplicationRun(job_url='https://jobs.example.test/2',fields={'old':field},submission_confirmed=True)
    store.save_run(pending);store.save_run(submitted)
    store.record_event(pending.id,'old_event','old')
    store.migrate_local_engine();store.migrate_local_engine()
    restored=store.get_run(pending.id)
    assert restored.status=='needs_input' and restored.fields=={} and restored.completed_sections==[]
    assert restored.submission_attempted and restored.browser=='firefox'
    assert store.get_run(submitted.id).fields=={'old':field}
    assert [e['kind'] for e in store.events(pending.id)]==['old_event','engine_migration']


def test_all_url_rules_preserve_application_query_and_fragment():
    from core.automation.models import canonical_url,ats_name,job_identity
    for url in ['https://a.myworkdayjobs.com/job/1?step=2#apply','https://jobs.polymer.co/example/1#apply','https://workforcenow.adp.com/mascsr/default?jobId=12', 'https://careers.example.test/?source=&ref=a%2Fb#apply']:
        assert canonical_url(url)==url
    assert ats_name('https://careers.example.test/job/1')==''
    assert canonical_url('https://careers.example.test/job/1')=='https://careers.example.test/job/1'
    assert job_identity('https://workforcenow.adp.com/mascsr/default?jobId=12')!=job_identity('https://workforcenow.adp.com/mascsr/default?jobId=13')


def test_shared_hosts_do_not_reuse_employer_answers_across_tenants():
    from core.automation.models import employer_key
    for first, second in [
        ('https://workforcenow.adp.com/mascsr/default?cid=first&jobId=1', 'https://workforcenow.adp.com/mascsr/default?cid=second&jobId=1'),
        ('https://apply.workable.com/first/j/1', 'https://apply.workable.com/second/j/1'),
        ('https://recruiting.paylocity.com/Recruiting/Jobs/Details/1', 'https://recruiting.paylocity.com/Recruiting/Jobs/Details/2'),
    ]:
        assert employer_key(first) != employer_key(second)


def test_explicit_boolean_and_added_name_language_facts_resolve_without_guessing():
    from core.automation.answers import resolve
    from core.automation.fields import FormField
    profile = ApplicantProfile(work_authorized_us=True, requires_sponsorship=False, preferred_middle_name='M',
                               language_proficiency=[Language(language='English', proficiency='Advanced', fluent=False)])
    run = ApplicationRun(job_url='https://example.myworkdayjobs.com/job/1')
    for label, kind, value in [('Are you authorized to work in the United States?', 'radio', 'Yes'),
                                ('Do you require sponsorship?', 'select-one', 'No'),
                                ('Preferred Middle Name', 'text', 'M')]:
        assert resolve(FormField('k', label, '', kind), profile, run, []).value == value
    assert resolve(FormField('k', 'Fluent', '', 'checkbox', group='language_proficiency'), profile, run, []).value is False
    assert resolve(FormField('k', 'Are you Hispanic or Latino?', '', 'radio'), profile, run, []).value is None


def test_changed_cover_letter_bytes_invalidate_saved_verification(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from core.automation.engine import ApplicationEngine
    from core.automation.models import FieldAssessment

    class ManualPage:
        page = SimpleNamespace(url='https://careers.example.test/job/1')
        binding = None
        async def discover(self): return {'matches': []}
        async def stop(self): pass

    async def scenario():
        letter = tmp_path/'cover.txt'
        letter.write_text('First explicitly approved document')
        profile = ApplicantProfile(cover_letter_path=str(letter))
        run = ApplicationRun(job_url=ManualPage.page.url)
        store = LocalStore(tmp_path/'state.db')
        engine = ApplicationEngine(store)
        await engine.start(run, profile, ManualPage())
        before = run.documents_digest
        run.fields = {'letter': FieldAssessment(key='letter', label='Cover letter', disposition='verified')}
        run.completed_sections = ['old-review']
        await engine.resume(run, profile, ManualPage())
        assert run.fields and run.completed_sections == ['old-review']
        letter.write_text('Changed document at exactly the same path')
        await engine.resume(run, profile, ManualPage())
        assert run.documents_digest != before
        assert run.fields == {} and run.completed_sections == []
        assert store.get_run(run.id).documents_digest == run.documents_digest
    asyncio.run(scenario())
