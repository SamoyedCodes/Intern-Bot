"""Real MV3 adapter fixtures; no vendor startup, server or mocked adapter scripts."""
import asyncio
import json
from pathlib import Path

import pytest

from core.automation.answers import resolve
from core.automation.extension_bridge import ExtensionBridge
from core.automation.engine import ApplicationEngine
from core.automation.models import ApplicantProfile, ApplicationRun, Experience
from core.automation.speedy_profile import translate
from core.automation.fields import FormField
from core.browser.playwright_mgr import AsyncPlaywrightManager
from core.storage.local_store import LocalStore

FIXTURES = Path(__file__).parent / 'fixtures' / 'speedyapply'
URLS = json.loads((FIXTURES / 'urls.json').read_text())
EXTENSION = Path(__file__).parents[1] / 'extension'


def profile_for(site):
    return ApplicantProfile(first_name='Ada', last_name='Example', email='ada@example.test', phone='5551234567',
        address_line1='123 Fictional St', city='Example City', postal_code='12345',
        experience=[Experience(job_title='Engineer', employer='Fictional Co', description='Built examples', start_date='2025-01')] if site == 'seek' else [])


async def with_extension(tmp_path, scenario):
    manager = AsyncPlaywrightManager(user_data_dir=str(tmp_path / 'browser'), extension_path=EXTENSION)
    try:
        context = await manager.start()
        await scenario(context, LocalStore(tmp_path / 'state.db'))
    finally:
        await manager.stop()


async def open_fixture(context, site, html=None, url=None):
    page = await context.new_page()
    body = html if html is not None else (FIXTURES / f'{site}.html').read_text()
    await page.route('**/*', lambda route: route.fulfill(body=body, content_type='text/html'))
    await page.goto(url or URLS[site])
    return page


async def prepare(page, store, site, profile=None, run=None):
    profile = profile or profile_for(site)
    run = run or ApplicationRun(job_url=page.url, auto_advance=False)
    bridge = ExtensionBridge(page, run.id)
    engine = ApplicationEngine(store)
    engine.bridge = bridge
    found = await bridge.discover()
    assert len(found['matches']) == 1, found
    assert found['matches'][0]['adapter']['id'] == site
    config = translate(profile, run, store.answers())
    config['adapter'] = site
    # These fixtures represent sites which already display a resume receipt.
    config['profile']['resumeData'] = {'fileName': 'fixture.pdf'}
    result = await bridge.command('prepare', config, binding=found['matches'][0])
    await engine.authorize(run, profile, [FormField(**f) for f in result['fields']])
    return bridge, engine, run, profile, config


@pytest.mark.parametrize('site', list(URLS))
def test_every_real_adapter_fills_and_stops(tmp_path, site):
    async def scenario(context, store):
        requests = []
        context.on('request', lambda request: requests.append(request.url))
        page = await open_fixture(context, site)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        bridge, engine, run, profile, config = await prepare(page, store, site)
        await bridge.command('start')
        snapshot = await engine.wait_for_section(run, profile)
        assert snapshot and snapshot['status'] != 'in-progress', (site, snapshot)
        assert not snapshot['problems'], (site, snapshot)
        assert not errors
        fields = [FormField(**f) for f in (await bridge.command('scan'))['fields']]
        assert len(fields) == 3, (site, fields)
        for field in fields:
            assert field.value == resolve(field, profile, run, []).value, (site, field)
        assert not any('speedyapply' in url.lower() or 'supabase' in url.lower() for url in requests)
        # No continuation or submission path executes without a desktop action command.
        assert not await page.evaluate('Boolean(window.submitted || window.advanced)')
        await bridge.stop()
        values = [(f.key, f.value) for f in fields]
        await asyncio.sleep(.4)
        assert [(f['key'], f['value']) for f in (await bridge.command('scan'))['fields']] == values
    asyncio.run(with_extension(tmp_path, scenario))


