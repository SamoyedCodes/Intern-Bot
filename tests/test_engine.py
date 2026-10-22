"""ApplicationEngine against the real extension and local fixtures: verification, submission and stop guarantees."""
import asyncio
from types import SimpleNamespace

import pytest
from playwright.async_api import Error as PlaywrightError

import core.automation.engine as engine_module
from core.automation.answers import resolve
from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.fields import FormField
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, Education, Experience, FieldAssessment, Language
from tests.support import FIXTURES, URLS, greenhouse, open_fixture, prepare, profile_for, resume_upload, until

COUNT_SUBMISSION = 'window.submissions=(window.submissions||0)+1'
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


async def apply(store, page, run, profile=None):
    return await ApplicationEngine(store).start(run, profile or profile_for('greenhouse'), ExtensionBridge(page, run.id))


def record_commands(bridge, before=None, after=None):
    """Log every extension command; `await before(name)` runs ahead of each one and `after(name)` once it returns."""
    sent, command = [], bridge.command
    async def recorded(name, payload=None, binding=None):
        sent.append(name)
        if before:
            await before(name)
        result = await command(name, payload, binding)
        if after:
            after(name)
        return result
    bridge.command = recorded
    return sent


async def test_submission_is_persisted_before_the_click_and_never_retried(context, store):
    page = await open_fixture(context, 'greenhouse', greenhouse())
    run = ApplicationRun(job_url=page.url, auto_submit=True)
    checkpoints = []
    engine = ApplicationEngine(store, lambda r: checkpoints.append((r.submission_attempted, r.submission_confirmed)))
    await engine.start(run, profile_for('greenhouse'), ExtensionBridge(page, run.id))
    assert run.submission_confirmed and run.pipeline == 'applied', run.interventions
    assert (True, False) in checkpoints
    assert await page.evaluate('window.submissions') == 1
    await engine.resume(store.get_run(run.id), profile_for('greenhouse'), ExtensionBridge(page, run.id))
    assert await page.evaluate('window.submissions') == 1


@pytest.mark.parametrize('auto_submit, extra, status', [
    (False, '', 'ready_for_review'),
    (True, '<label>Fictional fact<input required></label>', 'needs_input'),
], ids=['manual-by-default', 'unknown-required-fact'])
async def test_nothing_is_submitted_by_default_or_with_unknown_facts(context, store, auto_submit, extra, status):
    page = await open_fixture(context, 'greenhouse', greenhouse(extra=extra, handler=COUNT_SUBMISSION))
    run = await apply(store, page, ApplicationRun(job_url=page.url, auto_submit=auto_submit))
    assert run.status == status and not run.submission_attempted, run.interventions
    assert not await page.evaluate('Boolean(window.submissions)')


@pytest.mark.parametrize('handler', [
    COUNT_SUBMISSION,
    COUNT_SUBMISSION + ";document.body.innerHTML='<h1 hidden>Application submitted</h1>'",
], ids=['no-receipt', 'hidden-receipt'])
async def test_an_unconfirmed_submission_is_never_retried(context, store, monkeypatch, handler):
    monkeypatch.setattr(ApplicationEngine, 'RECEIPT_POLLS', 4)
    page = await open_fixture(context, 'greenhouse', greenhouse(handler=handler))
    run = ApplicationRun(job_url=page.url, auto_submit=True)
    engine = ApplicationEngine(store)
    await engine.start(run, profile_for('greenhouse'), ExtensionBridge(page, run.id))
    assert run.submission_attempted and not run.submission_confirmed
    await engine.resume(run, profile_for('greenhouse'), ExtensionBridge(page, run.id))
    assert not run.submission_confirmed and await page.evaluate('window.submissions') == 1


@pytest.mark.parametrize('stop, status', [('pause', 'needs_input'), ('cancel', 'cancelled')])
async def test_stopping_a_waiting_adapter_blocks_late_writes(context, store, stop, status):
    page = await open_fixture(context, 'greenhouse', greenhouse().replace('id="application"', 'id="loading"'))
    run = ApplicationRun(job_url=page.url, auto_submit=True)
    engine, bridge = ApplicationEngine(store), ExtensionBridge(page, run.id)
    sent = record_commands(bridge)
    task = asyncio.create_task(engine.start(run, profile_for('greenhouse'), bridge))
    await until(lambda: 'snapshot' in sent)  # The adapter is running and waiting for its form.
    getattr(engine, stop)()
    await task
    await page.evaluate('document.querySelector("form").id="application"')
    await asyncio.sleep(1)  # Deliberate: the late form must not wake the stopped adapter.
    assert await page.locator('#first_name').input_value() == ''
    assert not await page.evaluate('Boolean(window.submissions)')
    assert run.status == status


async def test_pause_after_prepare_blocks_even_approved_answers(context, store):
    page = await open_fixture(context, 'greenhouse', greenhouse())
    run = ApplicationRun(job_url=page.url)
    store.save_answer(ApprovedAnswer(question='First name', value='Approved name', scope_key=run.id))
    bridge, engine = ExtensionBridge(page, run.id), ApplicationEngine(store)
    record_commands(bridge, after=lambda name: name == 'prepare' and engine.pause())
    await engine.start(run, profile_for('greenhouse'), bridge)
    assert run.status == 'needs_input' and not run.submission_attempted
    assert await page.locator('#first_name').input_value() == ''


async def test_stale_documents_and_superseded_commands_are_rejected(context, store):
    page = await open_fixture(context, 'greenhouse')
    bridge, _, run, _, _ = await prepare(page, store, 'greenhouse')
    stale_token = bridge.binding['token']
    other, _, _, _, _ = await prepare(page, store, 'greenhouse', run=run)
    assert other.binding['token'] != stale_token
    with pytest.raises(Exception, match='Expired application'):
        await bridge.command('start')
    await page.reload()
    with pytest.raises(Exception, match='Receiving end does not exist'):
        await other.command('start')
    assert await page.locator('#first_name').input_value() == ''


