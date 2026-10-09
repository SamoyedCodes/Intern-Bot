import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
from core.automation.models import ApplicantProfile, ApplicationRun
from core.storage.local_store import LocalStore
from core.storage.vault import CredentialVault
from gui.main_window import MainWindow
from gui.theme import apply_theme
from gui.views.application_dialogs import RunDetailsDialog
from tests.test_verified_storage import MemoryKeychain


def desktop(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    store = LocalStore(tmp_path / 'state.db', CredentialVault(MemoryKeychain()))
    return app, MainWindow(store)


def test_single_profile_answers_and_restart_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, window = desktop(tmp_path)
    try:
        view = window.profile_view
        view.editor.inputs['first_name'].setText('Ada')
        view.editor.inputs['country'].setText('Singapore')
        table, keys = view.editor.tables['education']
        view.editor.add_row(table, keys, {'school':'Example University', 'degree':'BSc'})
        assert view.save_profile()
        profile = ApplicantProfile.model_validate(window.store.get('verified_profile'))
        assert profile.education[0].school == 'Example University'
        assert profile.country == 'Singapore'
        run = ApplicationRun(company='Example', job_url='https://a.wd1.myworkdayjobs.com/job/R123', profile_snapshot=profile, status='running')
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
        window.tasks_view.add_task(run)
        window.tasks_view.load_state()
        assert window.tasks_view.tasks[0].status == 'needs_input'
        assert window.store.get_run(run.id).status == 'needs_input'
        window.tasks_view.add_task(ApplicationRun(company='Example', job_url=run.job_url+'?source=other'))
        assert len(window.tasks_view.tasks) == 1
        labels = [button.text() for button in window.findChildren(QPushButton)]
        assert 'Edit verified engine profile' not in labels
        assert 'Export Extension JSON' not in labels
        window._select_nav(1)
        window.show()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        window.grab().save(str(tmp_path/'profile.png'))
    finally:
        window.close()
        app.processEvents()


def test_queue_starts_only_one_task_and_skips_handoffs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, window = desktop(tmp_path)
    try:
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
    finally:
        window.close()


def test_credentials_and_catchall_do_not_write_password_to_sqlite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, window = desktop(tmp_path)
    try:
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
    finally:
        window.close()


def test_auto_created_workday_login_and_verification_handoff(tmp_path, monkeypatch):
    import gui.views.tasks_view as tasks_module
    from core.automation.models import InterventionRequest
    monkeypatch.chdir(tmp_path)
    app, window = desktop(tmp_path)
    try:
        profile_view, view = window.profile_view, window.tasks_view
        vault = window.store._vault()
        url = 'https://acme.wd1.myworkdayjobs.com/job/R1'
        captured = []
        monkeypatch.setattr(view.service, 'start', lambda r, p, c, **kwargs: captured.append(dict(c) if c else c) or True)
        run = ApplicationRun(job_url=url, profile_snapshot=ApplicantProfile(email='me@example.test'))
        view.add_task(run)

        # Off by default: no login is invented.
        view._start_task(run)
        assert captured[-1] == {} and not vault.credential(url)
        view._active_id = None

        profile_view.catchall.setText('apps.example.test')
        profile_view.catchall_format.setText('ben-{company}')
        assert 'ben-company@apps.example.test' in profile_view.address_preview.text()
        profile_view.auto_create.setChecked(True)
        profile_view.save_account_settings()
        view._start_task(run)
        assert captured[-1]['username'] == 'ben-acme@apps.example.test' and captured[-1]['state'] == 'new'
        assert vault.credential(url) == captured[-1]
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
        assert captured[-1]['state'] == 'verified' and vault.credential(url)['state'] == 'verified'
        assert not window.store.get_run(run.id).authentication_attempted
    finally:
        window.close()


def test_new_application_uses_only_saved_structured_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, window = desktop(tmp_path)
    try:
        window.store.put('verified_profile', ApplicantProfile(first_name='Ada').model_dump())
        # Stale desktop data is never consulted.
        window.store.put('desktop', {'profile': {'first_name': 'Old'}, 'tasks': [{'job_url':'bad'}]})
        view = window.tasks_view
        run = ApplicationRun(job_url='https://a.wd1.myworkdayjobs.com/job/R1')
        view.add_task(run)
        captured = []
        monkeypatch.setattr(view.service, 'start', lambda r, p, c, **kwargs: captured.append((r,p,c)) or True)
        view._start_task(run)
        assert captured[0][1].first_name == 'Ada'
        assert view._active_id == run.id
        assert not hasattr(run, 'engine')
    finally:
        window.close()


def test_gui_workflow_uses_real_browser_service_and_answer_dialog(tmp_path, monkeypatch):
    import asyncio
    import json
    import time
    import hashlib
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialogButtonBox
    from playwright.async_api import Page
    from core.automation.models import Education, Experience

    monkeypatch.chdir(tmp_path)
    app, window = desktop(tmp_path)
    url = 'https://boards.greenhouse.io/fixture/jobs/GUI_R1'
    fixture = (Path(__file__).parent / 'fixtures/speedyapply/greenhouse.html').read_text().replace('</form>',
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
        # Install after the service origin guard; all requests remain local.
        await page.route('**/*', local_only)
        return await original_goto(page, destination, **kwargs)
    monkeypatch.setattr(Page, 'goto', intercepted_goto)
    view = window.tasks_view
    def click(label, root=None):
        button = next(b for b in (root or view).findChildren(QPushButton) if b.text() == label and b.isVisible())
        QTest.mouseClick(button, Qt.LeftButton)
    def until(predicate, seconds=25):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert predicate(), [(r.status, r.stage, r.interventions) for r in view.tasks]
    try:
        resume = tmp_path / 'resume.pdf'
        resume.write_bytes(b'%PDF-1.4\nGUI fixture\n%%EOF')
        profile = ApplicantProfile(first_name='Ada',last_name='Example',email='ada@example.test')
        run = ApplicationRun(job_url=url, company='Fixture', profile_snapshot=profile, browser='firefox')
        assert not run.auto_submit
        view.add_task(run)
        view.table.selectRow(0)
        window.show()
        app.processEvents()
        legacy = tmp_path / 'data/browser' / hashlib.sha256(run.id.encode()).hexdigest()[:24]
        legacy.mkdir(parents=True)
        (legacy / 'preserve.txt').write_text('Old browser session must remain intact')
        # Restore an explicit session cookie through the production browser manager.
        session_key = run.id + ':speedy-chromium'
        directory = tmp_path / 'data/browser' / hashlib.sha256(session_key.encode()).hexdigest()[:24]
        directory.mkdir(parents=True, mode=0o700)
        saved = directory / 'session-cookies.json'
        saved.write_text(json.dumps([{'name':'gui_session','value':'fixture-only','url':url,'httpOnly':True,'secure':True}]))
        os.chmod(saved,0o600)
        click('Start')
        until(lambda: view.service.busy)
        click('Pause')
        until(lambda: not view.service.busy and view._active_id is None)
        assert view.tasks[0].status == 'needs_input'
        click('Resume')
        until(lambda: not view.service.busy and view._active_id is None)
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
                close = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Close)
                QTest.mouseClick(close,Qt.LeftButton)
            except Exception as error:
                errors.append(error)
                if app.activeModalWidget():
                    app.activeModalWidget().reject()
        QTimer.singleShot(50,approve)
        click('Answer questions')
        assert not errors, errors
        assert window.store.answers()[0].value is False
        click('Resume')
        until(lambda: not view.service.busy and view._active_id is None)
        final = view.tasks[0]
        assert final.status == 'ready_for_review', final.interventions
        assert all(f.disposition == 'verified' for f in final.fields.values())
        assert window.store.get_run(run.id).status == 'ready_for_review'
        assert view.table.item(0,2).text() == 'Ready for review'
        async def verify():
            manager, adapter = view.service.sessions[run.id]
            assert any(c['name']=='gui_session' and c['value']=='fixture-only' for c in await manager.context.cookies(url))
            assert await adapter.page.evaluate('window.submissions') == 0
            assert await adapter.page.locator('#first_name').input_value() == 'Ada'
            assert not await adapter.page.locator('input[type=checkbox]').is_checked()
        asyncio.run_coroutine_threadsafe(verify(), view.service.loop).result(timeout=10)
        assert requests == [url]
        assert not final.submission_attempted
        assert final.browser == 'chromium' and (legacy / 'preserve.txt').read_text() == 'Old browser session must remain intact'
        assert any(event['kind'] == 'browser_migration' for event in window.store.events(run.id))
        window.grab().save(str(tmp_path/'gui-final-review.png'))
    finally:
        window.close()
        app.processEvents()
