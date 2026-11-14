"""Desktop views against a real store. Only the marked end-to-end test starts a browser."""
import asyncio
import hashlib
import json
import os
import time

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QPushButton, QTreeWidget

import core.automation.service as service_module
import gui.views.tasks_view as tasks_module
from core.automation.answers import resolve
from core.automation.fields import FormField
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, InterventionRequest
from core.automation.speedy_profile import translate
from core.browser.playwright_mgr import AsyncPlaywrightManager
from gui.views.application_dialogs import RunDetailsDialog
from gui.views.assistant_dialog import AssistantDialog
from gui.views.tasks_view import TaskDialog, stage_text
from tests.support import FIXTURES

URL = 'https://a.wd1.myworkdayjobs.com/job/R123'


def capture_starts(view, monkeypatch):
    """Replace the browser service with a recorder of (run, profile, credential) starts."""
    started = []
    monkeypatch.setattr(view.service, 'start', lambda run, profile, credential, **kwargs: started.append((run, profile, dict(credential) if credential else credential)) or True)
    return started


def test_profile_save_keeps_structured_fields(window):
    view = window.profile_view
    assert view.editor.inputs['work_authorized'].currentData() is True
    assert view.editor.inputs['citizenship'].text() == view.editor.inputs['nationality'].text() == ''
    view.editor.inputs['first_name'].setText('Ada')
    view.editor.inputs['country'].setText('Singapore')
    view.editor.inputs['citizenship'].setText('Malaysia')
    view.editor.inputs['nationality'].setText('Malaysian')
    table, keys = view.editor.tables['education']
    view.editor.add_row(table, keys, {'school': 'Example University', 'degree': 'BSc'})
    assert view.save_profile()
    profile = ApplicantProfile.model_validate(window.store.get('verified_profile'))
    assert profile.first_name == 'Ada' and profile.country == 'Singapore'
    assert profile.work_authorized is True and profile.citizenship == 'Malaysia' and profile.nationality == 'Malaysian'
    assert profile.education[0].school == 'Example University'


@pytest.mark.parametrize('choice', [False, None])
def test_eligibility_editor_saves_and_restores_choices_without_losing_legacy_facts(window, choice):
    view = window.profile_view
    view.editor.load_profile(ApplicantProfile(work_authorized_us=False))
    combo = view.editor.inputs['work_authorized']
    combo.setCurrentIndex(combo.findData(choice))
    view.editor.inputs['citizenship'].setText('Singapore')
    view.editor.inputs['nationality'].setText('Singaporean')
    assert view.save_profile()
    saved = window.store.profiles()['Default']
    assert saved.work_authorized is choice and saved.work_authorized_us is False
    view.editor.load_profile(ApplicantProfile())
    view.editor.load_profile(saved)
    assert combo.currentData() is choice
    assert view.editor.inputs['citizenship'].text() == 'Singapore'
    assert view.editor.inputs['nationality'].text() == 'Singaporean'
    assert view.editor.profile() == saved


def test_answers_are_saved_from_run_details_and_removed_from_the_bank(window, monkeypatch):
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='running')
    details = RunDetailsDialog(window.store, run)
    details.cards[0].wording.setText('Require sponsorship?')
    details.cards[0].text.setPlainText('No')
    details.save_answers()
    assert window.store.answers()[0].value == 'No' and details.result() != QDialog.Accepted  # No open question: nothing resumes.
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Yes)
    bank = window.answers_view
    bank.refresh()
    bank.tree.setCurrentItem(bank.tree.topLevelItem(0))
    bank.remove()
    assert window.store.answers() == []



def test_a_paragraph_long_saved_answer_does_not_widen_the_answer_dialog(window):
    window.store.save_answer(ApprovedAnswer(question='Are you fully vaccinated?', value='Fully vaccinated means the full approved regime. ' * 40, scope='global'))
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input',
                         interventions=[InterventionRequest(kind='answer', message='', question='Are you vaccinated?')])
    details = RunDetailsDialog(window.store, run)
    assert details.cards[0].same.count() == 2
    assert details.minimumSizeHint().width() < 900

def test_a_reworded_question_joins_a_saved_answer_and_the_wording_can_be_removed(window, monkeypatch):
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input',
                         interventions=[InterventionRequest(kind='answer', message='', question='What is your intended period of internship?')])
    window.store.save_answer(ApprovedAnswer(question='When is your intended period of internship?', value='Jan - May 2027', scope='global'))
    details = RunDetailsDialog(window.store, run)
    card = details.cards[0]
    assert card.scope() == 'application'  # A job's own specifics (an internship period) stay with this application.
    card.same.setCurrentIndex(1)
    assert not card.text.isEnabled() and not card.scope_row.isEnabled()
    details.save_answers()
    assert window.store.answers()[0].variants == ['What is your intended period of internship?'] and len(window.store.answers()) == 1
    bank = window.answers_view
    bank.refresh()
    answer = bank.tree.topLevelItem(0)
    assert answer.childCount() == 1 and answer.child(0).text(0) == 'What is your intended period of internship?'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Yes)
    bank.tree.setCurrentItem(answer.child(0))
    assert bank.remove_btn.text() == 'Remove wording…'
    bank.remove()
    assert window.store.answers()[0].variants == []