async def employer_page(context, frames):
    """An employer page embedding `frames` copies of the Greenhouse application."""
    page = await context.new_page()
    employer = '<h1>Employer</h1><label>Newsletter<input id=news></label>' + f'<iframe src="{URLS["greenhouse"]}"></iframe>' * frames
    async def route(route):
        await route.fulfill(body=greenhouse() if 'boards.greenhouse.io' in route.request.url else employer, content_type='text/html')
    await page.route('**/*', route)
    await page.goto('https://careers.example.test/apply')
    return page


async def test_only_employer_requests_hold_a_section_open(context):
    page = await open_fixture(context, 'workday')
    bridge = ExtensionBridge(page, 'run')
    hung = []
    await page.route(lambda url: url.endswith(('/li/track', '/wday/save', '/termslockmoment')), lambda route: hung.append(route))  # Held open, like a stuck beacon.
    await page.evaluate("() => { for (const url of ['https://www.linkedin.com/li/track', '/wday/save', '/wday/calypso/cxs/jobapplication/test/jobapplication/draft/termslockmoment']) fetch(url, {method: 'POST'}).catch(() => {}) }")
    await until(lambda: len(hung) == 3)
    assert [r.url.rsplit('/', 2)[-2:] for r in bridge.pending] == [['wday', 'save']]
    for route in hung:
        await route.abort()
    await page.close()


async def test_only_the_application_frame_receives_the_profile(context, store):
    page = await employer_page(context, frames=1)
    run = await apply(store, page, ApplicationRun(job_url=page.url))
    assert run.status == 'ready_for_review', run.interventions
    assert await page.locator('#news').input_value() == ''
    assert await page.frames[1].locator('#first_name').input_value() == 'Ada'


async def test_two_matching_frames_hand_off_instead_of_choosing(context, store):
    page = await employer_page(context, frames=2)
    run = await apply(store, page, ApplicationRun(job_url=page.url))
    assert run.status == 'needs_input' and 'More than one' in run.interventions[0].message
    assert [await frame.locator('#first_name').input_value() for frame in page.frames[1:]] == ['', '']


async def test_concurrent_applications_stay_isolated(context, store):
    first = await open_fixture(context, 'greenhouse')
    second = await open_fixture(context, 'greenhouse', url='https://boards.greenhouse.io/other/jobs/2')
    grace = profile_for('greenhouse')
    grace.first_name = 'Grace'
    one, engine1, run1, profile1, _ = await prepare(first, store, 'greenhouse')
    two, engine2, run2, profile2, _ = await prepare(second, store, 'greenhouse', profile=grace)
    await one.command('start')
    await two.command('start')
    await engine1.wait_for_section(run1, profile1)
    await engine2.wait_for_section(run2, profile2)
    assert await first.locator('#first_name').input_value() == 'Ada'
    assert await second.locator('#first_name').input_value() == 'Grace'
    cross_run = ExtensionBridge(first, run2.id)
    cross_run.binding = one.binding
    with pytest.raises(Exception, match='Expired application'):
        await cross_run.command('start')
    await one.stop()
    await two.stop()


async def test_same_document_navigation_revokes_the_adapter(context, store):
    page = await open_fixture(context, 'greenhouse', greenhouse().replace('id="application"', 'id="loading"'))
    bridge, _, _, _, _ = await prepare(page, store, 'greenhouse')
    await bridge.command('start')
    await page.evaluate("location.hash='another-document';document.querySelector('form').id='application'")
    await asyncio.sleep(.5)  # Deliberate: give the revoked adapter time to (not) write.
    assert not (await bridge.command('snapshot'))['live']
    assert await page.locator('#first_name').input_value() == ''
    assert not await page.evaluate('Boolean(window.submissions)')


@pytest.mark.parametrize('accept, existing, accepted', [
    ('.docx', False, True), ('.pdf', False, False), ('.docx', True, False),
], ids=['matching-type', 'unsupported-type', 'conflicting-existing-file'])
async def test_resume_upload_checks_type_readback_and_existing_files(context, store, tmp_path, accept, existing, accepted):
    resume = tmp_path / 'fictional.docx'
    resume.write_bytes(b'fictional-document-payload')
    page = await open_fixture(context, 'greenhouse', greenhouse(extra=resume_upload(accept)))
    if existing:
        await page.locator('input[type=file]').set_input_files({'name': 'fictional.docx', 'mimeType': DOCX, 'buffer': b'different bytes'})
    profile = profile_for('greenhouse')
    profile.resume_path = str(resume)
    run = await apply(store, page, ApplicationRun(job_url=page.url), profile)
    assert run.status == ('ready_for_review' if accepted else 'needs_input'), run.interventions
    assert not run.submission_attempted
    if accepted:
        assert await page.locator('input[type=file]').evaluate('e => e.files[0].type') == DOCX


@pytest.mark.parametrize('control, read, expected', [
    ('<label>Cover Letter<textarea></textarea></label>', 'e => e.value', 'Explicit letter text'),
    ('<label>Cover Letter<input type=file accept=".txt" onchange="this.parentElement.querySelector(\'[role=status]\').textContent=this.files[0].name+\' uploaded\'"><span role=status></span></label>',
     'e => e.files[0].name', 'cover.txt'),
], ids=['text', 'file'])
async def test_cover_letter_fills_as_text_or_file(context, store, tmp_path, control, read, expected):
    cover = tmp_path / 'cover.txt'
    cover.write_text('Fictional cover letter')
    page = await open_fixture(context, 'greenhouse', greenhouse(extra=control))
    profile = profile_for('greenhouse')
    profile.cover_letter_path, profile.cover_letter = str(cover), 'Explicit letter text'
    run = await apply(store, page, ApplicationRun(job_url=page.url), profile)
    assert run.status == 'ready_for_review' and not run.submission_attempted, run.interventions
    assert await page.get_by_label('Cover Letter').evaluate(read) == expected


