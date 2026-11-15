"""Every real MV3 adapter against its local fixture: no vendor startup, server or mocked adapter scripts."""
import asyncio
import json

import pytest

from core.automation.answers import resolve
from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.fields import FormField
from core.automation.models import ApplicationRun, ApprovedAnswer, Experience
from tests.support import FIXTURES, URLS, open_fixture, prepare, profile_for

# The first visible text control, including inside open shadow roots.
FIRST_VISIBLE_INPUT = '''(() => {const roots=[document];for(let i=0;i<roots.length;i++)for(const e of roots[i].querySelectorAll('*'))if(e.shadowRoot)roots.push(e.shadowRoot);return roots.flatMap(r=>[...r.querySelectorAll('input:not([type=hidden]),textarea')]).find(e=>e.getClientRects().length);})()'''
COUNT_NAVIGATION_CLICKS = '''() => {window.navigationClicks=0;document.addEventListener('click',e=>{const button=e.composedPath().find(n=>n.matches?.('button,input[type=submit]'));if(button&&/submit|send application|^next$/i.test(button.innerText||button.value||'')){e.preventDefault();window.navigationClicks++;}},true);}'''

# A continuation control per vendor, as its real form renders it; None means the fixture already has one or the vendor has none.
CONTROLS = {
    'workday': None,
    'greenhouse': '<button type="button" id="submit_app">Submit Application</button>',
    'lever': '<button type="button" id="btn-submit">Submit Application</button>',
    'ashby': '<button type="button" class="ashby-application-form-submit-button">Submit Application</button>',
    'sap-successfactors': None,
    'icims': None,
    'workable': '<button type="button" data-ui="apply-button">Submit Application</button>',
    'rippling': '<button type="submit">Submit Application</button>',
    'breezy': '<button type="button"><span>Submit Application</span></button>',
    'jazzhr': None,
    'smartrecruiters': '<button type="button" data-test="footer-next">Next</button>',
    'paylocity': '<button type="button" data-automation-id="btnSubmit">Submit Application</button>',
    'freshteam': None,
    'dover': '<button type="submit">Submit Application</button>',
    'pinpoint': None,
    'comeet': '<button type="button">Submit</button>',
    'gusto': '<input type="submit" value="Submit Application">',
    'polymer': '<button type="button">Submit Application</button>',
    'adp': None,
    'jobvite': '<button type="button" aria-label="Send Application">Send Application</button>',
    'ultipro': '<div data-automation="btn-submit"></div><script>document.querySelector("[data-automation=btn-submit]").attachShadow({mode:"open"}).innerHTML="<button type=button>Submit Application</button>";</script>',
    'tesla': '<button type="submit">Submit Application</button>',
    'tiktok': '<button type="button" data-test="applyResumeBtn">Submit Application</button>',
    'eightfold': '<button type="button" data-test-id="position-apply-button">Submit Application</button>',
    'seek': None,
    'bamboohr': '<button type="button">Submit Application</button>',
    'phenom': '<button type="button" class="btn-submit">Submit Application</button>',
    'dayforce': '<button type="button" test-id="application-next-step">Next</button>',
    'monee': None,
    'internsg': None,
    'formsg': None,
    'eightfold-pcs': None,
}
# These vendor branches hand continuation to the user instead of offering an action.
HANDOFF_SITES = {'sap-successfactors', 'jazzhr', 'freshteam', 'pinpoint'}


async def scan(bridge):
    return [FormField(**f) for f in (await bridge.command('scan'))['fields']]


