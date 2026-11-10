from types import SimpleNamespace

import pytest

from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.journey import ApplicationJourney
from core.automation.models import ApplicationRun, InterventionRequest
from core.automation.service import AutomationService
from tests.support import profile_for
from tests.test_accounts import SAP, signup

LISTING = 'https://careers.example.test/job/42'


def test_http_redirect_responses_keep_the_selected_request_lineage():
    run = ApplicationRun(job_url=LISTING)
    journey = ApplicationJourney(run, SimpleNamespace())
    class Request:
        def __init__(self, previous=None):
            self.redirected_from = previous
    initial = Request()
    journey.requests.add(initial)
    journey.arrived(SimpleNamespace(request=Request(Request(initial)), url=SAP))
    assert journey.permits(SAP)


async def journey_fixture(context, store, body, redirect=False):
    async def serve(route):
        if route.request.method == 'POST':
            return await route.fulfill(body=f'<script>location.replace({SAP!r})</script>', content_type='text/html')
        if '/talentcommunity/apply/42' in route.request.url:
            return await route.fulfill(body=f'<script>location.replace({SAP!r})</script>', content_type='text/html')
        if route.request.url == LISTING:
            if redirect:
                return await route.fulfill(body=f'<script>location.replace({SAP!r})</script>', content_type='text/html')
            return await route.fulfill(body=body, content_type='text/html; charset=utf-8')
        await route.fulfill(body=signup(), content_type='text/html; charset=utf-8')
    await context.route('**/*', serve)
    page = await context.new_page()
    run = ApplicationRun(job_url=LISTING)
    journey = ApplicationJourney(run, page)
    await journey.install()
    bridge = ExtensionBridge(page, run.id)
    bridge.journey = journey
    service = SimpleNamespace(store=store, hosts={}, journeys={run.id: journey})
    service.describe = lambda run, page: AutomationService.describe(service, run, page)
    return run, journey, bridge, service


@pytest.mark.parametrize('control', ['link', 'button', 'popup', 'duplicate-listing-links', 'post-handoff'])
async def test_apply_can_cross_domains_through_links_buttons_and_popups(fresh_context, store, control):
    body = f'<a href="{SAP}">Apply now</a>' if control == 'link' else f'''<button onclick="{'window.open' if control == 'popup' else 'location.assign'}('{SAP}')">Apply now</button>'''
    if control == 'duplicate-listing-links':
        body = '<a href="/talentcommunity/apply/42">Apply now »</a>' * 2
    if control == 'post-handoff':
        body = '<form method=POST action="https://career44.sapsf.com/careers"><input name=company value=fictional type=hidden><input name=career_job_req_id value=42 type=hidden><button>Apply now »</button></form>'
    run, journey, bridge, service = await journey_fixture(fresh_context, store, body)
    if control == 'post-handoff':
        journey.data_entered = True  # The public routing-only POST is also needed after a previous sign-in.
    problem, _ = await AutomationService.open_job(service, run, bridge.page)
    bridge.sync_page()
    assert problem == '' and journey.permits(bridge.page.url)
    assert 'career44.sapsf.com' in bridge.page.url and run.listing_url == LISTING
    await bridge.page.get_by_role('heading', name='Create an Account').wait_for()
    store.put('auto_create_accounts', True)
    await ApplicationEngine(store).start(run, profile_for('sap-successfactors'), bridge)
    assert run.registration_attempted and run.interventions[-1].kind == 'activation'


async def test_initial_listing_redirect_is_discovered_without_a_hostname_error(fresh_context, store):
    run, journey, bridge, service = await journey_fixture(fresh_context, store, '', redirect=True)
    problem, _ = await AutomationService.open_job(service, run, bridge.page)
    assert problem == '' and journey.permits(bridge.page.url)
    assert run.listing_url == LISTING and 'requestParams' not in run.job_url


@pytest.mark.parametrize('destination', ['https://unrelated.example.test/signup', SAP.replace('company=fictional', 'company=other')])
async def test_unrelated_navigation_is_readable_but_never_receives_credentials(fresh_context, store, vault, destination):
    run, journey, bridge, service = await journey_fixture(fresh_context, store, f'<a href="{SAP}">Apply now</a>')
    await AutomationService.open_job(service, run, bridge.page)
    await bridge.page.goto(destination)
    assert not journey.permits(destination)
    store.put('auto_create_accounts', True)
    await ApplicationEngine(store).start(run, profile_for('sap-successfactors'), bridge)
    assert not run.registration_attempted and not vault.logins.items
    assert await bridge.page.locator('input[type=password]').first.input_value() == ''
    assert 'left the selected employer' in run.interventions[-1].message


