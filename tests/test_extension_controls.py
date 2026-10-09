import asyncio
import json

import pytest

from core.automation.extension_bridge import ExtensionBridge
from core.automation.engine import ApplicationEngine
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer
from tests.test_extension_adapters import FIXTURES, URLS, open_fixture, prepare, profile_for, with_extension


def greenhouse(button=True, extra='', handler="window.submissions=(window.submissions||0)+1;document.body.innerHTML='<h1>Application submitted</h1>'"):
    body=(FIXTURES/'greenhouse.html').read_text()
    return body.replace('</form>', extra + (f'<button type="button" id="submit_app" onclick="{handler}">Submit Application</button>' if button else '') + '</form>')


def test_submission_is_persisted_before_click_and_never_retried(tmp_path):
    async def scenario(context, store):
        page=await open_fixture(context,'greenhouse',greenhouse())
        run=ApplicationRun(job_url=page.url,auto_submit=True)
        checkpoints=[]
        engine=ApplicationEngine(store,lambda r:checkpoints.append((r.submission_attempted,r.submission_confirmed)))
        await engine.start(run,profile_for('greenhouse'),ExtensionBridge(page,run.id))
        assert run.submission_confirmed and run.pipeline=='applied',run.interventions
        assert (True,False) in checkpoints
        assert await page.evaluate('window.submissions')==1
        await engine.resume(store.get_run(run.id),profile_for('greenhouse'),ExtensionBridge(page,run.id))
        assert await page.evaluate('window.submissions')==1
    asyncio.run(with_extension(tmp_path,scenario))


def test_manual_default_unknown_required_and_ambiguous_receipt(tmp_path):
    async def scenario(context,store):
        for case in ('manual','unknown','ambiguous','hidden_receipt'):
            extra='<label>Fictional fact<input required></label>' if case=='unknown' else ''
            handler="window.submissions=(window.submissions||0)+1" if case=='ambiguous' else "window.submissions=(window.submissions||0)+1;document.body.innerHTML='<h1 hidden>Application submitted</h1>'" if case=='hidden_receipt' else "window.submissions=(window.submissions||0)+1"
            page=await open_fixture(context,'greenhouse',greenhouse(extra=extra,handler=handler))
            run=ApplicationRun(job_url=page.url,auto_submit=case!='manual')
            engine=ApplicationEngine(store)
            await engine.start(run,profile_for('greenhouse'),ExtensionBridge(page,run.id))
            assert not run.submission_confirmed
            if case in {'manual','unknown'}:
                assert not run.submission_attempted,run.interventions
                assert not await page.evaluate('Boolean(window.submissions)')
                assert run.status==('ready_for_review' if case=='manual' else 'needs_input')
            else:
                assert run.submission_attempted
                await engine.resume(run,profile_for('greenhouse'),ExtensionBridge(page,run.id))
                assert await page.evaluate('window.submissions')==1
            await page.close()
    asyncio.run(with_extension(tmp_path,scenario))


def test_pause_cancel_during_active_adapter_and_late_controls(tmp_path):
    async def scenario(context,store):
        for cancel in (False,True):
            html=greenhouse().replace('id="application"','id="loading"')
            page=await open_fixture(context,'greenhouse',html)
            run=ApplicationRun(job_url=page.url,auto_submit=True)
            engine=ApplicationEngine(store)
            task=asyncio.create_task(engine.start(run,profile_for('greenhouse'),ExtensionBridge(page,run.id)))
            await asyncio.sleep(.3)
            engine.cancel() if cancel else engine.pause()
            await task
            await page.evaluate('document.querySelector("form").id="application"')
            await asyncio.sleep(1)
            assert await page.locator('#first_name').input_value()==''
            assert not await page.evaluate('Boolean(window.submissions)')
            assert run.status==('cancelled' if cancel else 'needs_input')
            await page.close()
    asyncio.run(with_extension(tmp_path,scenario))