def test_each_question_starts_with_its_form_control_type(window, tmp_path):
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF')
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input', interventions=[
        InterventionRequest(kind='answer', message='', question='Have you worked with us before?', field_kind='text'),
        InterventionRequest(kind='answer', message='', question='Degree', options=['Bachelor Degree'], field_kind='combobox'),
        InterventionRequest(kind='answer', message='', question='Resume', field_kind='file')])
    details = RunDetailsDialog(window.store, run)
    text, choice, upload = details.cards
    assert text.text and not text.choice and choice.choice and upload.file
    assert [choice.choice.itemText(i) for i in range(choice.choice.count())] == ['Bachelor Degree', 'Leave blank']
    upload.file.setText(str(resume))
    choice.choice.setCurrentText('Master')
    details.save_answers()
    assert window.store.answers() == []  # Only the form's own options are accepted, and nothing is saved until they are.
    choice.choice.setCurrentIndex(0)
    details.save_answers()
    assert details.result() == QDialog.Accepted  # The open question is optional, so the application continues with it left blank.
    assert {a.question: (a.value, a.omit) for a in window.store.answers()} == {
        'Resume': (str(resume), False), 'Degree': ('Bachelor Degree', False), 'Have you worked with us before?': ('', True)}
    assert str(resume) in translate(ApplicantProfile(), run, window.store.answers())['files']


def test_tick_all_that_apply_options_are_asked_as_one_checklist(window):
    asked = 'Where have you seen IMDA messages?'
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input', interventions=[
        InterventionRequest(kind='answer', message='', question=f'{asked} — {option}', field_kind='checkbox')
        for option in ('IMDA Website', 'IMDA LinkedIn', 'Word of Mouth')] + [
        InterventionRequest(kind='answer', message='', question='Expected salary', field_kind='text')])
    details = RunDetailsDialog(window.store, run)
    assert details.pending == [asked, 'Expected salary']
    checklist = details.cards[0].checklist
    assert [checklist.item(r).text() for r in range(checklist.count())] == ['IMDA Website', 'IMDA LinkedIn', 'Word of Mouth']
    checklist.item(1).setCheckState(Qt.Checked)
    assert details.progress.text() == '1 of 2 questions answered'
    details.save_answers()
    assert {a.question: a.value for a in window.store.answers() if not a.omit} == {
        f'{asked} — IMDA Website': False, f'{asked} — IMDA LinkedIn': True, f'{asked} — Word of Mouth': False}


def test_optional_questions_left_empty_are_left_blank_instead_of_asked_again(window):
    asked = 'Where did you hear about us?'
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input', interventions=[
        InterventionRequest(kind='answer', message='', question=f'{asked} — {option}', field_kind='checkbox') for option in ('LinkedIn', 'A friend')] + [
        InterventionRequest(kind='answer', message='', question='If Other, please specify', field_kind='text')])
    details = RunDetailsDialog(window.store, run)
    assert details.save_btn.text() == 'Save answers && continue'
    details.save_answers()
    assert details.result() == QDialog.Accepted
    answers = window.store.answers()
    assert {a.question for a in answers} == {f'{asked} — LinkedIn', f'{asked} — A friend', 'If Other, please specify'}
    assert all(a.omit and (a.scope, a.scope_key) == ('application', run.id) for a in answers)
    assert all(resolve(FormField('', a.question, '', 'text'), ApplicantProfile(), run, answers).omit for a in answers)


def test_a_question_starts_from_what_the_form_holds_or_the_saved_answer_it_did_not_take(window):
    ask = lambda question, **kw: InterventionRequest(kind='answer', message='The form did not take the approved value.', question=question, **kw)
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input', interventions=[
        ask('Are you located in Singapore?', options=['Yes', 'No'], field_kind='combobox', value='yes'),
        ask('City', field_kind='text', value='Singapore'),
        ask('I agree to the terms', field_kind='checkbox', value=True),
        ask('Heard from — LinkedIn', field_kind='checkbox', value=True), ask('Heard from — A friend', field_kind='checkbox'),
        ask('Currently enrolled?', options=['Yes', 'No'], field_kind='radio'),
        InterventionRequest(kind='conflict', message='Existing browser value conflicts with the profile.', question='Currently enrolled?', options=['Yes', 'No'], field_kind='radio', value='No'),
        InterventionRequest(kind='conflict', message='Existing browser value conflicts with the profile.', question='Country of citizenship', field_kind='text', value='Singapore Citizen')])
    details = RunDetailsDialog(window.store, run)
    located, city, terms, heard, enrolled, citizenship = details.cards
    assert [c.answer() for c in (located, city, terms, enrolled)] == [('value', 'Yes', False), ('value', 'Singapore', False), ('value', True, False), ('value', 'No', False)]
    assert heard.answer() == ('checklist', {'Heard from — LinkedIn': True, 'Heard from — A friend': False})
    # The form's own wording against a saved answer stays with this application, even for a stable fact.
    assert citizenship.scope() == 'application' and enrolled.scope() == 'application'
    assert details.progress.text() == '6 of 6 questions answered'


def test_with_answer_reuse_off_every_answer_stays_with_this_application(window):
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input', reuse_answers=False, interventions=[
        InterventionRequest(kind='answer', message='', question='Will you require visa sponsorship?', required=True)])
    details = RunDetailsDialog(window.store, run)
    card = details.cards[0]
    assert card.scope() == 'application' and card.scope_row.isHidden()
    card.text.setPlainText('No')
    details.save_answers()
    assert resolve(FormField('', 'Will you require visa sponsorship?', '', 'text'), ApplicantProfile(), run, window.store.answers()).value == 'No'


