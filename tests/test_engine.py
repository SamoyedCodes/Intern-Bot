"""ApplicationEngine against the real extension and local fixtures: verification, submission and stop guarantees."""
import asyncio
from types import SimpleNamespace

import pytest
from playwright.async_api import Error as PlaywrightError

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
    await page.route(lambda url: url.endswith(('/li/track', '/wday/save')), lambda route: hung.append(route))  # Held open, like a stuck beacon.
    await page.evaluate("() => { for (const url of ['https://www.linkedin.com/li/track', '/wday/save']) fetch(url, {method: 'POST'}).catch(() => {}) }")
    await until(lambda: len(hung) == 2)
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
    # Checking Choice reveals Extra fact mid-verification, so the first pass hands off instead of trusting a moving form.
    await engine.start(run, profile_for('greenhouse'), ExtensionBridge(page, run.id))
    assert run.status == 'needs_input' and [i.kind for i in run.interventions] == ['validation'], run.interventions
    await engine.resume(run, profile_for('greenhouse'), ExtensionBridge(page, run.id))
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
    request = next(i for i in run.interventions if i.question == 'Speaking')
    assert request.options == ['1 - Slight', '2 - Fair', '3 - Fluent']
    store.save_answer(ApprovedAnswer(question='Speaking', value='2 - Fair', scope_key=run.id))
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


async def test_an_approved_radio_is_clicked_so_the_site_registers_it(context, store, monkeypatch):
    monkeypatch.setattr(ApplicationEngine, 'SECTION_POLLS', 20)  # The rest of the Workday page never appears.
    radios = ''.join(f'<div><div><input type=radio name=previous id={o} onclick="window.picked=`{o}`"></div><label for={o}>{o}</label></div>' for o in ('Yes', 'No'))
    page = await open_fixture(context, 'workday', f'<div data-automation-id=applyFlowMyInfoPage><fieldset><legend>Have you worked with us before?</legend>{radios}</fieldset></div>')
    run = ApplicationRun(job_url=page.url)
    store.save_answer(ApprovedAnswer(question='Have you worked with us before?', value='No', scope_key=run.id, profile_name=run.profile_name))
    await ApplicationEngine(store).start(run, ApplicantProfile(), ExtensionBridge(page, run.id))
    assert await page.evaluate('window.picked') == 'No'


def test_a_reformatted_phone_number_still_verifies(store):
    run = ApplicationRun(job_url='https://example.wd1.myworkdayjobs.com/job')
    field = FormField('phone', 'Phone Number', '', 'text', value='9876 5411')
    assert ApplicationEngine(store).verify(run, ApplicantProfile(phone_country_code='+65', phone_number='98765411'), [field], {'files': {}})