async def test_conditional_fields_rerenders_and_a_late_enabled_submit(context, store):
    reveal = "if(this.checked&&!document.querySelector('#conditional')){const l=document.createElement('label');l.innerHTML='Extra fact<input id=conditional required>';this.closest('form').append(l)}"
    html = greenhouse(extra=f'''<label>Choice<input type=checkbox onchange="{reveal}"></label><script>setTimeout(()=>document.querySelector('#submit_app').disabled=false,800)</script>''').replace('id="submit_app"', 'id="submit_app" disabled')
    page = await open_fixture(context, 'greenhouse', html)
    run = ApplicationRun(job_url=page.url)
    store.save_answer(ApprovedAnswer(question='Choice', value=True, scope_key=run.id))
    store.save_answer(ApprovedAnswer(question='Extra fact', value='Explicit fact', scope_key=run.id))
    engine = ApplicationEngine(store)
    # Checking Choice reveals Extra fact; retry verification only after the new field settles.
    await engine.start(run, profile_for('greenhouse'), ExtensionBridge(page, run.id))
    assert run.status == 'ready_for_review', run.interventions
    assert await page.locator('#conditional').input_value() == 'Explicit fact'
    # A re-rendered control loses its value; resuming fills the replacement.
    await page.locator('#first_name').evaluate('e => {const copy=e.cloneNode();copy.value="";e.replaceWith(copy)}')
    await engine.resume(run, profile_for('greenhouse'), ExtensionBridge(page, run.id))
    assert await page.locator('#first_name').input_value() == 'Ada'
    assert not await page.evaluate('Boolean(window.submissions)')


async def test_an_unrecognized_form_hands_off_within_a_bounded_wait(context, store, monkeypatch):
    monkeypatch.setattr(ApplicationEngine, 'SECTION_POLLS', 20)
    page = await open_fixture(context, 'greenhouse', '<h1>Unrecognized form</h1>')
    run = await asyncio.wait_for(apply(store, page, ApplicationRun(job_url=page.url)), 25)
    assert run.status == 'needs_input' and not run.submission_attempted
    assert 'bounded wait' in run.interventions[-1].message


REVIEW_PAGE = '''<script>window.submissions=0;function review(){const value=document.querySelector('input').value;document.body.innerHTML=`<div data-automation-id="reviewJobApplicationPage"><dl><dt>First Name</dt><dd>${VALUE}</dd><dt>Last Name</dt><dd>Example</dd><dt>Email</dt><dd>ada@example.test</dd></dl><button type="button" data-automation-id="bottom-navigation-next-button" onclick="window.submissions++;document.body.innerHTML='<h1>Application submitted</h1>'">Submit Application</button></div>`;}</script>'''


@pytest.mark.parametrize('reviewed_name, submitted', [('${value}', True), ('Wrong', False)], ids=['review-matches', 'review-differs'])
async def test_auto_advance_submits_only_when_the_review_matches(context, store, reviewed_name, submitted):
    html = (FIXTURES / 'workday.html').read_text().replace('>Next</button>', ' onclick="review()">Next</button>')
    page = await open_fixture(context, 'workday', html + REVIEW_PAGE.replace('${VALUE}', reviewed_name))
    run = await apply(store, page, ApplicationRun(job_url=page.url, auto_submit=True), profile_for('workday'))
    assert (run.submission_attempted, run.submission_confirmed) == (submitted, submitted), run.interventions
    assert run.status == ('ready_for_review' if submitted else 'needs_input')
    assert await page.evaluate('window.submissions') == int(submitted)


async def test_immediate_preclick_recheck_blocks_a_changed_form(context, store):
    page = await open_fixture(context, 'greenhouse', greenhouse())
    run = ApplicationRun(job_url=page.url, auto_submit=True)
    bridge = ExtensionBridge(page, run.id)
    async def change_before_click(name):
        if name == 'action':
            assert store.get_run(run.id).submission_attempted
            await page.evaluate("document.querySelector('#first_name').value='Unexpected value'")
    record_commands(bridge, before=change_before_click)
    await ApplicationEngine(store).start(run, profile_for('greenhouse'), bridge)
    assert run.submission_attempted and not run.submission_confirmed
    assert run.status == 'needs_input'
    assert not await page.evaluate('Boolean(window.submissions)')


async def test_apply_label_is_never_an_unauthorized_continuation(context, store):
    body = (FIXTURES / 'tesla.html').read_text() + f'<button type="submit" onclick="{COUNT_SUBMISSION}">Apply</button>'
    page = await open_fixture(context, 'tesla', body)
    run = await apply(store, page, ApplicationRun(job_url=page.url), profile_for('tesla'))
    assert run.status == 'ready_for_review', run.interventions
    assert not run.submission_attempted and not await page.evaluate('Boolean(window.submissions)')