def test_answering_a_reworded_question_leaves_the_original_answer_alone(window):
    original, reworded = 'Are you authorized to work in Singapore?', 'Are you legally authorised to work here?'
    window.store.save_answer(ApprovedAnswer(question=original, variants=[reworded], value='Yes', scope='global'))
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input', interventions=[
        InterventionRequest(kind='answer', message='The exact approved option is not offered by this form.', question=reworded,
                            required=True, options=['Yes, I do', 'No, I do not'], field_kind='select-one')])
    details = RunDetailsDialog(window.store, run)
    assert details.cards[0].scope() == 'global'
    details.cards[0].choice.setCurrentText('Yes, I do')
    details.save_answers()
    value = lambda question: resolve(FormField('', question, '', 'text'), ApplicantProfile(), run, window.store.answers()).value
    assert (value(original), value(reworded)) == ('Yes', 'Yes, I do')


def test_restart_turns_an_interrupted_run_into_a_handoff(window):
    view = window.tasks_view
    run = ApplicationRun(company='Example', job_url=URL, status='running', approved_review={'Documents': 'd1'})
    view.add_task(run)
    view.load_state()
    assert view.tasks[0].status == 'needs_input'
    saved = window.store.get_run(run.id)
    assert saved.status == 'needs_input' and not saved.approved_review  # Resuming after a crash can't send without a fresh approval.


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


def test_catchall_login_is_created_in_1password_and_its_password_never_reaches_sqlite(window):
    view, vault = window.profile_view, window.store._vault()
    view.site.setText('company.wd1.myworkdayjobs.com')
    view.catchall.setText('applications.example.test')
    view.create_credential()
    login = vault.credential('company.wd1.myworkdayjobs.com')
    assert login['username'] == 'company_intern@applications.example.test' and login['state'] == 'new'
    assert login['password'].encode() not in window.store.path.read_bytes()
    assert window.store.get('catchall_domain') == 'applications.example.test'
    view.check_credential()
    assert 'company_intern@applications.example.test' in view.notice.text() and login['password'] not in view.notice.text()


def test_service_account_token_goes_to_the_keychain_and_old_keychain_logins_import(window):
    view, vault = window.profile_view, window.store._vault()
    view.token.setText('ops_secret')
    view.save_token()
    assert vault.get('op-service-account-token') == 'ops_secret' and view.token.text() == ''
    assert b'ops_secret' not in window.store.path.read_bytes() and 'saved' in view.token_status.text()
    url = 'https://legacy.wd1.myworkdayjobs.com/job/R1'
    window.store.save_run(ApplicationRun(job_url=url))
    vault.set('workday:legacy.wd1.myworkdayjobs.com', '{"username": "u", "password": "OldSecret1", "state": "verified"}')
    view.import_keychain_logins()
    assert vault.credential(url) == {'username': 'u', 'password': 'OldSecret1', 'state': 'verified'}
    view.import_keychain_logins()  # Running it again never duplicates.
    assert 'already there' in view.notice.text()

def test_logins_are_not_invented_unless_auto_create_is_enabled(window, monkeypatch):
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    run = ApplicationRun(job_url='https://acme.wd1.myworkdayjobs.com/job/R1', profile_snapshot=ApplicantProfile(email='me@example.test'))
    view.add_task(run)
    view._start_task(run)
    assert started[-1][2] is None and not window.store._vault().credential(run.job_url)