@pytest.mark.parametrize('site', URLS)
async def test_every_adapter_fills_its_fields_and_continues_only_on_command(context, store, site):
    body = (FIXTURES / f'{site}.html').read_text()
    if control := CONTROLS[site]:
        body = body.replace('</form>', control + '</form>', 1) if '</form>' in body else body + control
    page = await open_fixture(context, site, body)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    await page.evaluate(COUNT_NAVIGATION_CLICKS)
    bridge, engine, run, profile, _ = await prepare(page, store, site)
    await bridge.command('start')
    snapshot = await engine.wait_for_section(run, profile)
    assert snapshot and snapshot['status'] != 'in-progress' and not snapshot['problems'], (site, snapshot)
    assert not errors
    fields = await scan(bridge)
    assert len(fields) == 3, (site, fields)
    for field in fields:
        assert field.value == resolve(field, profile, run, []).value, (site, field)
    # No continuation or submission path executes without a desktop action command.
    assert bool(snapshot['actions']) == (site not in HANDOFF_SITES), (site, snapshot)
    assert not await page.evaluate('Boolean(window.submitted || window.advanced || window.navigationClicks)')
    await bridge.stop()
    await asyncio.sleep(.4)  # Deliberate: a stopped adapter must not write afterwards.
    assert [(f.key, f.value) for f in await scan(bridge)] == [(f.key, f.value) for f in fields]
    if snapshot['actions']:
        with pytest.raises(Exception, match='(?i)failed'):
            await bridge.command('action', {'id': snapshot['actions'][0]['id']})
    assert await page.evaluate('window.navigationClicks') == 0


@pytest.mark.parametrize('site', URLS)
async def test_every_adapter_reports_validation_unknowns_and_keeps_user_values(context, store, site):
    page = await open_fixture(context, site)
    bridge, engine, run, profile, config = await prepare(page, store, site)
    await bridge.command('start')
    snapshot = await engine.wait_for_section(run, profile)
    assert snapshot and not snapshot['problems'], (site, snapshot)
    assert engine.verify(run, profile, await scan(bridge), config)
    await bridge.stop()
    # Application-supplied validation invalidates previously correct evidence.
    await page.evaluate(f"() => {FIRST_VISIBLE_INPUT}.setAttribute('aria-invalid', 'true')")
    assert not engine.verify(run, profile, await scan(bridge), config)
    assert any(a.disposition == 'needs_input' for a in run.fields.values())
    await page.evaluate("() => {const label=document.createElement('label');label.innerHTML='Fictional clearance code<input required>';(document.querySelector('form')||document.body).append(label);}")
    assert not engine.verify(run, profile, await scan(bridge), config)
    assert any(i.question == 'Fictional clearance code' for i in run.interventions)
    # A restarted adapter never overwrites a value the user typed into a visible field.
    await page.evaluate(f"() => {{const e = {FIRST_VISIBLE_INPUT}; e.removeAttribute('aria-invalid'); e.value = 'USER VALUE';}}")
    bridge, engine, run, profile, _ = await prepare(page, store, site)
    engine.SECTION_POLLS = 30  # Some adapters never settle on a conflict; ~3s is long enough to see an overwrite.
    await bridge.command('start')
    await engine.wait_for_section(run, profile)
    assert any(f.value == 'USER VALUE' for f in await scan(bridge)), site
    await bridge.stop()


async def test_no_adapter_contacts_its_vendor_from_pages_or_the_extension_worker(fresh_context, store):
    context = fresh_context
    page_requests = []
    context.on('request', lambda request: page_requests.append(request.url))
    ready = next((w for w in context.service_workers if w.url.startswith('chrome-extension://')), None) or await context.wait_for_event(
        'serviceworker', predicate=lambda w: w.url.startswith('chrome-extension://'), timeout=5000)
    assert await ready.evaluate('typeof internBot === "object"')
    # Observe the worker's own network domain through CDP before any adapter starts.
    session = await context.new_cdp_session(context.pages[0])
    targets = await session.send('Target.getTargets')
    worker = next(t for t in targets['targetInfos'] if t['type'] == 'service_worker' and t['url'].startswith('chrome-extension://'))
    attached = await session.send('Target.attachToTarget', {'targetId': worker['targetId'], 'flatten': False})
    worker_requests, responses = [], []
    def on_message(data):
        if data.get('sessionId') != attached['sessionId']:
            return
        message = json.loads(data['message'])
        if message.get('method') == 'Network.requestWillBeSent':
            worker_requests.append(message['params']['request']['url'])
        if message.get('id') == 1:
            responses.append(message)
    session.on('Target.receivedMessageFromTarget', on_message)
    await session.send('Target.sendMessageToTarget', {'sessionId': attached['sessionId'], 'message': json.dumps({'id': 1, 'method': 'Network.enable'})})
    for _ in range(30):
        if responses:
            break
        await asyncio.sleep(.05)
    assert responses and 'error' not in responses[0], 'Worker Network domain was not enabled'
    for site in URLS:
        page = await open_fixture(context, site)
        bridge, engine, run, profile, _ = await prepare(page, store, site)
        await bridge.command('start')
        snapshot = await engine.wait_for_section(run, profile)
        assert snapshot and not snapshot['problems'], (site, snapshot)
        await bridge.stop()
        await page.close()
    await session.detach()
    assert worker_requests == []
    assert not any('speedyapply' in url.lower() or 'supabase' in url.lower() for url in page_requests)
    assert set(page_requests) <= {url.split('#')[0] for url in URLS.values()}


