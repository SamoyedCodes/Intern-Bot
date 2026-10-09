"""Every real MV3 adapter against its local fixture: no vendor startup, server or mocked adapter scripts."""
import asyncio
import json

import pytest

from core.automation.answers import resolve
from core.automation.fields import FormField
from tests.support import FIXTURES, URLS, open_fixture, prepare

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
}
# These vendor branches hand continuation to the user instead of offering an action.
HANDOFF_SITES = {'sap-successfactors', 'jazzhr', 'freshteam', 'pinpoint'}


async def scan(bridge):
    return [FormField(**f) for f in (await bridge.command('scan'))['fields']]


@pytest.mark.parametrize('site', URLS)
async def test_every_adapter_fills_its_fields_and_stops(context, store, site):
    page = await open_fixture(context, site)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
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
    assert not await page.evaluate('Boolean(window.submitted || window.advanced)')
    await bridge.stop()
    await asyncio.sleep(.4)  # Deliberate: a stopped adapter must not write afterwards.
    assert [(f.key, f.value) for f in await scan(bridge)] == [(f.key, f.value) for f in fields]


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


@pytest.mark.parametrize('site', URLS)
async def test_every_adapter_continuation_is_intercepted_or_handed_off(context, store, site):
    body = (FIXTURES / f'{site}.html').read_text()
    if control := CONTROLS[site]:
        body = body.replace('</form>', control + '</form>', 1) if '</form>' in body else body + control
    page = await open_fixture(context, site, body)
    await page.evaluate(COUNT_NAVIGATION_CLICKS)
    bridge, engine, run, profile, _ = await prepare(page, store, site)
    await bridge.command('start')
    snapshot = await engine.wait_for_section(run, profile)
    assert snapshot and not snapshot['problems'], (site, snapshot)
    assert bool(snapshot['actions']) == (site not in HANDOFF_SITES), (site, snapshot)
    assert await page.evaluate('window.navigationClicks') == 0
    await bridge.stop()
    if snapshot['actions']:
        with pytest.raises(Exception, match='(?i)failed'):
            await bridge.command('action', {'id': snapshot['actions'][0]['id']})
    assert await page.evaluate('window.navigationClicks') == 0


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
