import json
from types import SimpleNamespace

import pytest

from core.automation.models import ApplicationRun
from core.browser.playwright_mgr import AsyncPlaywrightManager

pytestmark = pytest.mark.browser
URL = 'https://example.wd1.myworkdayjobs.com/job/Intern_R1'


async def test_a_browser_profile_is_owned_by_one_session_at_a_time(tmp_path):
    first = AsyncPlaywrightManager(user_data_dir=str(tmp_path))
    second = AsyncPlaywrightManager(user_data_dir=str(tmp_path))
    try:
        context = await first.start()
        with pytest.raises(RuntimeError, match='already in use'):
            await second.start()
        page = context.pages[0]
        assert page.viewport_size == {'width': 1280, 'height': 800}
        assert await page.evaluate('navigator.webdriver') is False
        assert 'Chrome/' in await page.evaluate('navigator.userAgent')
        await first.stop()
        assert await second.start()
    finally:
        await second.stop()
        await first.stop()


async def test_session_cookies_are_restored_and_invalid_state_is_preserved(tmp_path):
    manager = AsyncPlaywrightManager(user_data_dir=str(tmp_path))
    saved = tmp_path / 'session-cookies.json'
    try:
        context = await manager.start()
        await context.add_cookies([{'name': 'fixture_session', 'value': 'fixture-only-token', 'url': URL, 'httpOnly': True, 'secure': True}])
        await manager.stop()
        assert saved.stat().st_mode & 0o777 == 0o600
        assert json.loads(saved.read_text())[0]['expires'] == -1
        context = await manager.start()
        assert any(c['name'] == 'fixture_session' and c['value'] == 'fixture-only-token' for c in await context.cookies(URL))
        await context.clear_cookies()
        await manager.stop()
        assert json.loads(saved.read_text()) == []
        saved.write_text('invalid state')
        with pytest.raises(json.JSONDecodeError):
            await manager.start()
        assert saved.read_text() == 'invalid state'
        assert manager.context is None and manager._lock is None  # A failed start releases the profile lock.
    finally:
        await manager.stop()


LISTING = 'https://careers.acme.test/jobs/42'
APPLY = 'https://boards.greenhouse.io/acme/jobs/1'


@pytest.mark.parametrize('listing, status, expected', [
    (f'<a href="{APPLY}?gh_src=site">Apply now</a>', 200, 'resolved'),
    (f'<a href="{APPLY}">Apply</a><a href="https://jobs.lever.co/acme/2">Apply for the Berlin role</a>', 200, 'choose'),
    ('<p>This job is no longer accepting applications.</p>', 200, 'closed'),
    ('Not found', 404, 'missing'),
])
async def test_a_careers_listing_is_followed_to_one_clear_application(context, store, listing, status, expected):
    from core.automation.service import AutomationService
    from tests.support import FIXTURES
    page = await context.new_page()
    async def serve(route):
        url = route.request.url
        body = listing if url.startswith(LISTING) else (FIXTURES / 'greenhouse.html').read_text().replace('<form', '<h1>Data Science Intern</h1><form', 1)
        await route.fulfill(status=status if url.startswith(LISTING) else 200, body=body, content_type='text/html')
    await page.route('**/*', serve)
    service = SimpleNamespace(hosts={}, store=store)
    service.describe = lambda run, page: AutomationService.describe(service, run, page)
    run = ApplicationRun(job_url=LISTING)
    problem, options = await AutomationService.open_job(service, run, page)
    if expected == 'resolved':
        assert problem == '' and run.listing_url == LISTING and run.job_url.startswith(APPLY) and page.url.startswith(APPLY)
        assert service.hosts[run.id] == 'boards.greenhouse.io'
        assert (run.company, run.role) == ('Acme', 'Data Science Intern')
    else:
        assert run.job_url == LISTING and not run.listing_url and service.hosts[run.id] == 'careers.acme.test'
        assert {'choose': 'more than one', 'closed': 'closed', 'missing': 'HTTP 404'}[expected] in problem
        assert options == ([APPLY, 'https://jobs.lever.co/acme/2'] if expected == 'choose' else [])
    await page.close()