def test_account_lookup_is_deferred_and_verification_does_not_mark_the_vault_verified(window, monkeypatch):
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
    assert started[-1][2] is None and not vault.credential(url)
    assert window.store.get('auto_create_accounts') is True
    view._active_id = None

    # The engine handed off for email verification.
    vault.save_credential(url, 'ben-acme@apps.example.test', 'Fixture1!', 'pending_verification')
    run.status, run.authentication_attempted = 'needs_input', True
    run.interventions = [InterventionRequest(kind='activation', message='Verify')]
    notifications = []
    monkeypatch.setattr(tasks_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(tasks_module.subprocess, 'Popen', lambda args, **kwargs: notifications.append(args))
    view.on_finished(run)
    assert view.status_label(run) == 'Waiting for email verification'
    assert len(notifications) == 1 and notifications[0][-1].startswith('acme.wd1.myworkdayjobs.com:')
    view.render(select_id=run.id)
    assert view.start_btn.text() == "Continue after verification"

    view.start_btn.click()
    assert started[-1][2] is None and vault.credential(url)['state'] == 'pending_verification'
    assert window.store.get_run(run.id).verification_continued


def test_duplicate_vault_login_selection_only_saves_the_item_reference(window, monkeypatch):
    from core.automation.models import account_context
    run = ApplicationRun(job_url=URL, account=account_context(URL), status='needs_input',
                         interventions=[InterventionRequest(kind='verification', message='Choose login', field_key='1password-item', options=['[first] Personal', '[second] Internship'])])
    window.store.save_run(run)
    monkeypatch.setattr(tasks_module.QInputDialog, 'getItem', lambda *a: ('[second] Internship', True))
    started = capture_starts(window.tasks_view, monkeypatch)
    window.tasks_view._start_task(run)
    assert started[-1][0].account.item_id == 'second' and started[-1][2] is None
    assert window.store.get_run(run.id).account.item_id == 'second'


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
    assert run.browser == 'chromium' and not run.approved_review and not run.auto_advance
    assert run.profile_name == 'Engineering' and run.profile_snapshot.skills == 'Python'


def test_request_mode_is_chosen_per_application_for_workday_only(window):
    dialog = TaskDialog(window.tasks_view)
    dialog.url.setText('https://jobs.lever.co/example/1')
    dialog.mode.setCurrentIndex(dialog.mode.findData('request'))
    dialog.validate()
    assert 'Workday' in dialog.error.text() and dialog.result() != QDialog.Accepted
    dialog.url.setText('https://example.wd1.myworkdayjobs.com/en-US/Careers/job/Singapore/Intern_R123')
    dialog.validate()
    assert dialog.result() == QDialog.Accepted and dialog.application().mode == 'request'


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


def test_a_local_server_is_the_default_and_cloud_providers_never_get_values_unless_allowed(window):
    settings, store = window.settings_view, window.store
    settings.categories.setCurrentIndex(1)  # Open AI assistance.
    assert settings.provider.currentData() == 'compatible' and settings.ai_url.text() == 'http://localhost:1234/v1'
    assert not settings.ai_facts.isVisibleTo(settings) and 'On this Mac' in settings.ai_privacy.text()
    settings.ai_url.setText('http://example.com/v1')
    settings.save_url()
    assert store.get('compatible_url') is None  # Plain http is refused off this Mac.
    for provider in ('anthropic', 'deepseek'):
        settings.provider.setCurrentIndex(settings.provider.findData(provider))
        assert not settings.ai_form.isRowVisible(settings.ai_url) and settings.ai_facts.isVisibleTo(settings)
        assert not settings.ai_facts.isChecked() and 'never their values' in settings.ai_privacy.text()
    assert 'China' in settings.ai_privacy.text()
    settings.ai_facts.setChecked(True)
    assert store.get('deepseek_facts') is True and not store.get('anthropic_facts')
    assert settings.ai_model.text() == 'deepseek-flash'


def test_an_ai_answer_is_confirmed_under_answers(window):
    window.store.save_answer(ApprovedAnswer(question='Graduation year', fact='education.0.end_date.year', scope='global', origin='ai'))
    bank = window.answers_view
    bank.refresh()
    item = bank.tree.topLevelItem(0)
    assert item.text(1) == 'AI · unconfirmed · Profile: education #1 end or expected graduation date (year)'
    bank.tree.setCurrentItem(item)
    assert bank.confirm_btn.isEnabled()
    bank.confirm()
    assert window.store.answers()[0].origin == 'you' and not bank.confirm_btn.isVisibleTo(bank)


@pytest.mark.browser
def test_desktop_workflow_pauses_asks_and_reaches_review_without_submitting(window, tmp_path, monkeypatch):
    from playwright.async_api import Page
    app = QApplication.instance()
    url = 'https://boards.greenhouse.io/fixture/jobs/GUI_R1'
    fixture = (FIXTURES / 'greenhouse.html').read_text().replace('</form>',
        '<label>Available for this internship?<input type="checkbox" aria-required="true"></label><button type="button" id="submit_app" onclick="window.submissions++">Submit Application</button></form><script>window.submissions=0</script>')
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
    monkeypatch.setattr(service_module.ApplicationEngine, 'RECEIPT_POLLS', 4)
    notifications = []
    monkeypatch.setattr(tasks_module, 'desktop_notification', lambda *args: notifications.append(args))
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
    assert not run.approved_review
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
            card, = dialog.cards
            assert card.question == 'Available for this internship?'
            card.choice.setCurrentIndex(card.choice.findText('No'))
            click('Save answers && continue', dialog)  # The only open question: saving it carries on.
        except Exception as error:
            errors.append(error)
            if app.activeModalWidget():
                app.activeModalWidget().reject()
    QTimer.singleShot(50, approve)
    click('Answer questions')
    assert not errors, errors
    assert window.store.answers()[0].value is False
    wait_for(lambda: not view.service.busy and view._active_id is None)
    final = view.tasks[0]
    assert final.status == 'ready_for_review', final.interventions
    assert all(f.disposition == 'verified' for f in final.fields.values())
    assert window.store.get_run(run.id).status == 'ready_for_review'
    assert view.table.item(0, 3).text() == 'Ready to approve'
    async def inspect_browser():
        manager, adapter = view.service.sessions[run.id]
        assert any(c['name'] == 'gui_session' and c['value'] == 'fixture-only' for c in await manager.context.cookies(url))
        assert await adapter.page.evaluate('window.submissions') == 0
        assert await adapter.page.locator('#first_name').input_value() == 'Ada'
        assert not await adapter.page.locator('input[type=checkbox]').is_checked()
    asyncio.run_coroutine_threadsafe(inspect_browser(), view.service.loop).result(timeout=10)
    assert requests == [url]
    view.select_all_visible.click()
    with monkeypatch.context() as confirm:
        confirm.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
        click('Restart from beginning (1)…')
    wait_for(lambda: not view.service.busy and view._active_id is None)
    final = view.tasks[0]
    assert requests == [url, url] and final.status == 'ready_for_review'
    asyncio.run_coroutine_threadsafe(inspect_browser(), view.service.loop).result(timeout=10)
    assert not final.submission_attempted
    assert final.browser == 'chromium' and (legacy / 'preserve.txt').read_text() == 'Old browser session must remain intact'
    assert any(event['kind'] == 'browser_migration' for event in window.store.events(run.id))
    assert notifications[-1][0] == 'Ready to approve' and not any('Paused' in text for _, text in notifications)

    # Approve & send from the board: one click, one send, and an unrecognized receipt never sends again.
    def approve_review():
        try:
            dialog = app.activeModalWidget()
            assert dialog.windowTitle() == 'Review application — Fixture'
            QTest.mouseClick(dialog.send_btn, Qt.LeftButton)
        except Exception as error:
            errors.append(error)
            if app.activeModalWidget():
                app.activeModalWidget().reject()
    QTimer.singleShot(50, approve_review)
    click('Review application')
    assert not errors, errors
    wait_for(lambda: not view.service.busy and view._active_id is None)
    sent = view.tasks[0]
    assert sent.submission_attempted and not sent.submission_confirmed, sent.interventions
    assert view.table.item(0, 3).text() == 'Sent · receipt unconfirmed'
    click('Check receipt')
    wait_for(lambda: not view.service.busy and view._active_id is None)
    async def submissions():
        return await view.service.sessions[run.id][1].page.evaluate('window.submissions')
    assert asyncio.run_coroutine_threadsafe(submissions(), view.service.loop).result(timeout=10) == 1


def test_a_pasted_link_starts_that_job_even_when_a_filter_hides_it(window, monkeypatch):
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    view.add_task(ApplicationRun(company='Other', job_url='https://jobs.lever.co/other/1', status='needs_input'))
    view.search.setText('Other')
    view.chips.button(1).click()  # Needs you
    view.paste.setText('https://jobs.lever.co/acme/2')
    QTest.keyClick(view.paste, Qt.Key_Return)
    assert [run.job_url for run, *_ in started] == ['https://jobs.lever.co/acme/2']
    assert view.selected().job_url == 'https://jobs.lever.co/acme/2' and not view.paste.text()


def test_link_only_jobs_are_not_duplicates_but_the_same_listing_opens_the_existing_run(window, monkeypatch):
    view = window.tasks_view
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: pytest.fail('Missing metadata must not look like a duplicate'))
    assert view.add_task(ApplicationRun(job_url='https://jobs.lever.co/a/1'))
    assert view.add_task(ApplicationRun(job_url='https://jobs.lever.co/b/2', listing_url='https://careers.b.test/jobs/2'))
    assert not view.add_task(ApplicationRun(job_url='https://careers.b.test/jobs/2'))
    assert len(view.tasks) == 2 and view.selected().job_url == 'https://jobs.lever.co/b/2'