SUCCESSFACTORS_FORM = '''<a id="30:_expandAllSections" class="expandCollapseTxt" role="button" href="javascript:void(0)" onclick="open_=true;render()">Expand all sections</a>
<div id="form"></div><span role="button" id="236:_submitBtn" onclick="window.submitted=true">Apply</span>
<script>
let open_=false, doc='', notice='';
window.rebuilds=0;
function render(){
  document.getElementById('form').innerHTML=`<div id="1:sectionContent" style="display:${open_?'block':'none'}">
  <div class="RCMFormField attachmentField"><label><span class="requiredField">*</span>&nbsp;Resume</label>
    <div id="51:_attachDownloadLabel" style="display:${doc?'block':'none'}">${doc}<br>(14/11/2026)</div>
    <span role="button" class="addAttachments" onclick="document.body.insertAdjacentHTML('beforeend','<div role=dialog id=popup><input type=file class=fileUpload onchange=received(this)></div>')">+</span></div>
  <div class="RCMFormField"><label><span class="requiredField">*</span>&nbsp;City</label><input type="text"></div>
  <div class="RCMFormField"><label><span class="requiredField">*</span>&nbsp;Notice Period</label>
    <input class="rcmpaginatedselectinput" role="combobox" aria-controls="9:_listSelect" value="${notice}"
      onclick="const l=document.getElementById('9:_listSelect');l.style.display=l.style.display==='none'?'block':'none'">
    <ul id="9:_listSelect" role="listbox" style="display:none">
      <li role="option" onclick="notice='1 Month';this.closest('.RCMFormField').querySelector('input').value=notice;this.parentElement.style.display='none'">1 Month</li>
      <li role="option">Immediate</li></ul></div></div>`;
}
// Like SuccessFactors: the document arrives, the popup closes, and the whole form is rebuilt without what was typed.
function received(input){doc=input.files[0].name;document.getElementById('popup').remove();setTimeout(()=>{window.rebuilds++;render();},300);}
render();
</script>'''


async def test_successfactors_uploads_through_its_popup_and_fills_the_rebuilt_form(context, store, tmp_path):
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF fictional resume')
    page = await open_fixture(context, 'sap-successfactors', SUCCESSFACTORS_FORM,
                              url='https://career44.sapsf.com/portalcareer?company=fictional&career_ns=job_application')
    profile = profile_for('sap-successfactors').model_copy(update={'resume_path': str(resume)})
    run = ApplicationRun(job_url=page.url, auto_advance=False)
    store.save_answer(ApprovedAnswer(question='Notice Period', value='1 Month', scope_key=run.id))
    run = await ApplicationEngine(store).start(run, profile, ExtensionBridge(page, run.id))
    assert run.status == 'ready_for_review', run.interventions
    assert await page.evaluate('window.rebuilds') == 1  # Sent once; the rebuilt receipt is verified, not uploaded again.
    assert await page.locator('.RCMFormField input[type=text]').input_value() == 'Example City'
    assert await page.locator('input.rcmpaginatedselectinput').input_value() == '1 Month'
    assert not await page.evaluate('Boolean(window.submitted)')