@pytest.mark.parametrize('site', list(URLS))
def test_every_adapter_validation_unknowns_and_existing_value_conflicts(tmp_path, site):
    async def scenario(context, store):
        page = await open_fixture(context, site)
        bridge, engine, run, profile, config = await prepare(page, store, site)
        await bridge.command('start')
        snapshot = await engine.wait_for_section(run, profile)
        assert snapshot and not snapshot['problems']
        fields = [FormField(**f) for f in (await bridge.command('scan'))['fields']]
        assert engine.verify(run, profile, fields, config)
        await bridge.stop()
        # Application-supplied validation must invalidate previously correct evidence.
        await page.evaluate('''() => {const roots=[document];for(let i=0;i<roots.length;i++)for(const e of roots[i].querySelectorAll('*'))if(e.shadowRoot)roots.push(e.shadowRoot);roots.flatMap(r=>[...r.querySelectorAll('input:not([type=hidden]),textarea')]).find(e=>e.getClientRects().length).setAttribute('aria-invalid','true');}''')
        invalid = [FormField(**f) for f in (await bridge.command('scan'))['fields']]
        assert not engine.verify(run, profile, invalid, config)
        assert any(a.disposition == 'needs_input' for a in run.fields.values())
        await page.evaluate('''() => {const form=document.querySelector('form')||document.body;const label=document.createElement('label');label.innerHTML='Fictional clearance code<input required>';form.append(label);}''')
        unknown = [FormField(**f) for f in (await bridge.command('scan'))['fields']]
        assert not engine.verify(run, profile, unknown, config)
        assert any(i.question == 'Fictional clearance code' for i in run.interventions)
        # Resume cannot overwrite a value the user put into an already visible field.
        await page.evaluate('''() => {const roots=[document];for(let i=0;i<roots.length;i++)for(const e of roots[i].querySelectorAll('*'))if(e.shadowRoot)roots.push(e.shadowRoot);const e=roots.flatMap(r=>[...r.querySelectorAll('input:not([type=hidden]),textarea')]).find(e=>e.getClientRects().length);e.removeAttribute('aria-invalid');e.value='USER VALUE';}''')
        bridge2, engine2, run2, profile2, _ = await prepare(page, store, site)
        await bridge2.command('start')
        await asyncio.sleep(2)
        observed = (await bridge2.command('scan'))['fields']
        assert any(f['value'] == 'USER VALUE' for f in observed), site
        await bridge2.stop()
    asyncio.run(with_extension(tmp_path, scenario))


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
}


@pytest.mark.parametrize('site', list(URLS))
def test_every_adapter_continuation_is_intercepted_or_handed_off(tmp_path, site):
    async def scenario(context,store):
        body=(FIXTURES/f'{site}.html').read_text()
        control=CONTROLS[site]
        if control:
            body=body.replace('</form>',control+'</form>',1) if '</form>' in body else body+control
        page=await open_fixture(context,site,body)
        await page.evaluate('''() => {window.navigationClicks=0;document.addEventListener('click',e=>{const button=e.composedPath().find(n=>n.matches?.('button,input[type=submit]'));if(button&&/submit|send application|^next$/i.test(button.innerText||button.value||'')){e.preventDefault();window.navigationClicks++;}},true);}''')
        bridge,engine,run,profile,_=await prepare(page,store,site)
        await bridge.command('start')
        snapshot=await engine.wait_for_section(run,profile)
        assert snapshot and not snapshot['problems'],(site,snapshot)
        assert await page.evaluate('window.navigationClicks')==0
        if site in {'sap-successfactors','jazzhr','freshteam','pinpoint'}:
            assert not snapshot['actions'] # This vendor branch hands continuation to the user.
        else:
            assert snapshot['actions'],(site,snapshot)
        await bridge.stop()
        if snapshot['actions']:
            try:
                await bridge.command('action',{'id':snapshot['actions'][0]['id']})
                assert False,'stopped action was accepted'
            except Exception as exc:
                assert 'failed' in str(exc).lower()
        assert await page.evaluate('window.navigationClicks')==0
    asyncio.run(with_extension(tmp_path,scenario))
