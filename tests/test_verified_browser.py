import asyncio
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from core.automation.engine import ApplicationEngine
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, Education, Experience
from core.automation.workday import WorkdayAdapter
from core.automation.privacy import BoundedRecovery
from core.storage.local_store import LocalStore

FIXTURE = Path(__file__).parent / 'fixtures' / 'workday.html'
URL = 'https://example.wd1.myworkdayjobs.com/job/Intern_R1'


async def with_page(tmp_path, scenario):
    async with async_playwright() as pw:
        name = os.environ.get('INTERN_BOT_TEST_ENGINE', 'chromium')
        engine = pw.firefox if name == 'firefox' else pw.chromium
        browser = await engine.launch(headless=True, timeout=30000, executable_path=os.environ.get('INTERN_BOT_TEST_BROWSER'),
                                      **({'channel': 'chrome'} if name == 'chrome' else {}))
        try:
            context = await browser.new_context()
            requests = []
            async def deny(route):
                requests.append(route.request.url)
                await route.abort()
            await context.route('**/*', deny)
            page = await context.new_page()
            store = LocalStore(tmp_path / 'state.db')
            await scenario(page, store)
            assert requests == [], 'The synthetic test unexpectedly attempted network access'
        finally:
            await browser.close()


def test_complete_application_dynamic_fields_rows_and_review(tmp_path):
    async def scenario(page, store):
        resume = tmp_path / 'resume.pdf'
        resume.write_bytes(b'%PDF-1.4\nfictional fixture\n%%EOF')
        profile = ApplicantProfile(first_name='Ada', last_name='Example', country='Singapore', resume_path=str(resume),
             education=[Education(school='Example University', degree='BSc'), Education(school='Second University', degree='MSc')],
             experience=[Experience(employer='Example Co', job_title='Intern'), Experience(employer='Other Co', job_title='Developer')])
        run = ApplicationRun(job_url=URL)
        store.save_answer(ApprovedAnswer(question='Available for this internship?', value=True, scope_key=run.id))
        store.save_answer(ApprovedAnswer(question='Start Date', value='2027-01-01', scope_key=run.id))
        await page.set_content(FIXTURE.read_text())
        await ApplicationEngine(store).start(run, profile, WorkdayAdapter(page, URL, True))
        assert run.status == 'ready_for_review', run.interventions
        assert len(run.completed_sections) == 4
        assert all(a.disposition == 'verified' for a in run.fields.values())
        assert await page.evaluate('window.submissions') == 0
        assert len([a for a in run.fields.values() if a.label == 'Company']) == 2
        assert store.get_run(run.id).status == 'ready_for_review'
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_utility_language_selector_does_not_block_application(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<div data-automation-id="utilityButtonBar">
          <button id="languageSelectorButton" aria-haspopup="listbox" data-automation-id="utilityMenuButton">English</button></div>
          <h1>Data Engineering Intern</h1><main><button onclick="this.parentElement.innerHTML='<h2>Sign In</h2><label>Email<input type=email></label><label>Password<input type=password></label><button>Sign In</button>'">Apply</button></main>''')
        run = ApplicationRun(job_url=URL)
        adapter = WorkdayAdapter(page, URL, True)
        assert await adapter.scan() == []
        await ApplicationEngine(store).start(run, ApplicantProfile(), adapter)
        assert run.status == 'needs_input' and run.stage == 'sign_in'
        assert not run.authentication_attempted and not run.submission_attempted
        assert all(f.label != 'utilityMenuButton' for f in await adapter.scan())
        await page.set_content('<h2>My Information</h2><button aria-haspopup="listbox" aria-label="Country">Select One</button>')
        fields = await adapter.scan()
        assert len(fields) == 1 and fields[0].label == 'Country'
    asyncio.run(with_page(tmp_path, scenario))


def test_navigation_completed_during_scan_rechecks_stage(tmp_path):
    from core.automation.workday import FormField
    class TransitioningAdapter:
        settled = False
        async def stage(self):
            return 'verification' if self.settled else 'start'
        async def scan(self):
            self.settled = True
            return [FormField('code', 'Verification code', '', 'text')]
    run = ApplicationRun(job_url=URL)
    asyncio.run(ApplicationEngine(LocalStore(tmp_path / 'state.db')).start(run, ApplicantProfile(), TransitioningAdapter()))
    assert run.status == 'needs_input' and run.stage == 'verification'
    assert run.interventions[0].kind == 'verification'


def test_workday_active_step_and_listbox_labels_are_stable(tmp_path):
    from core.automation.answers import resolve
    async def scenario(page, store):
        await page.set_content('''<h2>Engineering Intern</h2><ol>
          <li data-automation-id="progressBarActiveStep">current step 1 of 6 Autofill with Resume</li>
          <li data-automation-id="progressBarInactiveStep">My Information</li></ol>
          <label for="country">Country*</label>
          <button id="country" aria-haspopup="listbox" aria-label="Country Singapore Required">Singapore</button>''')
        adapter = WorkdayAdapter(page, URL, True)
        assert await adapter.stage() == 'resume'
        field, = await adapter.scan()
        assert field.label == 'Country' and field.required and field.value == 'Singapore'
        assert resolve(field, ApplicantProfile(country='Singapore'), ApplicationRun(job_url=URL), []).value == 'Singapore'
        await page.locator('#country').evaluate('e => {e.textContent="Malaysia";e.setAttribute("aria-label","Country Malaysia Required")}')
        changed, = await adapter.scan()
        assert changed.key == field.key and changed.value == 'Malaysia'
        await page.locator('[data-automation-id=progressBarActiveStep]').evaluate('e => e.textContent="My Information"')
        assert await adapter.stage() == 'information'
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_phone_prompt_reads_selected_value_and_splits_number(tmp_path):
    from core.automation.answers import resolve
    async def scenario(page, store):
        await page.set_content('''<label for="phoneNumber--countryPhoneCode">Country Phone Code*</label>
          <div data-automation-id="multiselectInputContainer">
            <input id="phoneNumber--countryPhoneCode" data-uxi-widget-type="selectinput">
            <ul role="listbox"><li data-automation-id="selectedItem"><p data-automation-id="promptOption">Singapore (+65)</p></li></ul>
          </div><label for="phoneNumber--phoneNumber">Phone Number*</label><input id="phoneNumber--phoneNumber">
          <label>Given Name(s) - Western Script<input></label><label>Family Name - Western Script<input></label>''')
        adapter = WorkdayAdapter(page, URL, True)
        fields = await adapter.scan()
        profile = ApplicantProfile(first_name='Ada', last_name='Example', phone='+65 8123 4567', country='Singapore')
        run = ApplicationRun(job_url=URL)
        assert fields[0].kind == 'combobox' and fields[0].value == 'Singapore (+65)'
        assert [resolve(f, profile, run, []).value for f in fields] == ['Singapore (+65)', '81234567', 'Ada', 'Example']
        assert await ApplicationEngine(store).complete_section(run, profile, adapter)
        assert await page.locator('[id="phoneNumber--phoneNumber"]').input_value() == '81234567'
        profile.phone = '+6581234567'
        assert resolve(fields[1], profile, run, []).value is None
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_accessible_rows_and_required_date_parts(tmp_path):
    from core.automation.answers import resolve
    async def scenario(page, store):
        await page.set_content('''<div role="group" aria-labelledby="Work-Experience-section">
          <div role="group" aria-labelledby="Work-Experience-1-panel"><label>Company<input></label>
            <fieldset><legend>From*</legend><input role="spinbutton" aria-label="Month"></fieldset></div>
          <div role="group" aria-labelledby="Work-Experience-2-panel"><label>Company<input></label></div></div>
          <div role="group" aria-labelledby="Education-section"><div role="group" aria-labelledby="Education-1-panel">
            <fieldset><legend>To (Actual or Expected)*</legend><input role="spinbutton" aria-label="Year"></fieldset>
          </div></div>''')
        adapter = WorkdayAdapter(page, URL, True)
        assert await adapter.row_counts() == {'experience': 2, 'education': 1}
        fields = await adapter.scan()
        assert [(f.group, f.row, f.label) for f in fields] == [('experience',0,'Company'),('experience',0,'From Month'),('experience',1,'Company'),('education',0,'To Year')]
        profile = ApplicantProfile(experience=[Experience(employer='A',start_date='2026-05'), Experience(employer='B')], education=[Education(end_date='2029-05')])
        assert [resolve(f,profile,ApplicationRun(job_url=URL),[]).value for f in fields] == ['A','5','B','2029']
        assert fields[1].required and fields[3].required
        assert 'reconcile' in (await adapter.ensure_rows(ApplicantProfile(experience=[Experience()]))).lower()
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_rich_question_labels_do_not_collapse_to_generic_options(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<fieldset><legend>Year of Study*</legend>
          <button aria-haspopup="listbox" aria-label=" Select One Required">Select One</button></fieldset>
          <div data-automation-id="formField-question"><fieldset><legend>Question A*</legend>
          <fieldset data-automation-id="question-CheckboxGroup"><label>Yes<input type="checkbox"></label><label>No<input type="checkbox"></label></fieldset>
          </fieldset></div>''')
        fields = await WorkdayAdapter(page, URL, True).scan()
        assert [f.label for f in fields] == ['Year of Study', 'Question A* — Yes', 'Question A* — No']
        assert all(f.required for f in fields)
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_search_prompt_selects_exact_leaf(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<label for="major">Field of Study</label>
          <div data-automation-id="multiselectInputContainer"><input id="major" data-uxi-widget-type="selectinput"></div>
          <script>document.querySelector('input').onkeydown=e=>{
            if(e.key!=='Enter')return;
            const leaf=document.createElement('div');leaf.dataset.automationId='promptLeafNode';
            const value=e.target.value;leaf.textContent=value;
            leaf.onclick=()=>{const selected=document.createElement('div');selected.dataset.automationId='selectedItem';
              const label=document.createElement('p');label.dataset.automationId='promptOption';label.textContent=value;
              selected.append(label);e.target.parentElement.append(selected);leaf.remove();};
            document.body.append(leaf);
          };</script>''')
        adapter = WorkdayAdapter(page, URL, True)
        field, = await adapter.scan()
        assert await adapter.fill(field, 'Data Science (Data Analytics)')
        changed, = await adapter.scan()
        assert adapter.matches(changed, 'Data Science (Data Analytics)')
    asyncio.run(with_page(tmp_path, scenario))


def test_unrecognized_authentication_never_treats_credentials_as_answers(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<h1>Data Engineering Intern</h1><div>Create Account</div>
          <label>Email Address<input type="text" data-automation-id="email"></label>
          <label>Password<input type="password"></label><label>Verify New Password<input type="password"></label>
          <label>Terms acknowledgement<input type="checkbox"></label>
          <button>Create Account</button>''')
        run = ApplicationRun(job_url=URL)
        await ApplicationEngine(store).start(run, ApplicantProfile(email='sample@example.test'), WorkdayAdapter(page, URL, True))
        assert run.stage == 'authentication' and run.status == 'needs_input'
        assert len(run.interventions) == 1 and run.interventions[0].kind == 'verification'
        assert not run.fields and not run.authentication_attempted
        assert await page.locator('input[type=text]').input_value() == ''
        assert all(not i.question for i in run.interventions)
    asyncio.run(with_page(tmp_path, scenario))


