import asyncio
import os

import pytest
from playwright.async_api import async_playwright
from core.automation.privacy import BoundedRecovery
from core.storage.local_store import LocalStore

URL = "https://example.wd1.myworkdayjobs.com/job/Intern_R1"


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


def test_ai_recovery_does_not_send_network_or_enable_telemetry(tmp_path):
    async def scenario(page, store):
        assert not await BoundedRecovery().recover(page=page, profile={'password':'must-not-leak'})
        assert os.environ['ANONYMIZED_TELEMETRY'] == 'false'
        assert not BoundedRecovery.enabled
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