# CPF Board's form: a repeating section whose rows line up with the profile's jobs, a date picker two shadow roots down that
# reads DD/MM/YYYY, a question answered with ARIA radios under a star-first label, and picklists of 100 options a page that
# filter as you type (institutions, and calling codes listed as bare numbers).
CPF_FORM = '''<h2 id="115:headerLabel"><button>My Work Experience</button></h2>
<div id="115:sectionContent" class="sectionContent" role="group" aria-labelledby="115:headerLabel">
  <div class="rcmSectionComponent">
    <div class="RCMFormField"><label><span class="requiredField">*</span>&nbsp;Organisation</label><input type="text"></div>
    <div class="RCMFormField"><label><span class="requiredField">*</span>&nbsp;From</label><div class="datePicker"><div><ui5-date-picker-test title="From"></ui5-date-picker-test></div></div></div>
    <div role="button" title="Delete Row">Remove</div></div>
  <div role="button" id="115:_addRowBtn">Add</div></div>
<div id="64:sectionContent" class="sectionContent">
  <div class="RCMFormField"><label><span class="requiredField">*</span>&nbsp;Mobile Phone Country Code</label>__CODE__</div>
  <div class="RCMFormField"><label><span class="requiredField">*</span>&nbsp;Institution</label>__SCHOOL__</div>
  <div class="RCMFormField"><label id="124:" class="rcmFormQuestionLabel"><span class="requiredField">*</span>&nbsp;Are you able to commit to a full-time 5 day internship?</label>
    <div class="radioGroup" role="radiogroup" aria-labelledby="124:">
      <span role="radio" aria-checked="false" aria-labelledby="y" onclick="tick(this)"></span><label id="y">Yes</label>
      <span role="radio" aria-checked="false" aria-labelledby="n" onclick="tick(this)"></span><label id="n">No</label></div></div></div>
<span role="button" id="194:_submitBtn" onclick="window.submitted=true">Apply</span>
<script>
function tick(r){r.parentElement.querySelectorAll('[role=radio]').forEach(o=>o.setAttribute('aria-checked',String(o===r)));}
const lists={code:[...Array(300)].map((_,i)=>String(i+1)),school:[...Array(150)].map((_,i)=>'Academy '+i).concat('Example University (EU)')};
function show(id,q){const all=lists[id].filter(o=>o.toLowerCase().includes(q.toLowerCase()));
  document.getElementById(id+'_list').innerHTML=all.slice(0,100).map(o=>`<li role="option" onclick="choose('${id}','${o}')">${o}</li>`).join('');}
function choose(id,o){document.getElementById(id).value=o;document.getElementById(id+'_list').innerHTML='';}
class Inner extends HTMLElement{connectedCallback(){this.attachShadow({mode:'open'}).innerHTML='<input type="text" placeholder="DD/MM/YYYY">';
  this.shadowRoot.firstChild.value=this.getRootNode().host.value;this.shadowRoot.firstChild.onchange=e=>{this.getRootNode().host.value=e.target.value;};}}
class Picker extends HTMLElement{value='01/06/2026';connectedCallback(){this.attachShadow({mode:'open'}).innerHTML='<ui5-inner-test class="ui5-date-picker-input"></ui5-inner-test>';}}
customElements.define('ui5-inner-test',Inner);customElements.define('ui5-date-picker-test',Picker);
</script>'''.replace('__CODE__', '''<input class="rcmpaginatedselectinput" role="combobox" id="code" aria-controls="code_list"
    onclick="const l=document.getElementById('code_list');l.innerHTML?l.innerHTML='':show('code','')" onkeyup="show('code',this.value)"><ul id="code_list" role="listbox"></ul>''').replace(
    '__SCHOOL__', '''<input class="rcmpaginatedselectinput" id="school" aria-controls="school_list"
    onclick="const l=document.getElementById('school_list');l.innerHTML?l.innerHTML='':show('school','')" onkeyup="show('school',this.value)"><ul id="school_list" role="listbox"></ul>''')