def test_unknown_optional_and_conflicting_values_pause(tmp_path):
    async def scenario(page, store):
        await page.set_content('<h2>My Information</h2><label>First Name<input value="Wrong"></label><label>Unknown optional<input></label><button>Next</button>')
        run = ApplicationRun(job_url=URL)
        await ApplicationEngine(store).start(run, ApplicantProfile(first_name='Ada'), WorkdayAdapter(page, URL, True))
        assert run.status == 'needs_input'
        assert len(run.interventions) == 2
        assert await page.locator('input').first.input_value() == 'Wrong'
        assert any(i.kind == 'conflict' for i in run.interventions)
    asyncio.run(with_page(tmp_path, scenario))


def test_retry_exhaustion_for_reverting_value(tmp_path):
    async def scenario(page, store):
        await page.set_content('<h2>My Information</h2><label>First Name<input onblur="this.value=\'\';window.reverted=(window.reverted||0)+1"></label><button>Next</button>')
        run = ApplicationRun(job_url=URL)
        await ApplicationEngine(store).start(run, ApplicantProfile(first_name='Ada'), WorkdayAdapter(page, URL, True))
        assert run.status == 'needs_input'
        assert next(iter(run.fields.values())).disposition == 'blocked'
        assert await page.evaluate('window.reverted') == 3
    asyncio.run(with_page(tmp_path, scenario))


