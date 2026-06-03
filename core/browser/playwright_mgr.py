import subprocess
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext
from typing import Optional

class AsyncPlaywrightManager:
    """Manages the Playwright headless browser context for navigating ATS domains."""
    def __init__(self, headless: bool = True, user_data_dir: str = "./playwright_profile"):
        self.headless = headless
        self.user_data_dir = str(Path(user_data_dir).resolve())
        self._playwright = None
        self.context: Optional[BrowserContext] = None

    async def start(self) -> BrowserContext:
        """Initializes the browser and returns the persistent context."""
        self._kill_orphaned_browsers()
        self._clear_stale_singleton_files()
        self._playwright = await async_playwright().start()

        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            # Let Playwright use its own UA so the header matches the real
            # navigator properties. A mismatched UA triggers bot detection.
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )

        # Hide navigator.webdriver from detection scripts
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        return self.context

    def _kill_orphaned_browsers(self):
        """Kill any leftover Chromium processes using this profile directory."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", self.user_data_dir],
                capture_output=True, text=True, timeout=5,
            )
            for pid in result.stdout.strip().splitlines():
                try:
                    subprocess.run(["kill", pid.strip()], timeout=5)
                except Exception:
                    pass
        except Exception:
            pass

    def _clear_stale_singleton_files(self):
        """Remove Chromium SingletonLock/Socket/Cookie files left by unclean shutdowns."""
        profile = Path(self.user_data_dir)
        if not profile.is_dir():
            return
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            lock = profile / name
            if lock.exists():
                try:
                    lock.unlink()
                except OSError:
                    pass

    async def stop(self):
        """Cleanly closes the persistent context to flush cookies/cache to disk."""
        if self.context:
            await self.context.close()
        if self._playwright:
            await self._playwright.stop()