async def test_successfactors_fills_a_cpf_style_form_from_the_profiles_rows(context, store):
    page = await open_fixture(context, 'sap-successfactors', CPF_FORM, url='https://career44.sapsf.com/portalcareer?company=fictional&career_ns=job_application')
    profile = profile_for('sap-successfactors').model_copy(update={'phone_country_code': '+65', 'phone_number': '55512345', 'country': 'Singapore',
        'experience': [Experience(employer='Fictional Co', start_date='June 2026')]})
    run = ApplicationRun(job_url=page.url, auto_advance=False)
    store.save_answer(ApprovedAnswer(question='Mobile Phone Country Code', fact='phone_country_code', scope='global'))
    store.save_answer(ApprovedAnswer(question='Institution', value='Example University', scope_key=run.id))
    store.save_answer(ApprovedAnswer(question='Are you able to commit to a full-time 5 day internship?', value='Yes', scope_key=run.id))
    run = await ApplicationEngine(store).start(run, profile, ExtensionBridge(page, run.id))
    assert run.status == 'ready_for_review', [(i.question, i.message) for i in run.interventions]
    assert await page.locator('.rcmSectionComponent > .RCMFormField > input').input_value() == 'Fictional Co'
    assert await page.locator('#code').input_value() == '65'
    assert await page.locator('#school').input_value() == 'Example University (EU)'
    assert await page.evaluate('[...document.querySelectorAll("[role=radio]")].map(r => r.getAttribute("aria-checked"))') == ['true', 'false']
    # The date SuccessFactors already held falls in the profile's month, so it is kept as it is.
    assert next(f for f in run.fields.values() if f.label == 'From').disposition == 'verified'
    assert await page.evaluate('document.querySelector("ui5-date-picker-test").value') == '01/06/2026'


# FormSG as it renders: a downshift dropdown whose pick shows beside its emptied input, and an attachment whose file input is
# replaced by a "File attached" receipt.
FORMSG_FORM = '''<form>
<div role="group"><label id="q4-label" for="q4"><div><span>4.</span>Identity Type</div></label>
  <div data-group="true"><div aria-hidden="true"><p><span id="shown"></span></p></div>
  <input role="combobox" id="q4" aria-controls="downshift-0-menu" aria-labelledby="q4-label" required aria-required="true" value=""
    placeholder="Select an option" onclick="menu()" oninput="menu(this.value)"></div></div>
<div role="group"><label id="q5-label" for="q5"><div><span>5.</span>Upload your resume</div><p>Documents must be uploaded as .PDF.</p></label>
  <div id="drop"><input type="file" id="q5" required accept=".pdf" onchange="attached(this)"></div></div>
<button type="button" onclick="window.submitted=true"><span><span>End of form.</span>Submit now</span></button>
</form><ul role="listbox" id="downshift-0-menu"></ul>
<script>
const choices=['Singapore Citizen','Singapore Permanent Resident','Foreigner'];
function menu(q=''){document.getElementById('downshift-0-menu').innerHTML=choices.filter(c=>c.toLowerCase().includes(q.toLowerCase())).map(c=>`<li role="option" onclick="pick('${c}')">${c}</li>`).join('');}
function pick(c){document.getElementById('shown').textContent=c;document.getElementById('q4').value='';document.getElementById('downshift-0-menu').innerHTML='';}
function attached(input){const f=input.files[0];document.getElementById('drop').outerHTML=`<div tabindex="0" aria-required="true"><div><span>File attached: ${f.name} with file size of ${f.size} B</span><button type="button" aria-label="Click to remove file">x</button></div></div>`;}
</script>'''


async def test_formsg_picks_dropdown_options_and_verifies_the_attachment_receipt(context, store, tmp_path):
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF fictional resume')
    page = await open_fixture(context, 'formsg', FORMSG_FORM)
    profile = profile_for('formsg').model_copy(update={'resume_path': str(resume)})
    run = ApplicationRun(job_url=page.url, auto_advance=False)
    store.save_answer(ApprovedAnswer(question='Identity Type', value='Foreigner', scope_key=run.id))
    run = await ApplicationEngine(store).start(run, profile, ExtensionBridge(page, run.id))
    assert run.status == 'ready_for_review', run.interventions
    assert await page.locator('#shown').inner_text() == 'Foreigner'
    assert await page.get_by_text('File attached: resume.pdf').count() == 1
    assert not await page.evaluate('Boolean(window.submitted)')