def test_resume_does_not_duplicate_rows(tmp_path):
    async def scenario(page, store):
        await page.set_content(FIXTURE.read_text())
        await page.evaluate('window.stage=2; render(); row("education"); row("experience")')
        await page.get_by_label('School', exact=True).fill('Example University')
        await page.get_by_label('Degree', exact=True).fill('BSc')
        await page.get_by_label('Company', exact=True).fill('Example Co')
        await page.get_by_label('Job Title', exact=True).fill('Intern')
        profile = ApplicantProfile(education=[Education(school='Example University', degree='BSc')], experience=[Experience(employer='Example Co', job_title='Intern')])
        run = ApplicationRun(job_url=URL)
        adapter = WorkdayAdapter(page, URL, True)
        engine = ApplicationEngine(store)
        await engine.start(run, profile, adapter)
        assert run.status == 'needs_input' and run.stage == 'questions'
        store.save_answer(ApprovedAnswer(question='Available for this internship?', value=False, scope_key=run.id))
        await engine.resume(store.get_run(run.id), profile, adapter)
        restored = store.get_run(run.id)
        assert restored.status == 'ready_for_review', restored.interventions
        assert len(await page.locator('[data-intern-review][data-label="Company"]').all()) == 1
    asyncio.run(with_page(tmp_path, scenario))