async def test_workday_repeated_rows_resume_and_flag_extra_rows(context, store):
    page = await open_fixture(context, 'workday', (FIXTURES / 'workday-rows.html').read_text())
    profile = ApplicantProfile(
        experience=[Experience(job_title='Engineer', employer='Fictional One', description='Built examples'),
                    Experience(job_title='Intern', employer='Fictional Two', description='Tested examples')],
        education=[Education(school='Fictional College', gpa='3.8'), Education(school='Second College', gpa='3.9')])
    run = ApplicationRun(job_url=page.url, auto_advance=False)
    bridge, engine = ExtensionBridge(page, run.id), ApplicationEngine(store)
    await engine.start(run, profile, bridge)
    assert len(run.fields) == 10 and all(f.disposition == 'verified' for f in run.fields.values()), run.interventions
    assert {f.row for f in run.fields.values()} == {0, 1}
    await engine.resume(run, profile, bridge)
    assert await page.locator('[data-automation-id^="workExperience-"]').count() == 2
    assert await page.locator('[data-automation-id^="education-"]').count() == 2
    assert len(run.fields) == 10 and all(f.disposition == 'verified' for f in run.fields.values())
    await page.evaluate("addRow('experience')")
    await engine.resume(run, profile, bridge)
    assert run.status == 'needs_input' and not run.submission_attempted
    assert any('extra row' in i.message for i in run.interventions)
    assert not await page.evaluate('Boolean(window.advanced)')


WORKDAY_LANGUAGES = '''<div data-automation-id="myExperiencePage"><h2>My Experience</h2>
<div role="group" aria-labelledby="Languages-section"><h3 id="Languages-section">Languages</h3>
<button type="button" aria-label="Add Language" onclick="addLanguage()">Add Language</button></div>
<button type="button" data-automation-id="bottom-navigation-next-button">Next</button></div>
<script>
function addLanguage(){
    const row=document.createElement('div'); row.setAttribute('role','group');row.setAttribute('aria-labelledby','Languages-1-panel');
    row.innerHTML='<label id="language-label">Language</label><button type="button" name="language" data-automation-id="language" aria-labelledby="language-label" aria-haspopup="listbox" aria-controls="choices" onclick="openChoices(this)">Select One</button><label>I am fluent in this language<input type="checkbox" data-automation-id="nativeLanguage"></label>';
    document.querySelector('[aria-labelledby="Languages-section"]').append(row);
}
function openChoices(button){
    if(document.querySelector('#choices'))return;
    const popup=document.createElement('div');popup.dataset.automationWidget='wd-popup';popup.dataset.automationActivepopup='true';
    popup.innerHTML='<ul id="choices" role="listbox"><li role="option">English</li><li role="option">French</li></ul>';
    popup.querySelectorAll('li').forEach(e=>e.onclick=()=>{button.textContent=e.textContent;popup.remove()});document.body.append(popup);
}
</script>'''


async def test_workday_language_dropdown_and_fluency_checkbox(context, store):
    page = await open_fixture(context, 'workday', WORKDAY_LANGUAGES)
    profile = ApplicantProfile(language_proficiency=[Language(language='English', fluent=True)])
    run = await apply(store, page, ApplicationRun(job_url=page.url, auto_advance=False), profile)
    assert len(run.fields) == 2 and all(f.disposition == 'verified' for f in run.fields.values()), run.interventions
    assert await page.get_by_role('button', name='Language', exact=True).inner_text() == 'English'
    assert await page.locator('input[type=checkbox]').is_checked()


WORKDAY_SPEAKING = '''<div data-automation-id="myExperiencePage"><h2>My Experience</h2>
<div role="group" aria-labelledby="Languages-section"><h3 id="Languages-section">Languages</h3>
<button type="button" aria-label="Add Language" onclick="addLanguage()">Add Language</button></div>
<button type="button" data-automation-id="bottom-navigation-next-button">Next</button></div>
<script>
const choices={language:['English','French'],speaking:['Select One','1 - Slight','2 - Fair','3 - Fluent']};
function addLanguage(){
    const row=document.createElement('div'); row.setAttribute('role','group');row.setAttribute('aria-labelledby','Languages-1-panel');
    row.innerHTML='<label id="language-label">Language</label><button type="button" name="language" data-automation-id="language" aria-labelledby="language-label" aria-haspopup="listbox" aria-controls="language-choices" onclick="toggle(this)">Select One</button>'
        +'<label id="speaking-label">Speaking</label><button type="button" data-automation-id="languageProficiency-0" aria-labelledby="speaking-label" aria-haspopup="listbox" aria-required="true" aria-controls="speaking-choices" onclick="toggle(this)">Select One</button>';
    document.querySelector('[aria-labelledby="Languages-section"]').append(row);
}
function toggle(button){
    const id=button.getAttribute('aria-controls'), open=document.getElementById(id);
    if(open){open.parentElement.remove();return;}
    const popup=document.createElement('div');popup.dataset.automationWidget='wd-popup';popup.dataset.automationActivepopup='true';
    popup.innerHTML=`<ul id="${id}" role="listbox">`+choices[id.split('-')[0]].map(c=>`<li role="option"${c==='Select One'?' id="select-one"':''}>${c}</li>`).join('')+'</ul>';
    popup.querySelectorAll('li').forEach(e=>e.onclick=()=>{button.textContent=e.textContent;popup.remove()});
    button.onkeydown=event=>{if(event.key==='Escape')popup.remove()};
    document.body.append(popup);
}
</script>'''


# 'Fluent' is outside the adapter's proficiency scale, so it clicks "Select One"; '' leaves the dropdown untouched.
@pytest.mark.parametrize('proficiency', ['Fluent', ''])
async def test_workday_dropdown_lists_options_and_selects_the_approved_choice(context, store, proficiency):
    page = await open_fixture(context, 'workday', WORKDAY_SPEAKING)
    profile = ApplicantProfile(language_proficiency=[Language(language='English', proficiency=proficiency)])
    run = await apply(store, page, ApplicationRun(job_url=page.url, auto_advance=False), profile)
    request = next(i for i in run.interventions if i.question == 'Speaking — English')  # Named for its row.
    assert request.options == ['1 - Slight', '2 - Fair', '3 - Fluent']
    store.save_answer(ApprovedAnswer(question='Speaking — English', value='2 - Fair', scope_key=run.id))
    run = await apply(store, page, run, profile)
    assert all(f.disposition == 'verified' for f in run.fields.values()), run.interventions
    assert not any(i.question for i in run.interventions), run.interventions
    assert await page.locator('[data-automation-id="languageProficiency-0"]').inner_text() == '2 - Fair'


