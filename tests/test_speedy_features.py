import asyncio
import json
from pathlib import Path

import pytest

from core.automation.answers import resolve
from core.automation.assistant import career_facts, generate_text
from core.automation.ats import adapter_for
from core.automation.engine import ApplicationEngine
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, ats_name, canonical_url, employer_key, job_identity
from core.automation.workday import FormField
from core.storage.local_store import LocalStore
from core.tracker import activity, export_csv, import_csv
from tests.test_verified_browser import with_page
from tests.test_verified_gui import desktop


def test_named_profiles_preserve_existing_default_and_snapshots(tmp_path):
    store = LocalStore(tmp_path / 'state.db')
    store.put('verified_profile', ApplicantProfile(first_name='Ada').model_dump())
    store.save_profile('Engineering', ApplicantProfile(first_name='Grace', skills='Python'))
    assert store.profiles()['Default'].first_name == 'Ada'
    assert store.get('verified_profile')['first_name'] == 'Grace'
    run = ApplicationRun(job_url='https://jobs.lever.co/example/123', profile_snapshot=store.profiles()['Engineering'])
    store.save_run(run)
    store.save_profile('Engineering', ApplicantProfile(first_name='Updated'))
    assert store.get_run(run.id).profile_snapshot.first_name == 'Grace'
    assert LocalStore(store.path).profiles()['Engineering'].first_name == 'Updated'


def test_csv_atomic_validation_duplicates_formula_safety_and_stats(tmp_path):
    store = LocalStore(tmp_path / 'state.db')
    path = tmp_path / 'jobs.csv'
    path.write_text('Company,Title,URL,Date\nExample,Engineer,https://jobs.example.test/123,2026-10-08\nBad,Other,http://bad.test/12,2026-10-08\n')
    with pytest.raises(ValueError):
        import_csv(store, path)
    assert not store.runs()
    path.write_text('Company,Title,URL,Date\nExample,Engineer,https://jobs.example.test/123,2026-10-08\nExample,Engineer,https://jobs.example.test/123?utm_source=mail,2026-10-08\n')
    assert import_csv(store, path) == (1, 1)
    assert import_csv(store, path) == (0, 2)
    run = store.runs()[0]
    assert run.pipeline == 'applied' and run.submitted_at == '2026-10-08'
    run.notes = '\t=HYPERLINK("bad")'
    export_csv([run], path)
    assert "'\t=HYPERLINK" in path.read_text()
    pipeline, daily, total, interviews = activity([run])
    assert (pipeline['applied'], daily['2026-10-08'], total, interviews) == (1, 1, 1, 0)


def test_host_matching_query_identity_and_explicit_answers():
    for url, name in [('https://boards.greenhouse.io/example/jobs/1', 'Greenhouse'), ('https://jobs.lever.co/example/1', 'Lever'), ('https://jobs.ashbyhq.com/example/1', 'Ashby')]:
        assert ats_name(canonical_url(url)) == name
        with pytest.raises(ValueError):
            canonical_url(url.replace('.io/', '.io.evil.test/').replace('.co/', '.co.evil.test/').replace('.com/', '.com.evil.test/'))
    assert job_identity('https://boards.greenhouse.io/embed/job_app?token=1') != job_identity('https://boards.greenhouse.io/embed/job_app?token=2')
    profile = ApplicantProfile(first_name='Ada', last_name='Example', cover_letter='Dear team', cover_letter_path='/tmp/letter.pdf')
    run = ApplicationRun(job_url='https://jobs.lever.co/example/1', reuse_answers=False)
    field = FormField('k', 'Full name ✱', '', 'text')
    assert resolve(field, profile, run, []).value == 'Ada Example'
    field.label = 'Cover letter'
    assert resolve(field, profile, run, []).value == 'Dear team'
    field.kind = 'file'
    assert resolve(field, profile, run, []).value == '/tmp/letter.pdf'
    field.label = 'Question'
    assert resolve(field, profile, run, [ApprovedAnswer(question='Question', scope='global', value='No')]).value is None
    assert resolve(field, profile, run, [ApprovedAnswer(question='Question', scope_key=run.id, value='Yes')]).value == 'Yes'
    run.profile_name = 'Engineering'
    assert resolve(field, profile, run, [ApprovedAnswer(question='Question', scope_key=run.id, value='Yes')]).value is None
    run.profile_name = 'Default'
    run.reuse_answers = True
    scoped = ApprovedAnswer(question='Question', scope='employer', scope_key=employer_key(run.job_url), value='Yes')
    assert resolve(field, profile, run, [scoped]).value == 'Yes'
    run.job_url = 'https://jobs.lever.co/another-company/2'
    assert resolve(field, profile, run, [scoped]).value is None