def ready_run(**kwargs):
    from core.automation.models import FieldAssessment
    fields = {
        's:first': FieldAssessment(key='s:first', label='First Name', section='s', disposition='verified', answer_ref='profile:first_name', value='Ada'),
        's:yes': FieldAssessment(key='s:yes', label='Eligible?', section='s', kind='radio', disposition='verified', answer_ref='answer:x', value=True, option='Yes'),
        's:no': FieldAssessment(key='s:no', label='Eligible?', section='s', kind='radio', disposition='verified', answer_ref='answer:x', value=False, option='No'),
        's:year': FieldAssessment(key='s:year', label='Graduation year', section='s', disposition='verified', answer_ref='answer:ai', value='2027'),
        's:terms': FieldAssessment(key='s:terms', label='I agree to the privacy notice', section='s', kind='checkbox', disposition='verified', answer_ref='answer:x', value=True),
        's:cv': FieldAssessment(key='s:cv', label='Resume', section='s', kind='file', disposition='verified', answer_ref='profile:resume_path', value='resume.pdf'),
    }
    return ApplicationRun(company='Acme', role='Data Intern', job_url='https://jobs.lever.co/acme/1', status='ready_for_review',
                          fields=fields, completed_sections=['s'], documents_digest='d1', profile_snapshot=ApplicantProfile(), **kwargs)


def test_review_shows_the_filled_values_and_approve_sends_exactly_that(window, monkeypatch):
    from gui.views.application_dialogs import ReviewDialog
    from core.automation.review import review_values
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    window.store.save_answer(ApprovedAnswer(id='ai', question='Graduation year', value='2027', origin='ai', scope='global'))
    run = ready_run()
    view.add_task(run)
    assert view.status_label(run) == 'Ready to approve' and view.review_btn.isVisibleTo(view)
    assert view.recheck_btn.isHidden() and view.secondary_actions[view.recheck_btn].isVisible()
    dialog = ReviewDialog(window.store, run)
    tree = dialog.findChild(QTreeWidget)
    first = tree.topLevelItem(0)
    assert first.text(0) == 'Check these first'
    assert {first.child(i).text(0) for i in range(first.childCount())} == {'Graduation year', 'I agree to the privacy notice'}
    page = tree.topLevelItem(1)
    assert [(page.child(i).text(0), page.child(i).text(1)) for i in range(page.childCount())] == [('First Name', 'Ada'), ('Eligible?', 'Yes'), ('Resume', 'resume.pdf')]
    assert dialog.ai_ids == {'ai'}
    view.approve_and_send(run, dialog.ai_ids)
    assert started[-1][0].approved_review == review_values(run) and window.store.answers()[0].origin == 'you'
    assert window.store.get_run(run.id).approved_review == review_values(run)


def test_review_stays_readable_while_another_job_runs_but_send_waits(window, monkeypatch):
    from gui.views.application_dialogs import ReviewDialog
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    run = ready_run()
    view.add_task(run)
    view._active_id = 'another'
    view.render(select_id=run.id)
    assert view.review_btn.isEnabled() and not view.recheck_btn.isEnabled()
    assert not ReviewDialog(window.store, run, can_send=False).send_btn.isEnabled()
    assert ReviewDialog(window.store, run).send_btn.isEnabled()
    run.fields['s:first'].value = ''  # Verified by a version that didn't record values.
    assert not ReviewDialog(window.store, run).send_btn.isEnabled()
    view.approve_and_send(run)
    assert started == [] and not window.store.get_run(run.id).approved_review


