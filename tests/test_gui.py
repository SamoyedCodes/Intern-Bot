"""Desktop views against a real store. Only the marked end-to-end test starts a browser."""
import asyncio
import hashlib
import json
import os
import time

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QPushButton

import core.automation.service as service_module
import gui.views.tasks_view as tasks_module
from core.automation.models import ApplicantProfile, ApplicationRun, InterventionRequest
from core.browser.playwright_mgr import AsyncPlaywrightManager
from gui.views.application_dialogs import RunDetailsDialog
from gui.views.assistant_dialog import AssistantDialog
from gui.views.tasks_view import TaskDialog
from tests.support import FIXTURES

URL = 'https://a.wd1.myworkdayjobs.com/job/R123'


def capture_starts(view, monkeypatch):
    """Replace the browser service with a recorder of (run, profile, credential) starts."""
    started = []
    monkeypatch.setattr(view.service, 'start', lambda run, profile, credential, **kwargs: started.append((run, profile, dict(credential) if credential else credential)) or True)
    return started


def test_profile_save_keeps_structured_fields(window):
    view = window.profile_view
    view.editor.inputs['first_name'].setText('Ada')
    view.editor.inputs['country'].setText('Singapore')
    table, keys = view.editor.tables['education']
    view.editor.add_row(table, keys, {'school': 'Example University', 'degree': 'BSc'})
    assert view.save_profile()
    profile = ApplicantProfile.model_validate(window.store.get('verified_profile'))
    assert profile.first_name == 'Ada' and profile.country == 'Singapore'
    assert profile.education[0].school == 'Example University'


def test_answers_are_saved_from_run_details_and_removed_from_the_bank(window, monkeypatch):
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='running')
    details = RunDetailsDialog(window.store, run)
    details.questions.setCurrentText('Require sponsorship?')
    details.kind.setCurrentIndex(2)
    details.save_answer()
    assert window.store.answers()[0].value is False
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Yes)
    bank = window.answers_view
    bank.refresh()
    bank.table.setCurrentCell(0, 0)
    bank.remove()
    assert window.store.answers() == []


def test_restart_turns_an_interrupted_run_into_a_handoff(window):
    view = window.tasks_view
    run = ApplicationRun(company='Example', job_url=URL, status='running')
    view.add_task(run)
    view.load_state()
    assert view.tasks[0].status == 'needs_input'
    assert window.store.get_run(run.id).status == 'needs_input'


def test_the_same_job_is_added_only_once(window):
    view = window.tasks_view
    assert view.add_task(ApplicationRun(company='Example', job_url=URL))
    assert not view.add_task(ApplicationRun(company='Example', job_url=URL + '?source=other'))
    assert len(view.tasks) == 1


def test_queue_starts_one_task_and_skips_handoffs(window, monkeypatch):
    view = window.tasks_view
    tasks = [ApplicationRun(company=str(i), job_url=f'https://a.wd1.myworkdayjobs.com/job/R{i}') for i in range(3)]
    tasks[1].status = 'needs_input'
    view.tasks = tasks
    started = []
    def start(run):
        started.append(run.id)
        view._active_id = run.id
    monkeypatch.setattr(view, '_start_task', start)
    view.start_all_tasks()
    assert started == [tasks[0].id]
    assert view._queue == [tasks[2].id]
    view._active_id = None
    view._start_next()
    assert started == [tasks[0].id, tasks[2].id]


def test_start_all_skips_runs_already_in_the_pipeline(window, monkeypatch):
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    view.add_task(ApplicationRun(job_url='https://jobs.lever.co/example/1', pipeline='interviewing'))
    view.start_all_tasks()
    assert started == [] and not view._active_id


def test_new_task_uses_only_the_saved_structured_profile(window, monkeypatch):
    window.store.put('verified_profile', ApplicantProfile(first_name='Ada').model_dump())
    view = window.tasks_view
    run = ApplicationRun(job_url='https://a.wd1.myworkdayjobs.com/job/R1')
    view.add_task(run)
    started = capture_starts(view, monkeypatch)
    view._start_task(run)
    assert started[0][1].first_name == 'Ada'
    assert view._active_id == run.id


def test_catchall_login_is_generated_and_its_password_never_reaches_sqlite(window):
    view = window.profile_view
    view.site.setText('company.wd1.myworkdayjobs.com')
    view.catchall.setText('applications.example.test')
    view.generate_credential()
    assert view.username.text() == 'company_intern@applications.example.test'
    password = view.password.text()
    assert len(password) == 18
    view.save_credential()
    assert view.password.text() == ''
    assert password.encode() not in window.store.path.read_bytes()
    view.load_credential()
    assert view.password.text() == password
    assert window.store.get('catchall_domain') == 'applications.example.test'