def test_hosted_adapter_rejects_same_host_different_employer():
    class Page:
        url = 'https://jobs.lever.co/another-company/2'
        def on(self, *args): pass
    adapter = adapter_for(Page(), 'https://jobs.lever.co/example/1')
    with pytest.raises(RuntimeError, match='employer'):
        adapter.assert_origin()


@pytest.mark.parametrize('url', ['https://boards.greenhouse.io/example/jobs/1', 'https://jobs.lever.co/example/1', 'https://jobs.ashbyhq.com/example/1'])
def test_hosted_forms_fill_upload_readback_and_manual_submission(tmp_path, url):
    async def scenario(page, store):
        resume = tmp_path / 'resume.pdf'
        resume.write_bytes(b'fictional resume')
        await page.set_content('''<h1>Software internship</h1>
          <form id="newsletter"><label>Email<input type="email"></label><button>Subscribe</button></form>
          <form onsubmit="event.preventDefault();window.sent=(window.sent||0)+1">
          <label>Full name ✱<input required></label><label>Email<input type="email" required></label>
          <label>Resume<input type="file" required></label><label>Country<select><option value="">Choose</option><option>Singapore</option></select></label>
          <button>Submit application</button></form>''')
        run = ApplicationRun(job_url=url)
        profile = ApplicantProfile(first_name='Ada', last_name='Example', email='ada@example.test', country='Singapore', resume_path=str(resume))
        await ApplicationEngine(store).start(run, profile, adapter_for(page, url, True))
        assert run.status == 'ready_for_review', run.interventions
        assert len(run.fields) == 4
        assert all(a.disposition == 'verified' for a in run.fields.values())
        assert not await page.evaluate('Boolean(window.sent)')
        assert await page.locator('#newsletter input').input_value() == ''
    asyncio.run(with_page(tmp_path, scenario))


def test_autopilot_receipt_and_no_duplicate_submission(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<form onsubmit="event.preventDefault();window.sent=(window.sent||0)+1;this.outerHTML='<h1>Thank you for applying!</h1>'">
          <label>Full name<input required></label><button>Submit Application</button></form>''')
        run = ApplicationRun(job_url='https://jobs.lever.co/example/1', auto_submit=True)
        adapter = adapter_for(page, run.job_url, True)
        engine = ApplicationEngine(store)
        profile = ApplicantProfile(first_name='Ada', last_name='Example')
        await engine.start(run, profile, adapter)
        assert run.submission_confirmed and run.pipeline == 'applied'
        assert run.submitted_at and await page.evaluate('window.sent') == 1
        await engine.resume(store.get_run(run.id), profile, adapter)
        assert await page.evaluate('window.sent') == 1
        assert store.get_run(run.id).status != 'running'
    asyncio.run(with_page(tmp_path, scenario))


def test_submission_control_is_scoped_to_the_application_form(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<form><label>Email<input></label><button onclick="window.wrong=true">Submit</button></form>
          <form><label>Full name<input></label><button type="button">Apply</button></form>''')
        run = ApplicationRun(job_url='https://jobs.lever.co/example/1', auto_submit=True)
        await ApplicationEngine(store).start(run, ApplicantProfile(first_name='Ada', last_name='Example'), adapter_for(page, run.job_url, True))
        assert run.status == 'needs_input' and not run.submission_attempted
        assert not await page.evaluate('Boolean(window.wrong)')
    asyncio.run(with_page(tmp_path, scenario))