def test_an_unconfirmed_send_offers_receipt_checks_never_a_second_send(window, monkeypatch):
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    run = ready_run(submission_attempted=True)
    run.status = 'needs_input'
    view.add_task(run)
    assert view.status_label(run) == 'Sent · receipt unconfirmed'
    assert view.start_btn.text() == 'Check receipt' and view.submitted_btn.text() == 'Record employer confirmation'
    assert not view.review_btn.isVisibleTo(view) and not view.recheck_btn.isVisibleTo(view)
    run.status = 'ready_for_review'  # Even a run left in review never offers Send again.
    view.render(select_id=run.id)
    assert not view.review_btn.isVisibleTo(view) and view.start_btn.text() == 'Check receipt'
    view.approve_and_send(run)
    assert started == [] and not run.approved_review


def test_replace_link_offers_the_listings_applications_and_restarts_on_the_choice(window, monkeypatch):
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    run = ApplicationRun(job_url='https://careers.acme.test/jobs/1', status='needs_input', interventions=[
        InterventionRequest(kind='link', message='More than one', options=['https://jobs.lever.co/acme/1', 'https://jobs.lever.co/acme/2'])])
    view.add_task(run)
    assert view.replace_btn.isVisibleTo(view)
    offered = []
    monkeypatch.setattr(tasks_module.QInputDialog, 'getItem', lambda parent, title, text, items, *args: offered.append(items) or (items[1], True))
    view.replace_link()
    assert offered == [['https://jobs.lever.co/acme/1', 'https://jobs.lever.co/acme/2']]
    saved = window.store.get_run(run.id)
    assert (saved.job_url, saved.listing_url, saved.stage) == ('https://jobs.lever.co/acme/2', 'https://careers.acme.test/jobs/1', 'start')
    assert started[-1][0].job_url == 'https://jobs.lever.co/acme/2'


def test_answers_default_to_this_job_except_stable_facts_and_declarations_are_locked(window):
    run = ApplicationRun(company='Example', job_url=URL, profile_snapshot=ApplicantProfile(), status='needs_input', interventions=[
        InterventionRequest(kind='answer', message='The form needs an answer.', question='Expected salary', required=True),
        InterventionRequest(kind='answer', message='', question='Will you require visa sponsorship?', required=True),
        InterventionRequest(kind='answer', message='', question='I certify the information above is true', required=True, field_kind='checkbox')])
    details = RunDetailsDialog(window.store, run)
    salary, sponsorship, declaration = details.cards
    assert salary.scope() == 'application' and sponsorship.scope() == 'global'
    assert declaration.scope() == 'application' and declaration.scope_row.isHidden()
    assert details.save_btn.text() == 'Save answers'
    salary.text.setPlainText('Negotiable')
    details.save_answers()
    assert details.result() != QDialog.Accepted and '2 required questions still need an answer' in details.notice.text()
    sponsorship.text.setPlainText('No')
    declaration.choice.setCurrentIndex(declaration.choice.findText('Yes'))
    assert details.save_btn.text() == 'Save answers && continue'
    details.save_answers()
    assert details.result() == QDialog.Accepted  # Saving the last required answer continues the application; no separate Resume.
    scopes = {a.question: (a.scope, a.scope_key) for a in window.store.answers()}
    assert scopes == {'Expected salary': ('application', run.id), 'Will you require visa sponsorship?': ('global', ''),
                      'I certify the information above is true': ('application', run.id)}
    assert window.store.answers()[-1].value is True


def test_an_unsupported_site_offers_teaching_and_a_draft_recipe_offers_review(window):
    from core.automation.models import InterventionRequest
    from core.automation.recipes import Recipe, save_recipe
    view = window.tasks_view
    run = ApplicationRun(job_url='https://careers.niche.test/apply/1', status='needs_input',
                         interventions=[InterventionRequest(kind='browser', message='No supported application form was detected. Open the application form or continue manually.')])
    view.add_task(run)
    view.render(select_id=run.id)
    assert not view.teach_btn.isHidden() and view.self_teach_btn.isHidden()
    assert view.secondary_actions[view.self_teach_btn].isVisible()
    assert view.recipe_btn.isHidden() and view.finish_teach_btn.isHidden()
    save_recipe(window.store, Recipe(host='careers.niche.test', origin='ai'))
    view.render(select_id=run.id)
    assert not view.recipe_btn.isHidden() and view.secondary_actions[view.submitted_btn].isVisible()


@pytest.mark.parametrize('size', [(1040, 660), (1280, 780)])
@pytest.mark.parametrize('state', ['ready', 'questions'])
def test_board_fits_supported_windows_and_keeps_secondary_actions_available(window, size, state):
    from PySide6.QtWidgets import QScrollArea
    view = window.tasks_view
    run = ready_run() if state == 'ready' else ApplicationRun(job_url=URL, status='needs_input',
        interventions=[InterventionRequest(kind='answer', question='When are you available?', message='Confirm your availability.')])
    view.add_task(run)
    window.resize(*size)
    window.show()
    QApplication.processEvents()
    view.render(select_id=run.id)
    QApplication.processEvents()
    visible_actions = [b for b in view.action_buttons if b.isVisibleTo(view)]
    assert len(visible_actions) == 1
    scroll = view.detail_body.parentWidget().parentWidget().parentWidget()
    assert isinstance(scroll, QScrollArea)
    assert scroll.widget().width() <= scroll.viewport().width()
    assert view.d_status.width() > 100
    total = sum(view.table.columnWidth(i) for i in range(view.table.columnCount()) if not view.table.isColumnHidden(i))
    assert total <= view.table.viewport().width() + 2
    assert not view.table.isColumnHidden(3)
    assert view.secondary_actions[view.recheck_btn if state=='ready' else view.start_btn].isVisible()
    assert not view.tracking.isVisibleTo(view)
    view.tracking_toggle.click()
    assert view.notes.isVisibleTo(view)