def test_stale_document_and_run_commands_are_rejected(tmp_path):
    async def scenario(context,store):
        page=await open_fixture(context,'greenhouse')
        bridge,_,run,_,_=await prepare(page,store,'greenhouse')
        stale=json.loads(json.dumps(bridge.binding))
        other,_,_,_,_=await prepare(page,store,'greenhouse',run=run)
        assert other.binding['token']!=stale['token']
        try:
            await bridge.command('start')
            assert False,'old generation accepted'
        except Exception as exc:
            assert 'Expired application' in str(exc)
        await page.reload()
        with pytest.raises(Exception):
            await other.command('start')
        assert await page.locator('#first_name').input_value()==''
    asyncio.run(with_extension(tmp_path,scenario))


def test_frames_are_selected_without_releasing_profiles_to_other_documents(tmp_path):
    async def scenario(context,store):
        page=await context.new_page()
        async def route(request):
            if 'boards.greenhouse.io' in request.request.url:
                await request.fulfill(body=greenhouse(),content_type='text/html')
            else:
                await request.fulfill(body='<h1>Employer</h1><label>Newsletter<input id=news></label><iframe src="'+URLS['greenhouse']+'"></iframe>',content_type='text/html')
        await page.route('**/*',route)
        await page.goto('https://careers.example.test/apply')
        run=ApplicationRun(job_url=page.url)
        await ApplicationEngine(store).start(run,profile_for('greenhouse'),ExtensionBridge(page,run.id))
        assert run.status=='ready_for_review',run.interventions
        assert await page.locator('#news').input_value()==''
        assert await page.frames[1].locator('#first_name').input_value()=='Ada'
        # Two matching frames require a handoff, not an arbitrary choice.
        await page.evaluate('(url)=>{const frame=document.createElement("iframe");frame.src=url;document.body.append(frame)}',URLS['greenhouse'])
        await asyncio.sleep(.5)
        run2=ApplicationRun(job_url=page.url)
        await ApplicationEngine(store).start(run2,profile_for('greenhouse'),ExtensionBridge(page,run2.id))
        assert run2.status=='needs_input'
        assert 'More than one' in run2.interventions[0].message
        assert await page.frames[2].locator('#first_name').input_value()==''
    asyncio.run(with_extension(tmp_path,scenario))


def test_upload_mime_readback_conflict_and_unsupported_type(tmp_path):
    async def scenario(context,store):
        resume=tmp_path/'fictional.docx';resume.write_bytes(b'fictional-document-payload')
        for accept,existing in [('.docx',False),('.pdf',False),('.docx',True)]:
            extra=f'<div id="s3_upload_for_resume"><label>Resume<input type=file accept="{accept}" onchange="this.closest(\'#s3_upload_for_resume\').querySelector(\'[role=status]\').textContent=this.files[0].name+\' uploaded\'"></label><span role=status></span></div>'
            page=await open_fixture(context,'greenhouse',greenhouse(extra=extra))
            if existing:
                await page.locator('input[type=file]').set_input_files({'name':'fictional.docx','mimeType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','buffer':b'different bytes'})
            profile=profile_for('greenhouse');profile.resume_path=str(resume)
            run=ApplicationRun(job_url=page.url)
            await ApplicationEngine(store).start(run,profile,ExtensionBridge(page,run.id))
            if accept=='.docx' and not existing:
                assert run.status=='ready_for_review',run.interventions
                assert await page.locator('input[type=file]').evaluate('e=>e.files[0].type')=='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            else:
                assert run.status=='needs_input'
                assert not run.submission_attempted
            await page.close()
    asyncio.run(with_extension(tmp_path,scenario))


def test_worker_restart_rebinds_without_restarting_adapter(tmp_path):
    async def scenario(context,store):
        page=await open_fixture(context,'greenhouse',greenhouse())
        bridge,engine,run,profile,_=await prepare(page,store,'greenhouse')
        await bridge.command('start')
        await engine.wait_for_section(run,profile)
        binding=bridge.binding.copy()
        session=await context.new_cdp_session(page)
        await session.send('ServiceWorker.enable')
        targets=await session.send('Target.getTargets')
        worker=next(t for t in targets['targetInfos'] if t['type']=='service_worker' and 'chrome-extension://' in t['url'])
        await asyncio.wait_for(session.send('Target.closeTarget', {'targetId': worker['targetId']}),5)
        for _ in range(30):
            if not context.service_workers:break
            await asyncio.sleep(.1)
        snapshot=await bridge.command('snapshot')
        assert bridge.binding==binding
        assert snapshot['status'] in {'autofill-complete','action-pending'}
        assert not await page.evaluate('Boolean(window.submissions)')
        await bridge.stop()
        await session.detach()
    asyncio.run(with_extension(tmp_path,scenario))