def test_missing_resume_never_claims_upload_success(tmp_path):
    async def scenario(page, store):
        await page.set_content(FIXTURE.read_text())
        run = ApplicationRun(job_url=URL)
        await ApplicationEngine(store).start(run, ApplicantProfile(resume_path=str(tmp_path/'missing.pdf')), WorkdayAdapter(page, URL, True))
        assert run.status == 'needs_input'
        assert run.stage == 'resume'
        assert next(iter(run.fields.values())).disposition == 'blocked'
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_unlabelled_resume_upload_uses_container_context(tmp_path):
    from core.automation.answers import resolve
    async def scenario(page, store):
        resume = tmp_path / 'resume.pdf'
        resume.write_bytes(b'%PDF-1.4\nfixture\n%%EOF')
        profile = ApplicantProfile(resume_path=str(resume))
        run = ApplicationRun(job_url=URL)
        await page.set_content('''<h2>Autofill with Resume</h2>
          <div data-automation-id="resumeUpload"><div>
            <input type="file" data-automation-id="file-upload-input-ref">
          </div></div><button>Continue</button>''')
        adapter = WorkdayAdapter(page, URL, True)
        assert await ApplicationEngine(store).complete_section(run, profile, adapter)
        field, = await adapter.scan()
        assert field.label == 'Resume' and adapter.matches(field, str(resume))
        await page.set_content('''<div data-automation-id="resumeUpload">
          <input type="file" aria-label="Cover Letter"></div>
          <input type="file" data-automation-id="file-upload-input-ref">''')
        cover, unknown = await adapter.scan()
        assert cover.label == 'Cover Letter'
        assert resolve(unknown, profile, run, []).value is None
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_replaced_upload_keeps_verified_receipt(tmp_path):
    async def scenario(page, store):
        resume = tmp_path / 'resume.pdf'
        resume.write_bytes(b'%PDF-1.4\nfixture\n%%EOF')
        profile = ApplicantProfile(resume_path=str(resume))
        run = ApplicationRun(job_url=URL)
        await page.set_content('''<div data-automation-id="resumeUpload"><input type="file"></div>
          <script>document.querySelector('input').onchange = e => {
            e.target.parentElement.innerHTML = '<div data-automation-id="file-upload-item">' +
              '<div data-automation-id="file-upload-item-name">resume.pdf</div>' +
              '<div data-automation-id="file-upload-successful">Successfully Uploaded!</div>' +
              '<div role="alert">resume.pdf successfully uploaded</div></div>';
          };</script>''')
        adapter = WorkdayAdapter(page, URL, True)
        assert await ApplicationEngine(store).complete_section(run, profile, adapter)
        field, = await adapter.scan()
        assert field.uploaded and adapter.matches(field, str(resume))
        assert len(run.fields) == 1 and next(iter(run.fields.values())).disposition == 'verified'
        assert 'payload digest' in next(iter(run.fields.values())).evidence
        assert await adapter.errors() == 0
        # A file already on the page has no byte evidence in a new session.
        old, = await WorkdayAdapter(page, URL, True).scan()
        assert not adapter.matches(old, str(resume))
        await page.locator('[data-automation-id=file-upload-item]').evaluate('e => e.parentElement.append(e.cloneNode(true))')
        duplicate_fields = await adapter.scan()
        assert all(f.invalid for f in duplicate_fields)
        await page.locator('[data-automation-id=file-upload-item]').last.evaluate('e => e.remove()')
        await page.locator('[role=alert]').evaluate('e => e.textContent="Upload failed"')
        assert await adapter.errors() == 1
        await page.locator('[data-automation-id=file-upload-successful]').evaluate('e => e.remove()')
        failed, = await adapter.scan()
        assert failed.invalid and not adapter.matches(failed, str(resume))
    asyncio.run(with_page(tmp_path, scenario))


