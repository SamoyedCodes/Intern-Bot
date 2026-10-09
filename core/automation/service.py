"""One persistent event loop; browser sessions survive manual handoffs."""
import asyncio
import hashlib
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from core.automation.engine import ApplicationEngine
from core.automation.models import canonical_url, site_key
from core.automation.ats import adapter_for
from core.browser.playwright_mgr import AsyncPlaywrightManager


class AutomationService(QObject):
    progress = Signal(object)
    finished = Signal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.sessions = {}
        self.engines = {}
        self.busy = False
        self.active_id = None
        self._future = None
        self._stop_request = None

    def start(self, run, profile, credential, inspect_only=False):
        if self.busy:
            return False
        canonical_url(run.job_url)
        self.busy = True
        self.active_id = run.id
        self._stop_request = None
        self._future = asyncio.run_coroutine_threadsafe(self._run(run, profile, credential, inspect_only), self.loop)
        return True

    async def _run(self, run, profile, credential, inspect_only=False):
        engine = ApplicationEngine(self.store, self.progress.emit)
        self.engines[run.id] = engine
        try:
            session = self.sessions.get(run.id)
            if session and session[1].page.is_closed():
                await session[0].stop()
                del self.sessions[run.id]
                session = None
            if not session:
                session_key = run.id if run.browser == "chromium" else run.id + ":" + run.browser
                manager = AsyncPlaywrightManager(headless=False, browser=run.browser, user_data_dir=str(Path("data/browser") / hashlib.sha256(session_key.encode()).hexdigest()[:24]))
                context = await manager.start()
                page = context.pages[0] if context.pages else await context.new_page()
                # Limit app-driven browsing to the selected employer; external verification is manual.
                host = site_key(canonical_url(run.job_url))
                async def guard(route):
                    from urllib.parse import urlsplit
                    request = route.request
                    destination = urlsplit(request.url)
                    leaves_origin = destination.scheme != "https" or destination.hostname != host or destination.port not in (None, 443)
                    if request.is_navigation_request() and request.frame == page.main_frame and leaves_origin:
                        await route.abort()
                    else:
                        await route.continue_()
                await page.route("**/*", guard)
                adapter = adapter_for(page, run.job_url)
                self.sessions[run.id] = (manager, adapter)
                await page.goto(run.job_url, wait_until="domcontentloaded")
            else:
                adapter = session[1]
                await adapter.page.bring_to_front()
            if self._stop_request is not None:
                if self._stop_request:
                    run.status = "cancelled"
                    engine.checkpoint(run)
                else:
                    engine.intervene(run, "Paused by you. Resume when ready.")
            elif inspect_only:
                engine.intervene(run, "Browser reopened. Open the saved draft and review it manually, or resume to reverify its current contents.")
            else:
                await engine.start(run, profile, adapter, credential)
        except Exception as exc:
            from core.automation.models import InterventionRequest
            run.status = "failed"
            run.interventions = [InterventionRequest(kind="browser", message=f"Could not open the application ({type(exc).__name__}). Check the URL, browser and profile lock, then retry.")]
            self.store.save_run(run)
        finally:
            self.busy = False
            self.active_id = None
            self.finished.emit(run.model_copy(deep=True))

    def pause(self, run_id, cancel=False):
        if self.active_id == run_id:
            self._stop_request = cancel
        def stop():
            engine = self.engines.get(run_id)
            if engine:
                engine.cancel() if cancel else engine.pause()
        self.loop.call_soon_threadsafe(stop)

    def show_browser(self, run_id):
        if run_id not in self.sessions or self.sessions[run_id][1].page.is_closed():
            return False
        async def show():
            if run_id in self.sessions and not self.sessions[run_id][1].page.is_closed():
                await self.sessions[run_id][1].page.bring_to_front()
        asyncio.run_coroutine_threadsafe(show(), self.loop)
        return True

    def shutdown(self):
        async def close():
            for engine in self.engines.values():
                engine.pause()
            if self._future and not self._future.done():
                self._future.cancel()
                await asyncio.sleep(.1)
            for manager, _ in list(self.sessions.values()):
                await manager.stop()
            self.sessions.clear()
        future = asyncio.run_coroutine_threadsafe(close(), self.loop)
        try:
            future.result(timeout=10)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
