"""One persistent event loop; browser sessions survive manual handoffs."""
import asyncio
import hashlib
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QObject, Signal

from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.models import InterventionRequest, ats_name, canonical_url, employer_key, job_identity, site_key
from core.automation.request_engine import RequestEngine
from core.browser.playwright_mgr import AsyncPlaywrightManager


# Hiring platforms that put the employer in the first path segment rather than the host name.
PATH_TENANTS = {"boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "apply.workable.com", "jobs.smartrecruiters.com"}
GENERIC_LABELS = {"www", "careers", "career", "jobs", "job", "apply", "boards", "recruiting", "hire"}


class AutomationService(QObject):
    progress = Signal(object)
    finished = Signal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        store.migrate_local_engine()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.sessions = {}
        self.hosts = {}  # run id -> the one host its tab may navigate to
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
        engine = (RequestEngine if run.mode == "request" else ApplicationEngine)(self.store, self.progress.emit)
        self.engines[run.id] = engine
        try:
            session = self.sessions.get(run.id)
            if session and session[1].page.is_closed():
                await session[0].stop()
                del self.sessions[run.id]
                session = None
            if not session:
                legacy_browser = run.browser != "chromium"
                session_key = run.id + ":speedy-chromium"
                if legacy_browser:
                    self.store.record_event(run.id, "browser_migration", run.stage, "Resuming in bundled Chromium. Employer sign-in may be required again; the old browser directory is preserved.")
                run.browser = "chromium"
                self.store.save_run(run)
                manager = AsyncPlaywrightManager(headless=False, browser="chromium", extension_path=Path(__file__).resolve().parents[2] / "extension", user_data_dir=str(Path("data/browser") / hashlib.sha256(session_key.encode()).hexdigest()[:24]))
                context = await manager.start()
                page = context.pages[0] if context.pages else await context.new_page()
                # Limit app-driven browsing to the selected employer; external verification is manual.
                run_id = run.id
                async def guard(route):
                    request = route.request
                    destination = urlsplit(request.url)
                    leaves_origin = destination.scheme != "https" or destination.hostname != self.hosts.get(run_id) or destination.port not in (None, 443)
                    if request.is_navigation_request() and request.frame == page.main_frame and leaves_origin:
                        await route.abort()
                    else:
                        await route.continue_()
                await page.route("**/*", guard)
                # Workday's "Something went wrong" page shows only a correlation ID; keep the failing call itself.
                def failed(response):
                    if response.status >= 400 and response.request.resource_type in {"document", "xhr", "fetch"} and urlsplit(response.url).hostname == self.hosts.get(run_id):
                        self.store.record_event(run_id, "http_error", run.stage, f"{response.status} {response.request.method} {urlsplit(response.url).path}")
                page.on("response", failed)
                adapter = ExtensionBridge(page, run.id)
                self.sessions[run.id] = (manager, adapter)
                problem = await self.open_job(run, page)
            else:
                adapter = session[1]
                await adapter.page.bring_to_front()
                problem = ('', [])
                # Starting over must leave the old draft even on the same employer site.
                fresh = run.status == "queued" and run.stage == "start"
                replaced = not run.fields and employer_key(adapter.page.url) != employer_key(run.job_url)
                if (fresh or replaced) and not run.submission_attempted and not inspect_only:
                    problem = await self.open_job(run, adapter.page)
            if problem[0]:
                run.interventions = [InterventionRequest(kind="link", message=problem[0], options=problem[1])]
                run.status = "needs_input"
                self.store.record_event(run.id, "link", run.stage, problem[0])
                engine.checkpoint(run)
            elif self._stop_request is not None:
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
            run.status = "failed"
            run.interventions = [InterventionRequest(kind="browser", message=f"Could not open the application ({type(exc).__name__}). Check the URL, browser and profile lock, then retry.")]
            self.store.save_run(run)
        finally:
            self.busy = False
            self.active_id = None
            self.finished.emit(run.model_copy(deep=True))

    async def open_job(self, run, page):
        """Open the run's link. A careers-page listing is followed to one clear Apply destination on a supported
        hiring platform before any profile data or login is used. Returns (what stops it or '', links to choose from)."""
        self.hosts[run.id] = site_key(canonical_url(run.job_url))
        response = await page.goto(run.job_url, wait_until="domcontentloaded")
        # Only "not found" and "gone" are final: bot checks answer 403 or 503 and then let the page through.
        if response and response.status in {404, 410}:
            return f"The link returned HTTP {response.status}, so the posting can't be opened. Replace the link with the current posting.", []
        if not ats_name(run.job_url):
            if ats_name(page.url) and site_key(page.url) != site_key(run.job_url):
                targets = [page.url]  # The listing redirected straight to its application.
            else:
                links = await page.evaluate("""() => [...document.querySelectorAll('a[href]')]
                    .filter(a => /\\bapply\\b/i.test((a.innerText || '') + ' ' + (a.getAttribute('aria-label') || '')))
                    .map(a => a.href)""")
                targets = list({job_identity(u): u for u in links if urlsplit(u).scheme == "https" and ats_name(u)}.values())
            if len(targets) > 1:
                return "This listing links to more than one application. Choose the right one with Replace link.", targets
            if targets:
                run.listing_url, run.job_url = run.job_url, canonical_url(targets[0])
                self.hosts[run.id] = site_key(run.job_url)
                self.store.record_event(run.id, "listing_resolved", run.stage, f"Apply link leads to {ats_name(run.job_url)} ({site_key(run.job_url)}).")
                if page.url != run.job_url:
                    response = await page.goto(run.job_url, wait_until="domcontentloaded")
                    if response and response.status in {404, 410}:
                        return f"The listing's Apply link returned HTTP {response.status}. The application may be closed; replace the link if you have another.", []
            elif re.search(r"no longer (available|accepting|open)|position has been filled|job (is |has been )?closed|posting (has )?expired|not accepting applications", await page.inner_text("body"), re.I):
                return "This posting says it's closed. Replace the link if you have an open one.", []
        await self.describe(run, page)
        return "", []

    async def describe(self, run, page):
        """Fill in a blank company or role from the posting itself, so the board names the job you pasted."""
        if run.company and run.role != "Internship":
            return
        title = await page.evaluate("""() => (document.querySelector('[data-automation-id=jobPostingHeader], h1')?.innerText
            || document.querySelector('meta[property="og:title"]')?.content || document.title || '').trim()""")
        if not run.company:
            # ponytail: the hiring platform's tenant name (acme in acme.wd1.myworkdayjobs.com or boards.greenhouse.io/acme); edit it under Options if it reads oddly.
            parts = urlsplit(run.job_url)
            tenant = parts.path.strip("/").split("/")[0] if parts.hostname in PATH_TENANTS else next((label for label in parts.hostname.split(".") if label not in GENERIC_LABELS), "")
            tenant = parse_qs(parts.query).get("for", [""])[0] if tenant == "embed" else tenant
            run.company = tenant.replace("-", " ").replace("_", " ").title()[:80]
        if run.role == "Internship" and title:
            # "Job Application for Data Intern at Acme" or "Acme - Data Intern": keep the part that isn't the company.
            title = re.sub(r"^job application for\s+", "", title.splitlines()[0], flags=re.I)
            parts = [part.strip() for part in re.split(r"\s+(?:at|@)\s+|\s+[|–—-]\s+", title) if part.strip()]
            parts = [part for part in parts if part.casefold() != run.company.casefold()] or parts
            run.role = parts[0][:120] if parts else run.role
        self.store.save_run(run)

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