def test_review_without_evidence_and_disclosures_are_not_ready(tmp_path):
    async def scenario(page, store):
        adapter = WorkdayAdapter(page, URL, True)
        await page.set_content('<h2>Voluntary Disclosures</h2><button>Submit Application</button>')
        assert await adapter.stage() == 'disclosures'
        await page.set_content('<h2>Review</h2><button onclick="window.sent=true">Submit Application</button>')
        run = ApplicationRun(job_url=URL)
        await ApplicationEngine(store).start(run, ApplicantProfile(), adapter)
        assert run.status == 'needs_input'
        assert not await page.evaluate('Boolean(window.sent)')
        with pytest.raises(ValueError):
            await adapter.exact_action(['Submit Application'])
    asyncio.run(with_page(tmp_path, scenario))


def test_searchable_combobox_readback_and_checkbox_false(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<h2>My Information</h2><label>Country<input role="combobox" onclick="document.querySelector('[role=option]').hidden=false"></label>
          <div role="option" hidden onclick="document.querySelector('input').value='Singapore';this.hidden=true">Singapore</div>
          <label>Contact me<input type="checkbox"></label>''')
        run = ApplicationRun(job_url=URL, stage='information')
        store.save_answer(ApprovedAnswer(question='Contact me', value=False, scope_key=run.id))
        assert await ApplicationEngine(store).complete_section(run, ApplicantProfile(country='Singapore'), WorkdayAdapter(page, URL, True))
        assert all(a.disposition == 'verified' for a in run.fields.values())
    asyncio.run(with_page(tmp_path, scenario))


def test_ai_recovery_does_not_send_network_or_enable_telemetry(tmp_path):
    async def scenario(page, store):
        assert not await BoundedRecovery().recover(page=page, profile={'password':'must-not-leak'})
        assert os.environ['ANONYMIZED_TELEMETRY'] == 'false'
        assert not BoundedRecovery.enabled
    asyncio.run(with_page(tmp_path, scenario))


def test_authentication_attempt_is_checkpointed_and_not_repeated(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<h2>Create Account</h2><label>Email<input type="email"></label><label>Password<input type="password"></label>
          <label>I consent<input type="checkbox"></label><button onclick="window.attempts=(window.attempts||0)+1">Create Account</button>''')
        run = ApplicationRun(job_url=URL)
        profile = ApplicantProfile()
        credential = {'username':'alias@example.test','password':'fictional-secret'}
        engine = ApplicationEngine(store)
        adapter = WorkdayAdapter(page, URL, True)
        await engine.start(run, profile, adapter, credential)
        assert run.status == 'needs_input'
        assert not run.authentication_attempted
        assert not await page.evaluate('Boolean(window.attempts)')
        store.save_answer(ApprovedAnswer(question='I consent', value=True, scope_key=run.id))
        await engine.resume(run, profile, adapter, credential)
        assert await page.evaluate('window.attempts') == 1
        assert run.authentication_attempted
        await ApplicationEngine(store).resume(store.get_run(run.id), profile, WorkdayAdapter(page, URL, True), credential)
        assert await page.evaluate('window.attempts') == 1
        assert b'fictional-secret' not in store.path.read_bytes()
    asyncio.run(with_page(tmp_path, scenario))


def test_session_expiry_pause_and_validation_errors(tmp_path):
    async def scenario(page, store):
        await page.set_content('<h2>Verify your email</h2><input aria-label="Verification code">')
        run = ApplicationRun(job_url=URL, stage='experience')
        await ApplicationEngine(store).resume(run, ApplicantProfile(), WorkdayAdapter(page, URL, True))
        assert run.stage == 'verification' and run.status == 'needs_input'
        await page.set_content('<h2>My Information</h2><label>First Name<input value="Ada"></label><div role="alert">Server rejected the value</div><button>Next</button>')
        await ApplicationEngine(store).resume(run, ApplicantProfile(first_name='Ada'), WorkdayAdapter(page, URL, True))
        assert run.status == 'needs_input'
        assert run.interventions[0].kind == 'validation'
    asyncio.run(with_page(tmp_path, scenario))