WORKDAY_PROMPT = '''<div data-automation-id="myExperiencePage"><h2>My Experience</h2>
<div data-automation-id="formField-fieldOfStudy"><label for="study">Field of Study</label>
<div data-automation-id="multiselectInputContainer"><ul role="listbox"></ul>
<input id="study" data-uxi-widget-type="selectinput" data-uxi-multiselect-id="study-prompt" onkeydown="if(event.key==='Enter')search(this.value);if(event.key==='Escape')closeResults()"></div></div>
<button type="button" data-automation-id="bottom-navigation-next-button">Next</button></div>
<script>
const categories=['Computer'], fields=['Accounting','Computer Engineering','Computer Science'];
const closeResults=()=>document.querySelector('[data-associated-widget]')?.remove();
// Like Workday, results come from the server only after Enter; a category opens a nested list instead of selecting.
function search(query){
    const found=list=>list.filter(f=>f.toLowerCase().includes(query.toLowerCase()));
    setTimeout(()=>{
        closeResults();
        const popup=document.createElement('div');popup.dataset.associatedWidget='study-prompt';
        popup.innerHTML='<div data-automation-id="activeListContainer"><div role="presentation">'
            +found(categories).map(c=>`<div role="option" onclick="window.categoryOpened=true"><div data-automation-id="promptOption">${c}</div></div>`).join('')
            +found(fields).map(f=>`<div role="option"><div><input type="radio" onclick="pick('${f}')"></div><div data-automation-id="promptOption">${f}</div></div>`).join('')+'</div></div>';
        document.body.append(popup);
    },200);
}
function pick(value){
    document.querySelector('[data-automation-id="multiselectInputContainer"] ul').innerHTML=`<li data-automation-id="menuItem"><div data-automation-id="selectedItem"><div data-automation-id="promptOption">${value}</div></div></li>`;
    document.getElementById('study').value='';closeResults();
}
</script>'''


async def test_workday_prompt_searches_the_answer_and_selects_only_an_exact_result(context, store):
    page = await open_fixture(context, 'workday', WORKDAY_PROMPT)
    run = ApplicationRun(job_url=page.url, auto_advance=False)
    answer = ApprovedAnswer(question='Field of Study', value='Computer', scope_key=run.id)
    store.save_answer(answer)
    run = await apply(store, page, run, ApplicantProfile())
    # 'Computer' exactly names only a category, so nothing is clicked and the search's choices are offered instead.
    request = next(i for i in run.interventions if i.question == 'Field of Study')
    assert request.options == ['Computer Engineering', 'Computer Science']
    assert not await page.locator('[data-automation-id="selectedItem"]').count()
    assert not await page.evaluate('window.categoryOpened')
    store.save_answer(answer.model_copy(update={'value': 'Computer Science'}))
    run = await apply(store, page, run, ApplicantProfile())
    assert all(f.disposition == 'verified' for f in run.fields.values()), run.interventions
    assert await page.locator('[data-automation-id="selectedItem"]').all_inner_texts() == ['Computer Science']


async def test_greenhouse_boolean_question_selects_the_profile_fact(context, store):
    question = '<div id="custom_fields"><div class="field"><label>Do you require sponsorship?<select><option value="">Select One</option><option>Yes</option><option>No</option></select></label></div></div>'
    page = await open_fixture(context, 'greenhouse', greenhouse(extra=question))
    profile = profile_for('greenhouse')
    profile.requires_sponsorship = False
    run = await apply(store, page, ApplicationRun(job_url=page.url), profile)
    assert run.status == 'ready_for_review' and not run.submission_attempted, run.interventions
    assert await page.locator('select').input_value() == 'No'


async def test_worker_restart_rebinds_without_restarting_the_adapter(fresh_context, store):
    context = fresh_context
    page = await open_fixture(context, 'greenhouse', greenhouse())
    bridge, engine, run, profile, _ = await prepare(page, store, 'greenhouse')
    await bridge.command('start')
    await engine.wait_for_section(run, profile)
    binding = bridge.binding.copy()
    session = await context.new_cdp_session(page)
    await session.send('ServiceWorker.enable')
    targets = await session.send('Target.getTargets')
    worker = next(t for t in targets['targetInfos'] if t['type'] == 'service_worker' and 'chrome-extension://' in t['url'])
    await asyncio.wait_for(session.send('Target.closeTarget', {'targetId': worker['targetId']}), 5)
    # Playwright keeps listing the closed worker; it either stops answering or reports the restart.
    with pytest.raises((asyncio.TimeoutError, PlaywrightError)):
        await asyncio.wait_for(context.service_workers[0].evaluate('1'), 1)
    snapshot = await bridge.command('snapshot')
    assert bridge.binding == binding
    assert snapshot['status'] in {'autofill-complete', 'action-pending'}
    assert not await page.evaluate('Boolean(window.submissions)')
    await bridge.stop()
    await session.detach()