def test_review_wraps_complete_answers_and_keeps_section_names(window):
    from gui.views.application_dialogs import ReviewDialog
    from core.automation.models import FieldAssessment
    run = ready_run()
    paragraph = 'I want to build dependable tools that make complex information clear and usable. ' * 6
    run.fields = {'answer': FieldAssessment(key='answer', label='Career aspirations', section='Application questions',
                    disposition='verified', value=paragraph, answer_ref='answer:approved')}
    run.completed_sections = ['Application questions']
    dialog = ReviewDialog(window.store, run)
    dialog.show()
    QApplication.processEvents()
    tree = dialog.findChild(QTreeWidget)
    section = tree.topLevelItem(1)
    assert section.text(0) == 'Application questions'
    item = section.child(0)
    assert item.text(1) == paragraph
    assert tree.textElideMode() == Qt.ElideNone
    assert tree.visualItemRect(item).height() > tree.fontMetrics().height() * 4
    assert dialog.send_btn.isEnabled()
    dialog.close()


def test_answering_exposes_the_full_question_and_discloses_options_and_reports(window):
    question = 'Describe the dates you are available, including your earliest starting date and latest ending date.'
    run = ApplicationRun(job_url=URL, status='needs_input', interventions=[InterventionRequest(kind='answer', question=question, required=True, message='This question needs your answer.')])
    dialog = RunDetailsDialog(window.store, run)
    dialog.show()
    QApplication.processEvents()
    card = dialog.cards[0]
    title = next(l for l in card.findChildren(QLabel) if l.text() == question)
    assert title.isVisible() and card.scope_row.isVisible() and not dialog.report_tabs.isVisible()
    assert 'Required · This question needs your answer.' in [l.text() for l in card.findChildren(QLabel)]
    assert card.blank is None  # A required question can't be left blank.
    dialog.report_toggle.click()
    assert dialog.report_tabs.isVisible()
    dialog.close()


def test_secondary_recheck_action_still_rechecks_the_selected_application(window, monkeypatch):
    view = window.tasks_view
    started = capture_starts(view, monkeypatch)
    run = ready_run()
    view.add_task(run)
    view.secondary_actions[view.recheck_btn].trigger()
    assert started[-1][0].id == run.id and not started[-1][0].approved_review


def test_no_search_results_has_a_working_recovery_action(window):
    view = window.tasks_view
    view.add_task(ready_run())
    view.search.setText('no such company')
    assert view.table.rowCount() == 0 and view.table_stack.currentIndex() == 1
    clear = next(b for b in view.table_stack.findChildren(QPushButton) if b.text()=='Show all applications')
    clear.click()
    assert view.search.text() == '' and view.table_stack.currentIndex() == 0 and view.table.rowCount() == 1


def test_approved_omissions_complete_progress_and_uncertain_sends_request_confirmation(window):
    from core.automation.models import FieldAssessment
    view = window.tasks_view
    run = ready_run()
    run.fields['optional'] = FieldAssessment(key='optional', label='Middle name', section='s', disposition='intentionally_omitted')
    view.add_task(run)
    assert view.d_bar.value() == view.d_bar.maximum()
    run.submission_attempted = True
    view.render(select_id=run.id)
    assert view.d_stage.text() == 'Check employer confirmation'


def test_bulk_selection_tracks_ids_and_only_acts_on_eligible_tasks(window, monkeypatch):
    view = window.tasks_view
    failed, second, active, ready, sent = runs = [ready_run() for _ in range(5)]
    for run, name, status in zip(runs, ['A', 'B', 'C', 'D', 'E'],
                                 ['failed', 'failed', 'running', 'ready_for_review', 'failed']):
        run.company, run.status = name, status
        run.stage = 'skills'
        window.store.save_run(run)
    sent.submission_attempted = True
    failed.approved_review = {'old': 'approval'}
    view.tasks, view._active_id = runs, active.id
    view.render()
    window.resize(1040, 660)
    window.show()
    QApplication.processEvents()
    view.select_all_visible.click()
    assert view.selection_count.text() == '5 selected'
    assert [b.text() for b in view.bulk_buttons.values()] == [
        'Retry failed (2)', 'Restart from beginning (3)…', 'Cancel tasks (1)', 'Delete tasks (4)…']
    assert window.width() == 1040
    view.table.sortByColumn(1, Qt.AscendingOrder)
    view.render()
    view.table.setCurrentCell(0, 0)
    QTest.keyClick(view.table, Qt.Key_Space)
    assert view._checked_ids == {r.id for r in runs if r != failed}
    assert view.select_all_visible.checkState() == Qt.PartiallyChecked
    QTest.keyClick(view.table, Qt.Key_Space)
    # One failure is already waiting in the queue.
    view._queue = [second.id]
    view.bulk_buttons['retry'].click()
    assert view._queue == [second.id, failed.id]
    assert view._checked_ids == {active.id, ready.id, sent.id}
    assert failed.fields and failed.stage == 'skills' and not failed.approved_review

    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    view.bulk_buttons['restart'].click()
    assert ready.fields and ready.status == 'ready_for_review'
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.No)
    view.bulk_buttons['delete'].click()
    assert len(view.tasks) == 5 and view.selection_count.text() == '3 selected'
    view.search.setText('unmatched company')
    assert not view._checked_ids and view.bulk_bar.isHidden()
    view.search.clear()
    assert not view._checked_ids