def test_saved_credentials_use_only_authorized_authentication_and_never_sqlite(tmp_path):
    async def scenario(context,store):
        html='''<div data-automation-id="signInPage"><label>Email<input autocomplete=email></label><label>Password<input type=password></label><button type=button data-automation-id=signInSubmitButton onclick="window.logins=(window.logins||0)+1">Sign In</button></div>'''
        page=await open_fixture(context,'workday',html)
        run=ApplicationRun(job_url=page.url)
        engine=ApplicationEngine(store)
        credential={'username':'fictional@example.test','password':'fixture-only-secret'}
        await engine.start(run,ApplicantProfile(),ExtensionBridge(page,run.id),credential)
        assert await page.evaluate('window.logins')==1
        assert run.authentication_attempted
        await engine.resume(run,ApplicantProfile(),ExtensionBridge(page,run.id),credential)
        assert await page.evaluate('window.logins')==1
        assert b'fixture-only-secret' not in store.path.read_bytes()
        worker=context.service_workers[0]
        stored=await worker.evaluate('chrome.storage.session.get(null)')
        assert 'fixture-only-secret' not in json.dumps(stored)
    asyncio.run(with_extension(tmp_path,scenario))


def test_rerenders_conditionals_delayed_submit_and_approved_answers(tmp_path):
    async def scenario(context,store):
        html=greenhouse(extra='''<label>Choice<input type=checkbox onchange="if(this.checked&&!document.querySelector('#conditional')){const l=document.createElement('label');l.innerHTML='Extra fact<input id=conditional required>';this.closest('form').append(l)}"></label><script>setTimeout(()=>document.querySelector('#submit_app').disabled=false,800)</script>''').replace('id="submit_app"','id="submit_app" disabled')
        page=await open_fixture(context,'greenhouse',html)
        run=ApplicationRun(job_url=page.url)
        store.save_answer(ApprovedAnswer(question='Choice',value=True,scope_key=run.id))
        store.save_answer(ApprovedAnswer(question='Extra fact',value='Explicit fact',scope_key=run.id))
        engine=ApplicationEngine(store)
        await engine.start(run,profile_for('greenhouse'),ExtensionBridge(page,run.id))
        if run.status=='needs_input':
            await engine.resume(run,profile_for('greenhouse'),ExtensionBridge(page,run.id))
        assert run.status=='ready_for_review',run.interventions
        assert await page.locator('#conditional').input_value()=='Explicit fact'
        await page.locator('#first_name').evaluate('e=>{const copy=e.cloneNode();copy.value="";e.replaceWith(copy)}')
        await engine.resume(run,profile_for('greenhouse'),ExtensionBridge(page,run.id))
        assert await page.locator('#first_name').input_value()=='Ada'
        assert not await page.evaluate('Boolean(window.submissions)')
    asyncio.run(with_extension(tmp_path,scenario))


def test_missing_selector_wait_is_bounded_and_intervenes(tmp_path):
    async def scenario(context,store):
        page=await open_fixture(context,'greenhouse','<h1>Unrecognized form</h1>')
        run=ApplicationRun(job_url=page.url)
        await asyncio.wait_for(ApplicationEngine(store).start(run,profile_for('greenhouse'),ExtensionBridge(page,run.id)),25)
        assert run.status=='needs_input'
        assert not run.submission_attempted
    asyncio.run(with_extension(tmp_path,scenario))