async def test_changed_cover_letter_bytes_invalidate_saved_verification(store, tmp_path):
    class ManualBridge:
        page = SimpleNamespace(url='https://careers.example.test/job/1')
        binding = None
        async def discover(self): return {'matches': []}
        async def stop(self): pass
    letter = tmp_path / 'cover.txt'
    letter.write_text('First explicitly approved document')
    profile = ApplicantProfile(cover_letter_path=str(letter))
    run = ApplicationRun(job_url=ManualBridge.page.url)
    engine = ApplicationEngine(store)
    await engine.start(run, profile, ManualBridge())
    before = run.documents_digest
    run.fields = {'letter': FieldAssessment(key='letter', label='Cover letter', disposition='verified')}
    run.completed_sections = ['old-review']
    await engine.resume(run, profile, ManualBridge())
    assert run.fields and run.completed_sections == ['old-review']
    letter.write_text('Changed document at exactly the same path')
    await engine.resume(run, profile, ManualBridge())
    assert run.documents_digest != before
    assert run.fields == {} and run.completed_sections == []
    assert store.get_run(run.id).documents_digest == run.documents_digest


@pytest.mark.parametrize('question, variants', [('Have you worked with us before?', []),
                                               ('Have you previously worked for this company?', ['Have you worked with us before?'])])
async def test_an_approved_radio_is_clicked_so_the_site_registers_it(context, store, monkeypatch, question, variants):
    monkeypatch.setattr(ApplicationEngine, 'SECTION_POLLS', 20)  # The rest of the Workday page never appears.
    radios = ''.join(f'<div><div><input type=radio name=previous id={o} onclick="window.picked=`{o}`"></div><label for={o}>{o}</label></div>' for o in ('Yes', 'No'))
    page = await open_fixture(context, 'workday', f'<div data-automation-id=applyFlowMyInfoPage><fieldset><legend>Have you worked with us before?</legend>{radios}</fieldset></div>')
    run = ApplicationRun(job_url=page.url)
    store.save_answer(ApprovedAnswer(question=question, variants=variants, value='No', scope_key=run.id, profile_name=run.profile_name))
    await ApplicationEngine(store).start(run, ApplicantProfile(), ExtensionBridge(page, run.id))
    assert await page.evaluate('window.picked') == 'No'


def test_a_reformatted_phone_number_still_verifies(store):
    run = ApplicationRun(job_url='https://example.wd1.myworkdayjobs.com/job')
    field = FormField('phone', 'Phone Number', '', 'text', value='9876 5411')
    assert ApplicationEngine(store).verify(run, ApplicantProfile(phone_country_code='+65', phone_number='98765411'), [field], {'files': {}})


@pytest.mark.parametrize('key, enabled, asked', [('key', True, True), ('', True, False), ('key', False, False)])
async def test_ai_records_a_rewording_once_and_it_resolves(store, monkeypatch, key, enabled, asked):
    run = ApplicationRun(job_url='https://example.wd1.myworkdayjobs.com/job')
    store.save_answer(ApprovedAnswer(question='When is your intended period of internship?', value='Jan - May 2027', scope='global'))
    store.put('automation_options', {'ai_match': enabled})
    store._vault().set('gemini-api-key', key)
    sent = []
    monkeypatch.setattr(engine_module, 'match_questions', lambda key, model, questions, known, provider: sent.append((questions, known)) or {'Internship period': 0})
    fields = [FormField('a', 'Internship period', '', 'text'), FormField('b', 'Hobbies', '', 'text'), FormField('c', 'First name', '', 'text')]
    profile = ApplicantProfile(first_name='Ada')
    engine = ApplicationEngine(store)
    for _ in range(2):  # The second pass must not ask again.
        await engine.match_rewordings(run, profile, fields)
    assert sent == ([(['Internship period', 'Hobbies'], ['When is your intended period of internship?'])] if asked else [])
    assert (resolve(fields[0], profile, run, store.answers()).value == 'Jan - May 2027') is asked


async def test_the_sites_own_step_list_is_recorded_for_the_progress_stepper(context, store):
    steps = ''.join(f'<li data-automation-id={state}><label>{prefix}step {i} of 3</label><div>{name}</div></li>' for i, (state, prefix, name) in enumerate(
        [('progressBarCompletedStep', 'completed ', 'My Information'), ('progressBarActiveStep', 'current ', 'My Experience'), ('progressBarInactiveStep', '', 'Review')], 1))
    page = await open_fixture(context, 'greenhouse', greenhouse(extra=f'<ol data-automation-id=progressBar>{steps}</ol>'))
    run = await apply(store, page, ApplicationRun(job_url=page.url))
    assert (run.steps, run.step) == (['My Information', 'My Experience', 'Review'], 1)


async def test_an_unlisted_degree_or_open_search_popup_does_not_stop_the_workday_resume_upload(context, store, tmp_path, monkeypatch):
    monkeypatch.setattr(ApplicationEngine, 'SECTION_POLLS', 100)  # Outlasts the popup wait's 5 s deadline.
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF fictional resume')
    page = await open_fixture(context, 'workday', '''<div data-automation-id="myExperiencePage"><h2>My Experience</h2>
<div role="group" aria-labelledby="Education-section"><h3 id="Education-section">Education</h3>
<div role="group" aria-labelledby="Education-1-panel"><label>School or University<input data-automation-id="school"></label>
<div data-automation-id="formField-fieldOfStudy"><label>Field of Study<input data-uxi-widget-type="selectinput" data-uxi-multiselect-id="m1"
 onkeydown="if(event.key==='Enter'){window.searched=true;window.searchPrevented=event.defaultPrevented}"
 onclick="if(!document.querySelector('[data-associated-widget=m1]'))document.body.insertAdjacentHTML('beforeend','<div data-associated-widget=m1><div data-automation-id=activeListContainer><div role=presentation>All</div></div></div>')"></label></div></div></div>
<div role="group" aria-labelledby="Resume/CV-section"><h3 id="Resume/CV-section">Resume/CV</h3><label>Resume<input type=file></label></div></div>''')
    # Workday's degree lookup only knows its own labels, such as "Bachelor's"; Keppel's search popup stays open after a search.
    profile = ApplicantProfile(resume_path=str(resume), education=[Education(school='Example University', degree='Bachelor of Science (Honours)', major='Data Science')])
    run = await apply(store, page, ApplicationRun(job_url=page.url, auto_advance=False), profile)
    assert await page.locator('input[type=file]').evaluate('e => e.files[0]?.name') == 'resume.pdf'
    assert await page.evaluate('window.searched && window.searchPrevented')
    assert not any('keyboard activation' in i.message for i in run.interventions)