async def test_verification_observer_only_queues_a_resume_after_visible_success(context, store):
    from tests.support import open_fixture
    page = await open_fixture(context, 'sap-successfactors', '<button>Sign Out</button>', url=SAP)
    run = ApplicationRun(job_url=SAP, status='needs_input', interventions=[InterventionRequest(kind='activation', message='Verify email')])
    store.save_run(run)
    bridge = ExtensionBridge(page, run.id)
    bridge.journey = ApplicationJourney(run, page)
    ready = []
    service = SimpleNamespace(store=store, sessions={run.id: (None, bridge)}, resume_ready=SimpleNamespace(emit=ready.append))
    await AutomationService.watch_verification(service, run.id)
    assert len(ready) == 1 and ready[0].status == 'queued' and ready[0].verification_continued
    assert not store._vault().logins.items


async def test_page_scripts_cannot_grant_themselves_an_apply_journey(fresh_context, store):
    run, journey, bridge, service = await journey_fixture(fresh_context, store, '<h1>Selected job</h1>')
    await AutomationService.open_job(service, run, bridge.page)
    await bridge.page.evaluate("internBotApplicationIntent('not-the-private-click-token')")
    await bridge.page.goto('https://unrelated.example.test/signup')
    assert not journey.permits(bridge.page.url)


async def test_an_unselected_popup_cannot_replace_the_application_tab(fresh_context, store):
    run, journey, bridge, service = await journey_fixture(fresh_context, store, '<h1>Selected job</h1>')
    await AutomationService.open_job(service, run, bridge.page)
    original = bridge.page
    async with fresh_context.expect_page() as opened:
        await original.evaluate("window.open('https://unrelated.example.test/')")
    popup = await opened.value
    await popup.wait_for_load_state()
    await popup.goto(LISTING)
    assert journey.page == original


async def test_cross_domain_post_cannot_forward_entered_credentials(fresh_context, store):
    body = '<form method=POST action="https://unrelated.example.test/collect"><input name=password type=password value=fixture-secret><button>Apply now</button></form>'
    run, journey, bridge, service = await journey_fixture(fresh_context, store, body)
    await bridge.page.goto(LISTING)
    journey.data_entered = True
    failed = []
    bridge.page.on('requestfailed', lambda r: failed.append(r.failure))
    await bridge.page.get_by_role('button', name='Apply now').click()
    assert failed == ['net::ERR_BLOCKED_BY_CLIENT']


async def test_login_that_loses_the_job_returns_through_the_original_listing(fresh_context, store, vault):
    from tests.support import FIXTURES
    home = 'https://career44.sapsf.com/career?company=fictional&career_ns=candidate_home'
    signed_in = False
    html = signup().replace("show('create');</script>", "show('sign_in');</script>").replace("show('application')", "location.assign('" + home + "')")
    application = '<button>Sign Out</button>' + (FIXTURES / 'sap-successfactors.html').read_text()
    async def serve(route):
        nonlocal signed_in
        if route.request.url == LISTING:
            body = f'<a href="{SAP}">Apply now</a>'
        elif route.request.url == home:
            signed_in = True
            body = '<button>Sign Out</button><h1>Candidate home</h1>'
        else:
            body = application if signed_in else html
        await route.fulfill(body=body, content_type='text/html')
    await fresh_context.route('**/*', serve)
    page = await fresh_context.new_page()
    run = ApplicationRun(job_url=LISTING)
    journey = ApplicationJourney(run, page)
    await journey.install()
    bridge = ExtensionBridge(page, run.id)
    bridge.journey = journey
    service = SimpleNamespace(store=store, hosts={}, journeys={run.id: journey})
    service.describe = lambda r,p: AutomationService.describe(service,r,p)
    returns = []
    async def reopen():
        returns.append(True)
        run.job_url = run.listing_url
        return await AutomationService.open_job(service, run, journey.page)
    journey.reopen_job = reopen
    await AutomationService.open_job(service, run, page)
    vault.save_credential(SAP, 'ada@example.test', 'SavedFixture1!')
    engine = ApplicationEngine(store)
    engine.SECTION_POLLS = 2
    await engine.start(run, profile_for('sap-successfactors'), bridge)
    assert returns == [True] and signed_in
    assert await bridge.page.locator('#fName').input_value() == 'Ada'

