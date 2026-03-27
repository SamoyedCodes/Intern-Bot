import nodriver as uc
from typing import Optional

class NodriverManager:
    """Manages the stealth CDP browser connection specifically to bypass strict WAFs."""
    def __init__(self, headless: bool = True, user_data_dir: str = "./nodriver_profile"):
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.browser: Optional[uc.Browser] = None
        
    async def start(self) -> uc.Browser:
        """Initializes the stealth browser and bypasses initial Cloudflare/DataDome challenges."""
        # nodriver patches undetected-chromedriver natively via low-level CDP
        self.browser = await uc.start(
            headless=self.headless,
            user_data_dir=self.user_data_dir
        )
        return self.browser

    async def stop(self):
        """Cleanly stops the CDP browser connection."""
        if self.browser:
            self.browser.stop()