@pytest.mark.parametrize('trigger', ['initial', 'fill', 'advance', 'authentication', 'submission'])
def test_workday_page_error_pauses_without_repeating_actions(tmp_path, trigger):
    code = 'VPS|bd99d508-0e78-4614-bf8a-e52c29c4f170'
    async def scenario(page, store):
        error = f'<div>Something went wrong</div><p>Please refresh the page and then try again.</p><p>Error Code: {code}</p><p>private-page-text</p>'
        await page.set_content('''<h2>My Information</h2><label>First Name<input></label>
            <button onclick="fail()">Next</button><script>window.actions=0;
            function fail(){window.actions++;document.body.insertAdjacentHTML('beforeend', window.failure)}</script>''')
        await page.evaluate('(html) => window.failure = html', error)
        if trigger in {'initial', 'submission'}:
            await page.evaluate('document.body.insertAdjacentHTML("beforeend", window.failure)')
        elif trigger == 'fill':
            await page.locator('input').evaluate('e => e.oninput = fail')
        elif trigger == 'authentication':
            await page.locator('h2').evaluate('e => e.textContent="Sign In"')
            await page.locator('label').evaluate('e => e.innerHTML="Email<input type=email>"')
            await page.locator('button').evaluate('e => {e.textContent="Sign In";e.dataset.automationId="signInSubmitButton";e.insertAdjacentHTML("beforebegin", "<input type=password>")}')
        run = ApplicationRun(job_url=URL, submission_attempted=trigger == 'submission')
        engine = ApplicationEngine(store)
        adapter = WorkdayAdapter(page, URL, True)
        credential = {'username': 'fixture@example.test', 'password': 'fixture-password'}
        await engine.start(run, ApplicantProfile(first_name='Ada'), adapter, credential)
        assert run.status == 'needs_input', run.interventions
        assert run.interventions[0].kind == 'browser'
        message = run.interventions[0].message
        assert ('automatic resubmission is disabled' if trigger == 'submission' else code) in message
        assert not run.submission_confirmed
        actions = await page.evaluate('window.actions')
        assert actions == (0 if trigger in {'initial', 'submission'} else 1)
        await engine.resume(run, ApplicantProfile(first_name='Ada'), adapter, credential)
        assert run.status == 'needs_input'
        assert await page.evaluate('window.actions') == actions
        assert store.get_run(run.id).status == 'needs_input'
        assert b'private-page-text' not in store.path.read_bytes()
        assert b'fixture-password' not in store.path.read_bytes()
        if trigger == 'initial':
            await page.set_content('<h2>My Information</h2><label>First Name<input></label>')
            run.auto_advance = False
            await engine.resume(run, ApplicantProfile(first_name='Ada'), adapter)
            assert await page.locator('input').input_value() == 'Ada'
            assert run.completed_sections == ['information']
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_hidden_error_is_ignored_and_visible_refresh_error_pauses(tmp_path):
    from core.automation.workday import WorkdayPageError
    async def scenario(page, store):
        await page.set_content('<h2>My Information</h2><div hidden>Something went wrong. Please refresh the page and then try again.</div>')
        adapter = WorkdayAdapter(page, URL, True)
        assert await adapter.stage() == 'information'
        await page.locator('div').evaluate('e => e.hidden=false')
        # Error handoff must not wait out a spinner or a hanging request.
        adapter.pending.add(object())
        with pytest.raises(WorkdayPageError, match='Automation is paused'):
            await asyncio.wait_for(adapter.stage(), timeout=2)
    asyncio.run(with_page(tmp_path, scenario))


def test_changed_review_values_and_extra_rows_are_rejected(tmp_path):
    async def scenario(page, store):
        await page.set_content(FIXTURE.read_text())
        await page.evaluate('window.stage=2;render();row("education");row("education")')
        run = ApplicationRun(job_url=URL)
        profile = ApplicantProfile(education=[Education(school='Example', degree='BSc')])
        await ApplicationEngine(store).start(run, profile, WorkdayAdapter(page, URL, True))
        assert run.status == 'needs_input'
        assert '2 education rows' in run.interventions[0].message
        assert await page.locator('[data-intern-row]').count() == 2
        from core.automation.models import FieldAssessment
        run.completed_sections = ['information']
        run.fields = {'information::0:first name::0':FieldAssessment(key='information::0:first name::0', label='First Name', section='information', disposition='verified', answer_ref='profile:first_name')}
        await page.set_content('<h2>Review</h2><div data-intern-review data-label="First Name" data-value="Wrong"></div><button>Submit Application</button>')
        message = await WorkdayAdapter(page, URL, True).audit_review(run, ApplicantProfile(first_name='Ada'), [])
        assert 'Cannot independently reconcile' in message
    asyncio.run(with_page(tmp_path, scenario))