def test_a_row_question_is_asked_for_its_own_row(store):
    run = ApplicationRun(job_url='https://example.wd1.myworkdayjobs.com/job', profile_snapshot=ApplicantProfile(language_proficiency=[Language(language='English'), Language(language='Chinese (Mandarin)')]))
    speaking = FormField('speaking', 'Speaking', '', 'select-one', group='language_proficiency', row=1)
    assert not ApplicationEngine(store).verify(run, run.profile_snapshot, [speaking], {'files': {}})
    assert run.interventions[0].question == 'Speaking — Chinese (Mandarin)'


@pytest.mark.parametrize('existing', ['', 'Existing employer'])
async def test_workday_native_profile_fields_do_not_wait_for_a_stalled_picker(context, store, existing):
    from core.automation.models import Experience
    html = f'''<div data-automation-id="myExperiencePage"><div data-intern-group="experience"><div data-intern-row>
    <label>Company<input value="{existing}"></label><label>Job Title<input></label>
    <label>I currently work here<input type="checkbox"></label></div></div>
    <button type="button" aria-haspopup="listbox">Unavailable picker</button></div>'''
    profile = ApplicantProfile(experience=[Experience(employer='Fictional Co', job_title='Engineer', current=True)])
    page = await open_fixture(context, 'workday', html)
    bridge, _, _, _, _ = await prepare(page, store, 'workday', profile)
    # No adapter start: an unrelated pending picker cannot hold these known native facts hostage.
    assert await page.get_by_label('Company', exact=True).input_value() == (existing or 'Fictional Co')
    assert await page.get_by_label('Job Title', exact=True).input_value() == ('' if existing else 'Engineer')
    assert await page.get_by_label('I currently work here', exact=True).is_checked() == (not existing)
    fields = (await bridge.command('scan'))['fields']
    assert {f['row'] for f in fields if f['group']=='experience'} == ({1} if existing else {0})


@pytest.mark.parametrize('reprepare', [False, True])
async def test_workday_cleared_file_input_keeps_digest_only_for_the_original_receipt(context, store, tmp_path, reprepare):
    import hashlib
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'fixture resume bytes')
    html = '''<div data-automation-id="myExperiencePage"><div role="group" aria-labelledby="Resume/CV-section">
    <h4 id="Resume/CV-section">Resume/CV</h4><input type=file onchange="this.files=new DataTransfer().files;window.finishUpload=()=>this.insertAdjacentHTML('afterend',`<div data-automation-id='file-upload-item'><span data-automation-id='file-upload-item-name'>resume.pdf</span><div data-automation-id='ariaLiveMessage' role='alert'>resume.pdf successfully uploaded</div><span data-automation-id='file-upload-successful'>Successfully Uploaded!</span></div>`)"></div></div>'''
    page = await open_fixture(context, 'workday', html)
    profile = ApplicantProfile(resume_path=str(resume))
    bridge, _, _, _, config = await prepare(page, store, 'workday', profile)
    await bridge.command('start')
    await page.wait_for_function('typeof window.finishUpload === "function"')
    [pending] = (await bridge.command('scan'))['fields']
    assert pending['file_digest'] == ''
    await page.evaluate('window.finishUpload()')
    await page.locator('[data-automation-id=file-upload-successful]').wait_for()
    [field] = (await bridge.command('scan'))['fields']
    digest = hashlib.sha256(resume.read_bytes()).hexdigest()
    assert field['file_digest'] == digest and not field['invalid']
    assert (await bridge.command('snapshot'))['errors'] == 0
    # Review pages may announce an upload without displaying the editing receipt's success icon.
    await page.locator('[data-automation-id=file-upload-successful]').evaluate('e=>{window.uploadSuccess=e;e.remove()}')
    assert (await bridge.command('snapshot'))['errors'] == 0
    await page.locator('[data-automation-id=file-upload-item]').evaluate('e=>e.append(window.uploadSuccess)')
    assert await page.locator('input[type=file]').evaluate('e=>e.files.length') == 0
    # A new runtime on resume must preserve proof for the unchanged accepted receipt.
    if reprepare:
        [field] = (await bridge.command('prepare', config))['fields']
        assert field['file_digest'] == digest
    # A replacement attachment with the same name is not the file we uploaded.
    await page.locator('[data-automation-id=file-upload-item]').evaluate('e=>e.replaceWith(e.cloneNode(true))')
    [field] = (await bridge.command('scan'))['fields']
    assert field['file_digest'] == ''


async def test_workday_route_normalization_rebinds_before_continuing(context, store):
    html = (FIXTURES / 'workday.html').read_text().replace('>Next</button>', '>Submit</button>')
    page = await open_fixture(context, 'workday', html)
    run = ApplicationRun(job_url=page.url)
    bridge = ExtensionBridge(page, run.id)
    changed = False
    async def normalize(name):
        nonlocal changed
        if name == 'start' and not changed:
            changed = True
            await page.evaluate("history.replaceState({}, '', location.pathname + '/apply')")
    commands = record_commands(bridge, before=normalize)
    await ApplicationEngine(store).start(run, profile_for('workday'), bridge)
    assert run.status == 'ready_for_review', run.interventions
    assert commands.count('prepare') == 2
    assert not run.submission_attempted