def test_logins_are_not_invented_unless_auto_create_is_enabled(window, monkeypatch):
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    run = ApplicationRun(job_url='https://acme.wd1.myworkdayjobs.com/job/R1', profile_snapshot=ApplicantProfile(email='me@example.test'))
    view.add_task(run)
    view._start_task(run)
    assert started[-1][2] == {} and not window.store._vault().credential(run.job_url)


def test_auto_created_login_waits_for_email_verification(window, monkeypatch):
    profile_view, view, vault = window.profile_view, window.tasks_view, window.store._vault()
    url = 'https://acme.wd1.myworkdayjobs.com/job/R1'
    started = capture_starts(view, monkeypatch)
    run = ApplicationRun(job_url=url, profile_snapshot=ApplicantProfile(email='me@example.test'))
    view.add_task(run)
    profile_view.catchall.setText('apps.example.test')
    profile_view.catchall_format.setText('ben-{company}')
    assert 'ben-company@apps.example.test' in profile_view.address_preview.text()
    profile_view.auto_create.setChecked(True)
    profile_view.save_account_settings()
    view._start_task(run)
    credential = started[-1][2]
    assert credential['username'] == 'ben-acme@apps.example.test' and credential['state'] == 'new'
    assert vault.credential(url) == credential
    view._active_id = None

    # The engine handed off for email verification.
    vault.set_account_state(url, 'pending_verification')
    run.status, run.authentication_attempted = 'needs_input', True
    run.interventions = [InterventionRequest(kind='activation', message='Verify')]
    notifications = []
    monkeypatch.setattr(tasks_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(tasks_module.subprocess, 'Popen', lambda args, **kwargs: notifications.append(args))
    view.on_finished(run)
    assert view.status_label(run) == 'Waiting for email verification'
    assert len(notifications) == 1 and notifications[0][-1].startswith('acme.wd1.myworkdayjobs.com:')
    view.render(select_id=run.id)
    assert view.start_btn.text() == "I've verified my account"

    view.start_btn.click()
    assert started[-1][2]['state'] == 'verified' and vault.credential(url)['state'] == 'verified'
    assert not window.store.get_run(run.id).authentication_attempted


def test_named_profiles_switch_in_the_editor(window):
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


def test_new_application_uses_saved_settings_and_the_active_profile(window):
    window.store.save_profile('Engineering', ApplicantProfile(skills='Python'))
    window.settings_view.auto_advance.setChecked(False)
    window.settings_view.save_options()
    dialog = TaskDialog(window.tasks_view)
    dialog.url.setText('https://jobs.lever.co/example/1')
    run = dialog.application()
    assert run.browser == 'chromium' and not run.auto_submit and not run.auto_advance
    assert run.profile_name == 'Engineering' and run.profile_snapshot.skills == 'Python'


def test_tracker_saves_stage_and_notes(window):
    tracker = window.tasks_view
    run = ApplicationRun(job_url='https://jobs.lever.co/example/1')
    assert tracker.add_task(run)
    assert tracker.selected().id == run.id
    tracker.stage.setCurrentIndex(tracker.stage.findData('interviewing'))
    tracker.notes.setPlainText('Follow up next week')
    tracker.save_tracking()
    saved = window.store.get_run(run.id)
    assert saved.notes == 'Follow up next week' and saved.pipeline == 'interviewing' and saved.submitted_at


def test_cloud_assistant_requires_consent(window):
    dialog = AssistantDialog(window.store, ApplicationRun(job_url='https://jobs.lever.co/example/1'))
    dialog.start()
    assert dialog.worker is None and 'consent' in dialog.notice.text()


def test_each_ai_provider_keeps_its_own_model_and_key(window):
    settings, vault = window.settings_view, window.store._vault()
    settings.provider.setCurrentIndex(settings.provider.findData('openai'))
    assert window.store.get('ai_provider') == 'openai' and settings.ai_model.text() == 'gpt-6-luna'
    settings.ai_key.setText('sk-test')
    settings.save_api_key()
    assert vault.get('openai-api-key') == 'sk-test' and not vault.get('gemini-api-key')
    assert 'OpenAI' in AssistantDialog(window.store, ApplicationRun(job_url='https://jobs.lever.co/example/1')).consent.text()


@pytest.mark.browser
def test_desktop_workflow_pauses_asks_and_reaches_review_without_submitting(window, tmp_path, monkeypatch):
    from playwright.async_api import Page
    app = QApplication.instance()
    url = 'https://boards.greenhouse.io/fixture/jobs/GUI_R1'
    fixture = (FIXTURES / 'greenhouse.html').read_text().replace('</form>',
        '<label>Available for this internship?<input type="checkbox"></label><button type="button" id="submit_app" onclick="window.submissions++">Submit Application</button></form><script>window.submissions=0</script>')
    requests = []
    original_goto = Page.goto
    async def intercepted_goto(page, destination, **kwargs):
        assert destination == url
        async def local_only(route):
            requests.append(route.request.url)
            if route.request.url == url and route.request.method == 'GET':
                await route.fulfill(status=200, content_type='text/html', body=fixture)
            else:
                await route.abort()
        # Installed after the service's origin guard; every request stays local.
        await page.route('**/*', local_only)
        return await original_goto(page, destination, **kwargs)
    monkeypatch.setattr(Page, 'goto', intercepted_goto)
    # The service opens a visible browser for the user; tests keep it headless.
    monkeypatch.setattr(service_module, 'AsyncPlaywrightManager', lambda **kwargs: AsyncPlaywrightManager(**{**kwargs, 'headless': True}))
    view = window.tasks_view
    def click(label, root=None):
        button = next(b for b in (root or view).findChildren(QPushButton) if b.text() == label and b.isVisible())
        QTest.mouseClick(button, Qt.LeftButton)
    def wait_for(predicate, seconds=25):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert predicate(), [(r.status, r.stage, r.interventions) for r in view.tasks]

    profile = ApplicantProfile(first_name='Ada', last_name='Example', email='ada@example.test')
    run = ApplicationRun(job_url=url, company='Fixture', profile_snapshot=profile, browser='firefox')
    assert not run.auto_submit
    view.add_task(run)
    view.table.selectRow(0)
    window.show()
    app.processEvents()
    # A run from the retired Firefox engine keeps its old browser directory untouched.
    legacy = tmp_path / 'data/browser' / hashlib.sha256(run.id.encode()).hexdigest()[:24]
    legacy.mkdir(parents=True)
    (legacy / 'preserve.txt').write_text('Old browser session must remain intact')
    # Restore an explicit session cookie through the production browser manager.
    directory = tmp_path / 'data/browser' / hashlib.sha256((run.id + ':speedy-chromium').encode()).hexdigest()[:24]
    directory.mkdir(parents=True, mode=0o700)
    saved = directory / 'session-cookies.json'
    saved.write_text(json.dumps([{'name': 'gui_session', 'value': 'fixture-only', 'url': url, 'httpOnly': True, 'secure': True}]))
    os.chmod(saved, 0o600)

    click('Start')
    wait_for(lambda: view.service.busy)
    click('Pause')
    wait_for(lambda: not view.service.busy and view._active_id is None)
    assert view.tasks[0].status == 'needs_input'
    click('Resume')
    wait_for(lambda: not view.service.busy and view._active_id is None)
    assert view.tasks[0].stage.startswith('Greenhouse:')
    assert view.tasks[0].interventions[0].question == 'Available for this internship?'

    errors = []
    def approve():
        try:
            dialog = app.activeModalWidget()
            assert isinstance(dialog, RunDetailsDialog)
            assert dialog.questions.currentText() == 'Available for this internship?'
            dialog.kind.setCurrentIndex(2)
            click('Save approved answer', dialog)
            assert 'saved' in dialog.notice.text().lower()
            QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Close), Qt.LeftButton)
        except Exception as error:
            errors.append(error)
            if app.activeModalWidget():
                app.activeModalWidget().reject()
    QTimer.singleShot(50, approve)
    click('Answer questions')
    assert not errors, errors
    assert window.store.answers()[0].value is False

    click('Resume')
    wait_for(lambda: not view.service.busy and view._active_id is None)
    final = view.tasks[0]
    assert final.status == 'ready_for_review', final.interventions
    assert all(f.disposition == 'verified' for f in final.fields.values())
    assert window.store.get_run(run.id).status == 'ready_for_review'
    assert view.table.item(0, 2).text() == 'Ready for review'
    async def inspect_browser():
        manager, adapter = view.service.sessions[run.id]
        assert any(c['name'] == 'gui_session' and c['value'] == 'fixture-only' for c in await manager.context.cookies(url))
        assert await adapter.page.evaluate('window.submissions') == 0
        assert await adapter.page.locator('#first_name').input_value() == 'Ada'
        assert not await adapter.page.locator('input[type=checkbox]').is_checked()
    asyncio.run_coroutine_threadsafe(inspect_browser(), view.service.loop).result(timeout=10)
    assert requests == [url]
    assert not final.submission_attempted
    assert final.browser == 'chromium' and (legacy / 'preserve.txt').read_text() == 'Old browser session must remain intact'
    assert any(event['kind'] == 'browser_migration' for event in window.store.events(run.id))