def test_multi_section_review_and_auto_advance_require_reconciliation(tmp_path):
    async def scenario(context,store):
        for wrong in (False,True):
            html=(FIXTURES/'workday.html').read_text().replace('>Next</button>', ''' onclick="review()">Next</button>''')
            html+='''<script>window.submissions=0;function review(){const value=document.querySelector('input').value;document.body.innerHTML=`<div data-automation-id="reviewJobApplicationPage"><dl><dt>First Name</dt><dd>${VALUE}</dd><dt>Last Name</dt><dd>Example</dd><dt>Email</dt><dd>ada@example.test</dd></dl><button type="button" data-automation-id="bottom-navigation-next-button" onclick="window.submissions++;document.body.innerHTML='<h1>Application submitted</h1>'">Submit Application</button></div>`;}</script>'''.replace('${VALUE}', 'Wrong' if wrong else '${value}')
            page=await open_fixture(context,'workday',html)
            run=ApplicationRun(job_url=page.url,auto_submit=True)
            await ApplicationEngine(store).start(run,profile_for('workday'),ExtensionBridge(page,run.id))
            if wrong:
                assert run.status=='needs_input' and not run.submission_attempted,run.interventions
                assert await page.evaluate('window.submissions')==0
            else:
                assert run.submission_confirmed,run.interventions
                assert await page.evaluate('window.submissions')==1
            await page.close()
    asyncio.run(with_extension(tmp_path,scenario))


def test_cover_letter_text_and_file_support_without_vendor_cloud(tmp_path):
    async def scenario(context,store):
        cover=tmp_path/'cover.txt';cover.write_text('Fictional cover letter')
        for as_file in (False,True):
            extra='<label>Cover Letter<input type=file accept=".txt" onchange="this.parentElement.querySelector(\'[role=status]\').textContent=this.files[0].name+\' uploaded\'"><span role=status></span></label>' if as_file else '<label>Cover Letter<textarea></textarea></label>'
            page=await open_fixture(context,'greenhouse',greenhouse(extra=extra))
            profile=profile_for('greenhouse');profile.cover_letter_path=str(cover);profile.cover_letter='Explicit letter text'
            run=ApplicationRun(job_url=page.url)
            await ApplicationEngine(store).start(run,profile,ExtensionBridge(page,run.id))
            assert run.status=='ready_for_review',run.interventions
            assert not run.submission_attempted
            await page.close()
    asyncio.run(with_extension(tmp_path,scenario))


def test_actual_workday_repeated_rows_resume_and_extra_rows(tmp_path):
    from core.automation.models import Experience, Education
    async def scenario(context, store):
        page = await open_fixture(context, 'workday', (FIXTURES/'workday-rows.html').read_text())
        profile = ApplicantProfile(experience=[
            Experience(job_title='Engineer', employer='Fictional One', description='Built examples'),
            Experience(job_title='Intern', employer='Fictional Two', description='Tested examples')],
            education=[Education(school='Fictional College', gpa='3.8'), Education(school='Second College', gpa='3.9')])
        run = ApplicationRun(job_url=page.url, auto_advance=False)
        bridge = ExtensionBridge(page, run.id)
        engine = ApplicationEngine(store)
        await engine.start(run, profile, bridge)
        assert len(run.fields) == 10, run.interventions
        assert all(f.disposition == 'verified' for f in run.fields.values()), run.interventions
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
    asyncio.run(with_extension(tmp_path, scenario))


def test_application_isolation_and_same_document_navigation_stop_writes(tmp_path):
    async def scenario(context, store):
        first = await open_fixture(context, 'greenhouse')
        second = await open_fixture(context, 'greenhouse', url='https://boards.greenhouse.io/other/jobs/2')
        profile = profile_for('greenhouse'); profile.first_name = 'Grace'
        one, engine1, run1, profile1, _ = await prepare(first, store, 'greenhouse')
        two, engine2, run2, profile2, _ = await prepare(second, store, 'greenhouse', profile=profile)
        await one.command('start'); await two.command('start')
        await engine1.wait_for_section(run1, profile1); await engine2.wait_for_section(run2, profile2)
        assert await first.locator('#first_name').input_value() == 'Ada'
        assert await second.locator('#first_name').input_value() == 'Grace'
        cross_run = ExtensionBridge(first, run2.id); cross_run.binding = one.binding
        with pytest.raises(Exception, match='Expired application'):
            await cross_run.command('start')
        await one.stop(); await two.stop()
        late = greenhouse().replace('id="application"', 'id="loading"')
        third = await open_fixture(context, 'greenhouse', late, url='https://boards.greenhouse.io/third/jobs/3')
        bridge, _, _, _, _ = await prepare(third, store, 'greenhouse')
        await bridge.command('start')
        await third.evaluate("location.hash='another-document';document.querySelector('form').id='application'")
        await asyncio.sleep(.5)
        snapshot = await bridge.command('snapshot')
        assert not snapshot['live']
        assert await third.locator('#first_name').input_value() == ''
        assert not await third.evaluate('Boolean(window.submissions)')
    asyncio.run(with_extension(tmp_path, scenario))