# What live FormSG forms showed (LSC, MAS): a mobile field that spaces its digits beside a country picker, a date field declaring
# pattern="\d*", one question repeated under each period's statement, and an attachment renumbered by a question revealed above it.
FORMSG_QUIRKS = r'''<form>
<div role="group"><label id="m-label" for="m"><div><span>1.</span>Mobile Number</div></label>
  <div><select aria-label="Country selector"><option>Afghanistan</option><option selected>Singapore</option></select>
  <input id="m" autocomplete="tel" placeholder="8123 4567" aria-labelledby="m-label" oninput="this.value=this.value.replace(/\D/g,'').replace(/(\d{4})(?=\d)/g,'$1 ')"></div></div>
<div role="group"><label id="d-label" for="d"><div><span>2.</span>Date of Consent</div></label>
  <span aria-live="assertive">No date selected</span><input id="d" inputmode="numeric" pattern="\d*" placeholder="dd/mm/yyyy" aria-labelledby="d-label"></div>
<div><p>January 2027 - June 2027</p></div>
<div role="group"><label id="c1-label" for="c1"><div><span>3.</span>First Choice</div></label><input id="c1" aria-labelledby="c1-label"></div>
<div><p>May 2027 - July 2027</p></div>
<div role="group"><label id="c2-label" for="c2"><div><span>4.</span>First Choice</div></label><input id="c2" aria-labelledby="c2-label"></div>
<div role="group"><label id="t-label" for="t"><div><span id="tn">5.</span>Attachment (Transcripts)</div></label>
  <div id="drop"><input type="file" id="t" accept=".pdf" onchange="attached(this)"></div></div>
<button type="button" onclick="window.submitted=true"><span><span>End of form.</span>Submit now</span></button>
</form>
<script>
function attached(input){const f=input.files[0];document.getElementById('tn').textContent='6.';
  document.getElementById('drop').outerHTML=`<div tabindex="0"><div><span>File attached: ${f.name} with file size of ${f.size} B</span><button type="button" aria-label="Click to remove file">x</button></div></div>`;}
</script>'''


async def test_formsg_reads_spaced_mobiles_dates_repeated_questions_and_renumbered_attachments(context, store, tmp_path):
    transcript = tmp_path / 'transcript.pdf'
    transcript.write_bytes(b'%PDF fictional transcript')
    page = await open_fixture(context, 'formsg', FORMSG_QUIRKS)
    profile = profile_for('formsg').model_copy(update={'country': 'Singapore'})
    run = ApplicationRun(job_url=page.url, auto_advance=False)
    for question, value in [('Date of Consent (dd/mm/yyyy)', '15/11/2026'), ('January 2027 - June 2027 — First Choice', 'Project A'),
                            ('May 2027 - July 2027 — First Choice', 'Project B'), ('Attachment (Transcripts)', str(transcript))]:
        store.save_answer(ApprovedAnswer(question=question, value=value, scope_key=run.id))
    run = await ApplicationEngine(store).start(run, profile, ExtensionBridge(page, run.id))
    assert run.status == 'ready_for_review', run.interventions
    assert await page.locator('#m').input_value() == '5551 2345 67'
    assert [await page.locator(s).input_value() for s in ('#d', '#c1', '#c2')] == ['15/11/2026', 'Project A', 'Project B']
    assert await page.get_by_text('File attached: transcript.pdf').count() == 1
    assert not await page.evaluate('Boolean(window.submitted)')


