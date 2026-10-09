"""Persistent browser ownership without process searches or lock-file deletion."""
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext


class AsyncPlaywrightManager:
    def __init__(self, headless: bool = True, user_data_dir: str = "./data/browser/default", executable_path=None, browser="chromium", extension_path=None):
        if browser not in {"chromium", "chrome", "firefox"}:
            raise ValueError("Choose Chromium, Chrome or Firefox.")
        if extension_path and browser != "chromium":
            raise ValueError("Local adapters require bundled Chromium.")
        self.extension_path = str(Path(extension_path).resolve()) if extension_path else None
        self.browser = browser
        self.headless = headless
        self.user_data_dir = str(Path(user_data_dir).resolve())
        self.executable_path = executable_path
        self._playwright = None
        self._lock = None
        self._session_ready = False
        self.context: Optional[BrowserContext] = None

    async def start(self) -> BrowserContext:
        if self.context is not None:
            return self.context
        directory = Path(self.user_data_dir)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        self._lock = open(directory / ".intern-bot.lock", "a")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            self._lock = None
            raise RuntimeError("This browser profile is already in use. Close its other Intern-Bot session first.") from None
        try:
            self._playwright = await async_playwright().start()
            browser_type = self._playwright.firefox if self.browser == "firefox" else self._playwright.chromium
            self.context = await browser_type.launch_persistent_context(
                self.user_data_dir, headless=self.headless, timeout=30000,
                **({"channel": "chromium"} if self.extension_path else {"channel": "chrome"} if self.browser == "chrome" else {}),
                **({"args": ["--disable-blink-features=AutomationControlled"] + ([f"--disable-extensions-except={self.extension_path}", f"--load-extension={self.extension_path}"] if self.extension_path else []),
                    "ignore_default_args": ["--enable-automation"]} if self.browser != "firefox" else {}),
                executable_path=self.executable_path,
                **({"viewport": {"width": 1280, "height": 800}} if self.headless else {"no_viewport": True}),
            )
            self.context.set_default_timeout(5000)
            saved = directory / "session-cookies.json"
            if saved.exists():
                await self.context.add_cookies(json.loads(saved.read_text()))
            self._session_ready = True
            return self.context
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        try:
            if self.context:
                try:
                    if self._session_ready:
                        await self.save_session()
                finally:
                    await self.context.close()
        finally:
            self._session_ready = False
            self.context = None
            try:
                if self._playwright:
                    await self._playwright.stop()
            finally:
                self._playwright = None
                if self._lock:
                    self._lock.close()
                    self._lock = None

    async def save_session(self):
        if not self.context or not self._session_ready:
            return
        cookies = await self.context.cookies()
        directory = Path(self.user_data_dir)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as file:
                temporary = Path(file.name)
                json.dump(cookies, file)
            os.replace(temporary, directory / "session-cookies.json")
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