def test_pause_and_cancel_do_not_advance_or_submit(tmp_path):
    async def scenario(page, store):
        await page.set_content('<h2>My Information</h2><label>First Name<input></label><button onclick="window.advanced=true">Next</button>')
        run = ApplicationRun(job_url=URL)
        engine = ApplicationEngine(store)
        def pause_after_write(updated):
            if updated.fields:
                engine.pause()
        engine.emit = pause_after_write
        await engine.start(run, ApplicantProfile(first_name='Ada'), WorkdayAdapter(page, URL, True))
        assert run.status == 'needs_input'
        assert not await page.evaluate('Boolean(window.advanced)')
        engine.emit = lambda r: engine.cancel()
        await engine.resume(run, ApplicantProfile(first_name='Ada'), WorkdayAdapter(page, URL, True))
        assert run.status == 'cancelled'
    asyncio.run(with_page(tmp_path, scenario))


def test_embedded_form_is_explicitly_blocked(tmp_path):
    async def scenario(page, store):
        await page.set_content('<h2>My Information</h2><iframe srcdoc="<input required>"></iframe><button>Next</button>')
        run = ApplicationRun(job_url=URL)
        await ApplicationEngine(store).start(run, ApplicantProfile(), WorkdayAdapter(page, URL, True))
        assert run.status == 'needs_input'
        assert 'embedded frame' in run.interventions[0].message
    asyncio.run(with_page(tmp_path, scenario))


@pytest.mark.parametrize('headless', [True, False])
def test_browser_profile_lock_only_owns_its_session(tmp_path, headless):
    from core.browser.playwright_mgr import AsyncPlaywrightManager
    async def scenario():
        path = str(tmp_path / 'browser')
        first = AsyncPlaywrightManager(headless=headless, user_data_dir=path, executable_path=os.environ.get('INTERN_BOT_TEST_BROWSER'), browser=os.environ.get('INTERN_BOT_TEST_ENGINE', 'chromium'))
        second = AsyncPlaywrightManager(headless=headless, user_data_dir=path, executable_path=os.environ.get('INTERN_BOT_TEST_BROWSER'), browser=os.environ.get('INTERN_BOT_TEST_ENGINE', 'chromium'))
        try:
            context = await first.start()
            with pytest.raises(RuntimeError, match='already in use'):
                await second.start()
            page = context.pages[0]
            assert page.viewport_size == ({'width': 1280, 'height': 800} if headless else None)
            if first.browser != 'firefox':
                assert await page.evaluate('navigator.webdriver') is False
                assert 'Chrome/' in await page.evaluate('navigator.userAgent')
            await page.set_content('<h1>Still owned by first session</h1>')
            assert await page.title() == ''
            await first.stop()
            assert await second.start()
        finally:
            await second.stop()
            await first.stop()
    asyncio.run(scenario())


def test_browser_restores_session_cookies_and_preserves_invalid_state(tmp_path):
    import json
    from core.browser.playwright_mgr import AsyncPlaywrightManager
    async def scenario():
        directory = tmp_path / 'browser'
        manager = AsyncPlaywrightManager(headless=True, user_data_dir=str(directory), browser=os.environ.get('INTERN_BOT_TEST_ENGINE', 'chromium'))
        saved = directory / 'session-cookies.json'
        try:
            context = await manager.start()
            await context.add_cookies([{'name':'fixture_session','value':'fixture-only-token','url':URL,'httpOnly':True,'secure':True}])
            await manager.stop()
            assert saved.stat().st_mode & 0o777 == 0o600
            assert json.loads(saved.read_text())[0]['expires'] == -1
            context = await manager.start()
            cookies = await context.cookies(URL)
            assert any(c['name'] == 'fixture_session' and c['value'] == 'fixture-only-token' for c in cookies)
            await context.clear_cookies()
            await manager.stop()
            assert json.loads(saved.read_text()) == []
            saved.write_text('invalid state')
            with pytest.raises(json.JSONDecodeError):
                await manager.start()
            assert saved.read_text() == 'invalid state'
            assert manager.context is None and manager._lock is None
        finally:
            await manager.stop()
    asyncio.run(scenario())