# Eightfold as Micron's careers site renders it: calling codes as "🇸🇬 (+65) Singapore", and radios whose group names no label.
# Eightfold as Micron's and PayPal's careers sites render it: calling codes as "🇸🇬 (+65) Singapore", radios whose group names no label,
# and a résumé that waits behind a consent dialog (kept hidden in the page until a file is picked), then is read and rewrites the form.
EIGHTFOLD_FORM = '''<meta charset="utf-8"><code id="pcsx-data" hidden>{}</code><form>
<div><div><label id="Resume_resume_label" for="Resume_resume">Upload your resume</label></div>
  <div><div role="status"></div><span><input type="file" id="resume" accept=".pdf" style="display: none;" onchange="picked(this)"><div id="files"></div></span></div></div>
<div id="contact"><label for="Contact_Information_firstname">First Name</label><input id="Contact_Information_firstname">
  <label for="Contact_Information_email">Email</label><input id="Contact_Information_email"></div>
<input role="combobox" aria-label="Country code" aria-controls="list-5" id="input-7" value="" onclick="showCodes()" oninput="showCodes(this.value)">
<span>Have you previously been employed by any Micron Company?</span>
<div role="radiogroup" aria-labelledby="missing_legend">
  <div><input type="radio" name="prev" id="prev-true" value="true" readonly aria-label="Yes, Have you previously been employed by any Micron Company?"><label for="prev-true" aria-hidden="true"><span>Yes</span></label></div>
  <div><input type="radio" name="prev" id="prev-false" value="false" readonly aria-label="No, Have you previously been employed by any Micron Company?"><label for="prev-false" aria-hidden="true"><span>No</span></label></div>
</div>
<div role="radiogroup" aria-labelledby="missing_visibility">
  <div><input type="radio" name="vis" id="vis-all" readonly aria-label="Any company recruiter worldwide, Make My Profile Visible to"><label for="vis-all" aria-hidden="true"><span>Any company recruiter worldwide</span></label></div>
  <div><input type="radio" name="vis" id="vis-local" readonly aria-label="Any company recruiter in my country/region, Make My Profile Visible to"><label for="vis-local" aria-hidden="true"><span>Any company recruiter in my country / region</span></label></div>
</div>
<button type="button" data-test-id="submitApplicationButton" onclick="window.submitted=true">Submit application</button>
</form><div id="list-5" role="listbox"></div>
<div role="dialog" aria-modal="true" aria-labelledby="consent-title" id="consent" style="visibility: hidden"><h2 id="consent-title">Data Privacy Agreement</h2>
  <button type="button" onclick="this.parentElement.style.visibility='hidden'">Cancel</button><button type="button" onclick="agreed()">I Agree</button></div>
<script>
const codes=['🇦🇩 (+376) Andorra','🇸🇬 (+65) Singapore','🇺🇸 (+1) United States'];
function showCodes(q=''){document.getElementById('list-5').innerHTML=codes.filter(c=>c.toLowerCase().includes(q.toLowerCase())).map(c=>`<button type="button" role="option" onclick="choose('${c}')">${c}</button>`).join('');}
function choose(c){document.getElementById('input-7').value=c;document.getElementById('list-5').innerHTML='';}
let pending='';
function picked(input){pending=input.files[0].name;input.value='';document.getElementById('consent').style.visibility='visible';}
function agreed(){
  document.getElementById('consent').style.visibility='hidden';window.uploads=(window.uploads||0)+1;
  const files=document.getElementById('files');files.innerHTML=`<ul><li><span title="${pending}">${pending}</span><span>Matching…</span></li></ul>`;
  setTimeout(()=>{
    files.innerHTML=`<ul><li><span title="${pending}">${pending}</span><button type="button" aria-label="Delete file ${pending}">x</button></li></ul>`;
    document.querySelector('[role=status]').textContent='File upload completed successfully';
    // The résumé is read and the contact fields are rendered again with its values.
    document.getElementById('contact').innerHTML='<label for="Contact_Information_firstname">First Name</label><input id="Contact_Information_firstname" value="Jonathan"><label for="Contact_Information_email">Email</label><input id="Contact_Information_email" value="parsed@example.com">';
  },400);}
</script>'''