def test_ambiguous_receipt_never_retries_and_unresolved_never_submits(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<form onsubmit="event.preventDefault();window.sent=(window.sent||0)+1;document.getElementById('error').hidden=false">
          <label>Full name<input></label><button>Submit application</button></form><div id="error" role="alert" hidden>Try later</div>''')
        run = ApplicationRun(job_url='https://jobs.ashbyhq.com/example/1', auto_submit=True)
        adapter = adapter_for(page, run.job_url, True)
        profile = ApplicantProfile(first_name='Ada', last_name='Example')
        engine = ApplicationEngine(store)
        await engine.start(run, profile, adapter)
        assert run.submission_attempted and not run.submission_confirmed
        assert run.status == 'needs_input'
        await engine.resume(store.get_run(run.id), profile, adapter)
        assert await page.evaluate('window.sent') == 1
        await page.set_content('<form><label>Unknown required<input required></label><button onclick="window.sent=999">Submit application</button></form>')
        run = ApplicationRun(job_url=run.job_url, auto_submit=True)
        await engine.start(run, profile, adapter)
        assert not run.submission_attempted and run.status == 'needs_input'
        assert await page.evaluate('window.sent') != 999
    asyncio.run(with_page(tmp_path, scenario))


def test_manual_continue_same_heading_and_no_navigation_when_disabled(tmp_path):
    async def scenario(page, store):
        html = '''<h1>Application</h1><form><label>First name<input></label><button type="button" onclick="this.parentElement.innerHTML='<label>Email<input type=email></label><button>Submit application</button>'">Next</button></form>'''
        await page.set_content(html)
        url = 'https://jobs.lever.co/example/1'
        profile = ApplicantProfile(first_name='Ada', email='ada@example.test')
        run = ApplicationRun(job_url=url, auto_advance=False)
        adapter = adapter_for(page, url, True)
        await ApplicationEngine(store).start(run, profile, adapter)
        assert run.status == 'needs_input' and await page.get_by_role('button', name='Next').count() == 1
        assert run.completed_sections
        await page.get_by_role('button', name='Next').click()
        await ApplicationEngine(store).resume(run, profile, adapter)
        assert run.status == 'ready_for_review'
        await page.set_content(html)
        run = ApplicationRun(job_url=url)
        await ApplicationEngine(store).start(run, profile, adapter)
        assert run.status == 'ready_for_review', run.interventions
    asyncio.run(with_page(tmp_path, scenario))


def test_gemini_context_is_allowlisted_and_draft_request_is_bounded(monkeypatch):
    from core.automation import assistant
    profile = ApplicantProfile(first_name='Private name', email='secret@example.test', resume_path='/private/resume.pdf', gender='Private', skills='Python')
    facts = career_facts(profile)
    assert facts['skills'] == 'Python' and not {'email', 'resume_path', 'gender', 'first_name'} & facts.keys()
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            assert limit == 1_000_001
            return json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'Draft based on Python.'}]}}]}).encode()
    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            assert timeout == 40
            return Response()
    monkeypatch.setattr(assistant, 'build_opener', lambda *args: Opener())
    assert generate_text('key', 'gemini-2.5-flash', 'draft', json.dumps(facts)) == 'Draft based on Python.'
    assert 'key' not in captured[0].full_url
    assert captured[0].get_header('X-goog-api-key') == 'key'
    assert 'tools' not in json.loads(captured[0].data)
    with pytest.raises(ValueError):
        generate_text('key', '../../evil', 'draft', 'context')
    with pytest.raises(ValueError):
        generate_text('key', 'gemini-2.5-flash', 'draft', 'a' * 60001)
    assert len(captured) == 1


def test_desktop_profiles_settings_tracker_and_cloud_consent(tmp_path, monkeypatch):
    from gui.views.tasks_view import TaskDialog
    from gui.views.tracker_dialog import TrackerDialog
    from gui.views.assistant_dialog import AssistantDialog
    monkeypatch.chdir(tmp_path)
    app, window = desktop(tmp_path)
    try:
        view = window.profile_view
        view.editor.inputs['first_name'].setText('Ada')
        assert view.save_profile()
        view.save_named('Engineering')
        view.editor.inputs['skills'].setText('Python')
        assert view.save_profile()
        view.profile_names.setCurrentText('Default')
        assert view.editor.inputs['skills'].text() == ''
        view.profile_names.setCurrentText('Engineering')
        assert view.editor.inputs['skills'].text() == 'Python'
        settings = window.settings_view
        settings.browser.setCurrentIndex(settings.browser.findData('firefox'))
        settings.auto_advance.setChecked(False)
        settings.save_options()
        dialog = TaskDialog(window.tasks_view)
        dialog.url.setText('https://jobs.lever.co/example/1')
        run = dialog.application()
        assert run.browser == 'firefox' and not run.auto_submit and not run.auto_advance
        assert run.profile_name == 'Engineering' and run.profile_snapshot.skills == 'Python'
        assert window.tasks_view.add_task(run)
        tracker = TrackerDialog(window.store, run)
        tracker.pipeline.setCurrentText('interviewing')
        tracker.notes.setPlainText('Follow up next week')
        tracker.save()
        assert window.store.get_run(run.id).notes == 'Follow up next week'
        cloud = AssistantDialog(window.store, run)
        cloud.start()
        assert cloud.worker is None and 'consent' in cloud.notice.text()
        window.tasks_view.start_all_tasks()
        assert not window.tasks_view._active_id
        window.show()
        app.processEvents()
        window.grab().save(str(tmp_path / 'speedy-desktop.png'))
    finally:
        window.close()