def test_immediate_preclick_recheck_blocks_changed_form(tmp_path):
    async def scenario(context, store):
        page = await open_fixture(context, 'greenhouse', greenhouse())
        run = ApplicationRun(job_url=page.url, auto_submit=True)
        bridge = ExtensionBridge(page, run.id)
        command = bridge.command
        async def changed(command_name, payload=None, binding=None):
            if command_name == 'action':
                assert store.get_run(run.id).submission_attempted
                await page.evaluate("document.querySelector('#first_name').value='Unexpected value'")
            return await command(command_name, payload, binding)
        bridge.command = changed
        await ApplicationEngine(store).start(run, profile_for('greenhouse'), bridge)
        assert run.submission_attempted and not run.submission_confirmed
        assert run.status == 'needs_input'
        assert not await page.evaluate('Boolean(window.submissions)')
    asyncio.run(with_extension(tmp_path, scenario))


def test_workday_language_dropdowns_and_explicit_boolean_select(tmp_path):
    from core.automation.models import Language
    async def scenario(context, store):
        html = '''<div data-automation-id="myExperiencePage"><h2>My Experience</h2>
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
        page = await open_fixture(context, 'workday', html)
        profile = ApplicantProfile(language_proficiency=[Language(language='English', fluent=True)])
        run = ApplicationRun(job_url=page.url, auto_advance=False)
        await ApplicationEngine(store).start(run, profile, ExtensionBridge(page, run.id))
        assert len(run.fields) == 2 and all(f.disposition == 'verified' for f in run.fields.values()), run.interventions
        assert await page.get_by_role('button', name='Language', exact=True).inner_text() == 'English'
        assert await page.locator('input[type=checkbox]').is_checked()
        page2 = await open_fixture(context, 'greenhouse', greenhouse(extra='<div id="custom_fields"><div class="field"><label>Do you require sponsorship?<select><option value="">Select One</option><option>Yes</option><option>No</option></select></label></div></div>'), url='https://boards.greenhouse.io/second/jobs/2')
        profile2 = profile_for('greenhouse');profile2.requires_sponsorship = False
        run2 = ApplicationRun(job_url=page2.url)
        # The original Greenhouse question helper discovers and selects this exact profile fact.
        await ApplicationEngine(store).start(run2, profile2, ExtensionBridge(page2, run2.id))
        assert not run2.submission_attempted
        assert run2.status == 'ready_for_review', run2.interventions
        assert await page2.locator('select').input_value() == 'No'
    asyncio.run(with_extension(tmp_path, scenario))


def test_pause_after_prepare_prevents_even_approved_answer_writes(tmp_path):
    async def scenario(context, store):
        page = await open_fixture(context, 'greenhouse', greenhouse())
        run = ApplicationRun(job_url=page.url)
        store.save_answer(ApprovedAnswer(question='First name', value='Approved name', scope_key=run.id))
        bridge = ExtensionBridge(page, run.id)
        engine = ApplicationEngine(store)
        command = bridge.command
        async def pause_prepared(name, payload=None, binding=None):
            result = await command(name, payload, binding)
            if name == 'prepare':
                engine.pause()
            return result
        bridge.command = pause_prepared
        await engine.start(run, profile_for('greenhouse'), bridge)
        assert run.status == 'needs_input'
        assert await page.locator('#first_name').input_value() == ''
        assert not run.submission_attempted
    asyncio.run(with_extension(tmp_path, scenario))


def test_apply_label_is_never_treated_as_unauthorized_continuation(tmp_path):
    async def scenario(context, store):
        body = (FIXTURES/'tesla.html').read_text() + '<button type="submit" onclick="window.submissions=(window.submissions||0)+1">Apply</button>'
        page = await open_fixture(context, 'tesla', body)
        run = ApplicationRun(job_url=page.url)
        await ApplicationEngine(store).start(run, profile_for('tesla'), ExtensionBridge(page, run.id))
        assert run.status == 'ready_for_review', run.interventions
        assert not run.submission_attempted and not await page.evaluate('Boolean(window.submissions)')
    asyncio.run(with_extension(tmp_path, scenario))