async def test_eightfold_fills_after_its_resume_consent_upload_and_rewrite(context, store, tmp_path):
    resume = tmp_path / 'resume.pdf'
    resume.write_bytes(b'%PDF fictional resume')
    page = await open_fixture(context, 'eightfold-pcs', EIGHTFOLD_FORM)
    profile = profile_for('eightfold-pcs').model_copy(update={'phone_country_code': '+65', 'phone_number': '91234567', 'country': 'Singapore', 'resume_path': str(resume)})
    run = ApplicationRun(job_url=page.url, auto_advance=False)
    store.save_answer(ApprovedAnswer(question='Have you previously been employed by any Micron Company?', value='No', scope_key=run.id))
    # Vodafone's option text differs from its aria-label ("country / region" against "country/region").
    store.save_answer(ApprovedAnswer(question='Make My Profile Visible to', value='Any company recruiter in my country / region', scope_key=run.id))
    run = await ApplicationEngine(store).start(run, profile, ExtensionBridge(page, run.id))
    # The picked résumé waits behind the consent dialog, which is asked; nothing is uploaded until it is approved.
    assert 'Data Privacy Agreement' in [i.question for i in run.interventions], run.interventions
    assert not await page.evaluate('window.uploads')
    store.save_answer(ApprovedAnswer(question='Data Privacy Agreement', value=True, scope_key=run.id))
    run = await ApplicationEngine(store).start(run, profile, ExtensionBridge(page, run.id))
    assert run.status == 'ready_for_review', run.interventions
    assert await page.evaluate('window.uploads') == 1
    # The résumé's rewrite is replaced by the profile's values.
    assert [await page.locator(s).input_value() for s in ('#Contact_Information_firstname', '#Contact_Information_email')] == ['Ada', 'ada@example.test']
    assert await page.locator('#vis-local').is_checked() and await page.locator('#prev-false').is_checked()
    assert await page.locator('#input-7').input_value() == '🇸🇬 (+65) Singapore'
    assert not await page.evaluate('Boolean(window.submitted)')


# Qualcomm's and Microsoft's Eightfold sites ask you to sign in first, in a dialog shown a moment after the page loads.
EIGHTFOLD_SIGN_IN = '''<code id="pcsx-data" hidden>{}</code><script>setTimeout(() => document.body.insertAdjacentHTML('beforeend',
  '<div role="dialog" aria-modal="true"><h1>Sign in</h1><label for="em">Email</label><input type="email" id="em"><button type="button">Continue</button></div>'), DELAY);</script>'''


@pytest.mark.parametrize('delay', [0, 800])
async def test_eightfold_hands_a_sign_in_dialog_to_you_without_typing_into_it(context, store, delay):
    page = await open_fixture(context, 'eightfold-pcs', EIGHTFOLD_SIGN_IN.replace('DELAY', str(delay)))
    run = ApplicationRun(job_url=page.url, auto_advance=False)
    run = await ApplicationEngine(store).start(run, profile_for('eightfold-pcs'), ExtensionBridge(page, run.id))
    assert [i.kind for i in run.interventions] == ['verification'], run.interventions
    assert await page.locator('#em').input_value() == ''


@pytest.mark.parametrize('site, page_text', [
    ('formsg', '<h2>Thank you for filling out the form.</h2><button>Submit another response</button>'),
    ('eightfold-pcs', '<h1>Thank you for your application, Ada!</h1><p>We will review it shortly.</p>'),
])
async def test_platform_confirmation_pages_are_recognized(context, site, page_text):
    from core.automation.engine import receipt_shown
    page = await open_fixture(context, site, page_text)
    assert await receipt_shown(page, page.url)
    form = await open_fixture(context, site)
    assert not await receipt_shown(form, form.url)


async def test_a_saved_recipe_does_not_compete_with_an_adapter_in_another_frame(context):
    # Micron's form adds a profile view in an iframe after its résumé upload, on a host the user had taught a recipe for.
    from core.automation.recipes import Recipe
    page = await context.new_page()
    async def serve(route):
        body = '<form><label>Notes<input></label></form>' if '/profile/' in route.request.url else (FIXTURES / 'eightfold-pcs.html').read_text() + '<iframe src="/profile/1"></iframe>'
        await route.fulfill(body=body, content_type='text/html')
    await page.route('**/*', serve)
    await page.goto(URLS['eightfold-pcs'])
    await page.wait_for_function("document.querySelector('iframe').contentDocument?.querySelector('form')")
    recipe = Recipe(host='careers.example.test', origin='taught', approved=True)
    found = await ExtensionBridge(page, 'run').discover([recipe.model_dump()])
    assert [m['adapter']['id'] for m in found['matches']] == ['eightfold-pcs']
