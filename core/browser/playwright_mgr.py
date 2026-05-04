from playwright.async_api import async_playwright, BrowserContext
from typing import Optional

class AsyncPlaywrightManager:
    """Manages the Playwright headless browser context for navigating ATS domains."""
    def __init__(self, headless: bool = True, user_data_dir: str = "./playwright_profile"):
        self.headless = headless
        self.user_data_dir = user_data_dir
        self._playwright = None
        self.context: Optional[BrowserContext] = None
        
    async def start(self) -> BrowserContext:
        """Initializes the browser and returns the persistent context."""
        self._playwright = await async_playwright().start()
        
        # Launch persistent context to preserve cookies and session states
        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled", # Raw evasion logic
            ],
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        return self.context

    async def stop(self):
        """Cleanly closes the persistent context to flush cookies/cache to disk."""
        if self.context:
            await self.context.close()
        if self._playwright:
            await self._playwright.stop()