def test_bulk_restart_cancel_and_delete_preserve_other_work(window, monkeypatch):
    view = window.tasks_view
    ready = ready_run(notes='Follow up', approved_review={'old': 'approval'})
    active = ApplicationRun(job_url=URL, company='Running', status='running')
    waiting = ApplicationRun(job_url=URL, company='Waiting')
    verify = ApplicationRun(job_url=URL, company='Verification', status='needs_input',
                            interventions=[InterventionRequest(kind='activation', message='Verify')])
    view.tasks = [ready, active, waiting, verify]
    for run in view.tasks:
        window.store.save_run(run)
    window.store.record_event(ready.id, 'old', 'first step')
    view._queue, view._active_id = [waiting.id], active.id
    view.render()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    view.search.setText('Acme')
    view.select_all_visible.click()
    view.bulk_buttons['restart'].click()
    reset = window.store.get_run(ready.id)
    assert reset.status == 'queued' and reset.stage == 'start' and not reset.fields
    assert not reset.approved_review and not reset.completed_sections and reset.step == -1
    assert reset.notes == 'Follow up' and reset.profile_snapshot == ready.profile_snapshot
    assert [e['kind'] for e in window.store.events(ready.id)] == ['old', 'restart']
    assert view._queue == [waiting.id, ready.id]
    view.search.setText('Running')
    view.select_all_visible.click()
    stops = []
    monkeypatch.setattr(view.service, 'pause', lambda rid, cancel: stops.append((rid, cancel)))
    view.bulk_buttons['cancel'].click()
    assert stops == [(active.id, True)] and view._queue == [waiting.id, ready.id]
    view.search.setText('Verification')
    view.select_all_visible.click()
    assert not view.bulk_buttons['restart'].isEnabled()
    view.search.setText('Acme')
    view.select_all_visible.click()
    view.bulk_buttons['cancel'].click()
    assert ready.status == 'cancelled' and view._queue == [waiting.id]
    view.select_all_visible.click()
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Yes)
    view.bulk_buttons['delete'].click()
    assert window.store.get_run(ready.id) is None and not window.store.events(ready.id)
    assert view._queue == [waiting.id] and view._run(active.id) == active


@pytest.mark.parametrize('status, expected_navigation', [('failed', False), ('queued', True)])
async def test_retry_and_restart_in_an_existing_tab(window, monkeypatch, status, expected_navigation):
    from unittest.mock import AsyncMock, Mock
    from core.automation.engine import ApplicationEngine

    service = window.tasks_view.service
    run = ApplicationRun(job_url=URL, status=status)
    page = Mock(url=URL + '/later-step', is_closed=Mock(return_value=False), bring_to_front=AsyncMock())
    service.sessions[run.id] = (Mock(stop=AsyncMock()), Mock(page=page))
    open_job = AsyncMock(return_value=('', []))
    monkeypatch.setattr(service, 'open_job', open_job)
    prepare = AsyncMock()
    monkeypatch.setattr(ApplicationEngine, 'start', prepare)
    await service._run(run, ApplicantProfile(), None)
    assert open_job.await_count == int(expected_navigation)
    prepare.assert_awaited_once()


async def test_cancel_and_delete_close_the_runs_browser(window, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, Mock
    from core.automation.engine import ApplicationEngine

    service, view = window.tasks_view.service, window.tasks_view
    def session(run):
        page = Mock(url=URL, is_closed=Mock(return_value=False), bring_to_front=AsyncMock())
        manager = Mock(stop=AsyncMock())
        service.sessions[run.id] = (manager, Mock(page=page))
        return manager
    # Cancelled while running: the engine stops and the window closes with it.
    running = ApplicationRun(job_url=URL, status='queued')
    manager = session(running)
    async def cancelled(self, run, *args):
        run.status = 'cancelled'
    monkeypatch.setattr(ApplicationEngine, 'start', cancelled)
    monkeypatch.setattr(service, 'open_job', AsyncMock(return_value=('', [])))
    await service._run(running, ApplicantProfile(), None)
    manager.stop.assert_awaited_once()
    assert running.id not in service.sessions
    # Cancelled or deleted while waiting on you.
    for action in ('cancel', 'delete'):
        run = ApplicationRun(job_url=URL, status='needs_input')
        window.store.save_run(run)
        view.load_state()
        manager = session(run)
        if action == 'cancel':
            view.cancel_run(run)
        else:
            monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.Yes)
            view.delete_runs([run])
        for _ in range(50):
            if manager.stop.await_count:
                break
            await asyncio.sleep(.02)
        manager.stop.assert_awaited_once()
        assert run.id not in service.sessions


def test_signing_in_again_shows_over_the_sites_step_list():
    # An expired Workday session signs in again with the step list from the earlier run still on the task.
    run = ApplicationRun(job_url=URL, steps=['My Information', 'Review'], step=0, stage='Signing in')
    assert stage_text(run) == 'Signing in'
    run.stage = 'workday:abc123'
    assert stage_text(run) == 'My Information · step 1 of 2'
