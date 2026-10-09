import json

import pytest

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