def test_unverified_review_field_prevents_false_completion(tmp_path):
    async def scenario(page, store):
        from core.automation.models import FieldAssessment
        run = ApplicationRun(job_url=URL, completed_sections=['information'])
        key = 'information::0:first name::0'
        run.fields[key] = FieldAssessment(key=key, label='First Name', section='information', disposition='verified', answer_ref='profile:first_name')
        await page.set_content('<h2>Review</h2><div data-intern-review data-label="First Name" data-value="Ada"></div><div data-intern-review data-label="Secretly skipped question" data-value="Unknown"></div><button>Submit Application</button>')
        message = await WorkdayAdapter(page, URL, True).audit_review(run, ApplicantProfile(first_name='Ada'), [])
        assert 'unverified field' in message
    asyncio.run(with_page(tmp_path, scenario))


def test_same_filename_with_different_bytes_is_not_verified(tmp_path):
    async def scenario(page, store):
        expected = tmp_path / 'resume.pdf'
        expected.write_bytes(b'approved resume bytes')
        await page.set_content('<h2>Upload Resume</h2><label>Resume<input type="file"></label><button>Next</button>')
        await page.locator('input').set_input_files({'name':'resume.pdf','mimeType':'application/pdf','buffer':b'wrong resume bytes'})
        run = ApplicationRun(job_url=URL)
        await ApplicationEngine(store).start(run, ApplicantProfile(resume_path=str(expected)), WorkdayAdapter(page, URL, True))
        assert run.status == 'needs_input'
        assert run.interventions[0].kind == 'conflict'
    asyncio.run(with_page(tmp_path, scenario))


def test_stage_waits_for_loading_application_script(tmp_path):
    async def scenario(page, store):
        adapter = WorkdayAdapter(page, URL, True)
        async def script(route):
            await asyncio.sleep(.25)
            await route.fulfill(content_type="application/javascript", body="document.body.innerHTML='<h2>Sign In</h2><input type=password>'")
        await page.route('https://example.wd1.myworkdayjobs.com/application.js', script)
        await page.set_content('<script async src="https://example.wd1.myworkdayjobs.com/application.js"></script>', wait_until='domcontentloaded')
        assert await adapter.stage() == 'sign_in'
    asyncio.run(with_page(tmp_path, scenario))


def test_workday_saved_credentials_choose_existing_signin_and_scoped_submit(tmp_path):
    async def scenario(page, store):
        await page.set_content('''<div data-automation-id="progressBarActiveStep">Create Account/Sign In</div>
          <button onclick="window.wrongButton=true">Sign In</button>
          <main><input type="password"><button data-automation-id="createAccountSubmitButton" onclick="window.created=true">Create Account</button>
          <button data-automation-id="signInLink" onclick="signIn()">Sign In</button></main>
          <script>function signIn(){document.querySelector('main').innerHTML =
            '<label>Email Address<input autocomplete="email" type="text"></label>' +
            '<label>Password<input type="password"></label>' +
            '<input data-automation-id="beecatcher" aria-label="Leave empty">' +
            '<div style="position:relative"><div role="button" tabindex="0" aria-label="Sign In" data-automation-id="click_filter" style="position:absolute;inset:0" onclick="login()"></div>' +
            '<button data-automation-id="signInSubmitButton" aria-hidden="true" tabindex="-2" onclick="window.wrongButton=true">Sign In</button></div>';}
          function login(){window.loginCount=(window.loginCount||0)+1;
            window.trapValue=document.querySelector('[data-automation-id=beecatcher]').value;
            document.querySelector('[data-automation-id=progressBarActiveStep]').textContent='My Information';
            document.querySelector('main').innerHTML='<h2>My Information</h2><label>Unknown fact<input></label><button>Next</button>';}</script>''')
        run=ApplicationRun(job_url=URL)
        await ApplicationEngine(store).start(run,ApplicantProfile(),WorkdayAdapter(page,URL,True),{'username':'sample@example.test','password':'fixture-only-secret'})
        assert run.stage=='information' and run.status=='needs_input'
        assert not run.authentication_attempted
        assert await page.evaluate('window.loginCount')==1
        assert await page.evaluate('window.trapValue')==''
        assert not await page.evaluate('Boolean(window.wrongButton || window.created)')
        assert b'fixture-only-secret' not in store.path.read_bytes()
    asyncio.run(with_page(tmp_path,scenario))