@pytest.mark.parametrize('keeps_changing', [False, True])
async def test_verification_retries_transient_changes_but_bounds_unstable_forms(context, store, keeps_changing):
    page = await open_fixture(context, 'greenhouse', greenhouse())
    run = ApplicationRun(job_url=page.url)
    bridge = ExtensionBridge(page, run.id)
    scans = 0
    async def change_during_readback(name):
        nonlocal scans
        if name == 'scan':
            scans += 1
            if scans == 2 or (keeps_changing and scans % 2 == 0):
                await page.locator('input').first.evaluate('e=>e.required=!e.required')
    commands = record_commands(bridge, before=change_during_readback)
    await ApplicationEngine(store).start(run, profile_for('greenhouse'), bridge)
    assert run.status == ('needs_input' if keeps_changing else 'ready_for_review'), run.interventions
    assert commands.count('prepare') == (4 if keeps_changing else 2)
    assert not run.submission_attempted
    if keeps_changing:
        assert any(i.kind == 'validation' for i in run.interventions)


async def test_workday_date_parts_commit_on_blur_and_expose_group_validation(context, store):
    html = '''<div data-automation-id="myExperiencePage"><div data-intern-group="experience"><div data-intern-row>
    <fieldset><legend>From*</legend><div data-automation-id="dateInputWrapper">
    <label>Month<input role="spinbutton" onblur="window.savedMonth=this.value"></label>
    <label>Year<input role="spinbutton" onblur="window.savedYear=this.value"></label>
    </div></fieldset></div></div></div>'''
    page = await open_fixture(context, 'workday', html)
    profile = ApplicantProfile(experience=[Experience(start_date='2026-05')])
    bridge, engine, run, _, config = await prepare(page, store, 'workday', profile)
    assert await page.evaluate('[window.savedMonth,window.savedYear]') == ['5', '2026']
    await page.locator('fieldset').evaluate('e=>e.insertAdjacentHTML("beforeend",`<p data-automation-id="inputAlert">The field From is required and must have a value.</p>`)')
    fields = [FormField(**f) for f in (await bridge.command('scan'))['fields']]
    assert all(f.invalid for f in fields)
    assert (await bridge.command('snapshot'))['errors']
    assert not engine.verify(run, profile, fields, config)


@pytest.mark.parametrize('replace,stop', [(False,False),(True,False),(True,True)])
async def test_workday_saved_resume_is_replaced_only_by_an_explicit_file_answer(context, store, tmp_path, replace, stop):
    import hashlib
    resume = tmp_path / 'new.pdf'
    resume.write_bytes(b'new fixture resume')
    html = '''<div data-automation-id=myExperiencePage><div aria-labelledby="Resume/CV-section" role=group>
    <input type=file onchange="this.insertAdjacentHTML('afterend',`<div data-automation-id='file-upload-item'><span data-automation-id='file-upload-item-name'>new.pdf</span><span data-automation-id='file-upload-successful'>Successfully Uploaded!</span></div>`);this.files=new DataTransfer().files">
    <div data-automation-id=file-upload-item><span data-automation-id=file-upload-item-name>old.pdf</span><span data-automation-id=file-upload-successful>Successfully Uploaded!</span>
    <button type=button data-automation-id=delete-file onclick="window.deletes=(window.deletes||0)+1;setTimeout(()=>this.parentElement.remove(),100)">Delete old.pdf</button></div>
    </div></div>'''
    page = await open_fixture(context, 'workday', html)
    if replace:
        store.save_answer(ApprovedAnswer(question='Resume', value=str(resume), scope='global'))
    bridge, _, _, _, _ = await prepare(page, store, 'workday', ApplicantProfile(resume_path=str(resume)))
    await bridge.command('start')
    if stop:
        await page.wait_for_function('window.deletes===1')
        await bridge.stop()
    await page.wait_for_timeout(350)
    [field] = (await bridge.command('scan'))['fields']
    assert await page.evaluate('window.deletes||0') == int(replace)
    if stop:
        assert field['value'] == '' and field['file_digest'] == ''
        return
    assert field['value'] == ('new.pdf' if replace else 'old.pdf')
    assert field['file_digest'] == (hashlib.sha256(resume.read_bytes()).hexdigest() if replace else '')


async def test_workday_reordered_saved_jobs_keep_their_own_profile_policies(context, store):
    html = '''<div data-automation-id=myExperiencePage><div data-intern-group=experience>
    <div data-intern-row><label>Company<input value="Second Co"></label><label>Job Title<input value="Tutor"></label><label>I currently work here<input type=checkbox checked></label></div>
    <div data-intern-row><label>Company<input value="First Co"></label><label>Job Title<input value="Intern"></label><label>I currently work here<input type=checkbox></label></div>
    </div></div>'''
    profile = ApplicantProfile(experience=[Experience(employer='First Co', job_title='Intern', current=False), Experience(employer='Second Co', job_title='Tutor', current=True)])
    page = await open_fixture(context, 'workday', html)
    bridge, _, _, _, _ = await prepare(page, store, 'workday', profile)
    fields = (await bridge.command('scan'))['fields']
    assert [(f['row'],f['value']) for f in fields if f['label']=='Company'] == [(1,'Second Co'),(0,'First Co')]
    assert await page.locator('input[type=checkbox]').evaluate_all('es=>es.map(e=>e.checked)') == [True,False]
    # An unrecognized populated row must not receive another job's checkbox or dates.
    await page.locator('input').first.fill('Unknown Co')
    fields = (await bridge.command('scan'))['fields']
    assert all(f['row'] >= 2 for f in fields[:3])
