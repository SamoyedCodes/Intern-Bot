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
from core.automation.models import InterventionRequest, ats_name, canonical_url, application_scope, job_identity, site_key, stable_application_url
from core.automation.journey import ApplicationJourney
from core.automation.recipes import OBSERVE, TEACH, recipe_for, save_recipe
from core.automation.request_engine import RequestEngine
from core.automation.self_teach import SelfTeacher
from core.browser.playwright_mgr import AsyncPlaywrightManager


# Hiring platforms that put the employer in the first path segment rather than the host name.
PATH_TENANTS = {"boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "apply.workable.com", "jobs.smartrecruiters.com"}
GENERIC_LABELS = {"www", "careers", "career", "jobs", "job", "apply", "boards", "recruiting", "hire"}


class AutomationService(QObject):
    progress = Signal(object)
    finished = Signal(object)
    resume_ready = Signal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        store.migrate_local_engine()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.sessions = {}
        self.hosts = {}  # Diagnostic HTTP events only; journeys authorize writes.
        self.journeys = {}
        self.verification_watchers = {}
        self.engines = {}
        self.teaching = {}  # run id -> pages captured while you teach its site
        self.busy = False
        self.active_id = None
        self._future = None
        self._stop_request = None

    def start(self, run, profile, credential=None, inspect_only=False):
        if self.busy:
            return False
        canonical_url(run.job_url)
        self.busy = True
        self.active_id = run.id
        self._stop_request = None
        watcher = self.verification_watchers.pop(run.id, None)
        if watcher:
            self.loop.call_soon_threadsafe(watcher.cancel)
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
                run_id = run.id
                journey = ApplicationJourney(run, page)
                async def reopen_job():
                    journey.run.job_url = journey.run.listing_url or journey.run.job_url
                    return await self.open_job(journey.run, journey.page)
                journey.reopen_job = reopen_job
                self.journeys[run.id] = journey
                await journey.install()
                # Workday's "Something went wrong" page shows only a correlation ID; keep the failing call itself.
                def failed(response):
                    if response.status >= 400 and response.request.resource_type in {"document", "xhr", "fetch"} and urlsplit(response.url).hostname == self.hosts.get(run_id):
                        self.store.record_event(run_id, "http_error", run.stage, f"{response.status} {response.request.method} {urlsplit(response.url).path}")
                page.on("response", failed)
                adapter = ExtensionBridge(page, run.id)
                adapter.journey = journey
                self.sessions[run.id] = (manager, adapter)
                problem = await self.open_job(run, page)
            else:
                adapter = session[1]
                adapter.sync_page()
                adapter.journey.run = run
                await adapter.page.bring_to_front()
                problem = ('', [])
                # Starting over must leave the old draft even on the same employer site.
                fresh = run.status == "queued" and run.stage == "start"
                replaced = not run.fields and not adapter.journey.permits(adapter.page.url)
                if (fresh or replaced) and not run.submission_attempted and not inspect_only:
                    adapter.journey.scopes = {application_scope(run.job_url)}
                    if run.listing_url:
                        adapter.journey.scopes.add(application_scope(run.listing_url))
                    if run.account:
                        adapter.journey.scopes.add(run.account.key)
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
            self.store.record_event(run.id, "failed", run.stage, type(exc).__name__)
            self.store.save_run(run)
        finally:
            self.busy = False
            self.active_id = None
            self.finished.emit(run.model_copy(deep=True))
            if run.status == 'needs_input' and any(i.kind == 'activation' or i.field_key == 'account-challenge' for i in run.interventions) and run.id in self.sessions:
                self.verification_watchers[run.id] = asyncio.create_task(self.watch_verification(run.id))

    async def watch_verification(self, run_id):
        """Only observe: all writes and vault access resume through the normal single-run scheduler."""
        try:
            while run_id in self.sessions:
                await asyncio.sleep(2)
                run = self.store.get_run(run_id)
                if not run or run.status != 'needs_input' or not any(i.kind == 'activation' or i.field_key == 'account-challenge' for i in run.interventions):
                    return
                bridge = self.sessions[run_id][1]
                bridge.sync_page()
                if bridge.page.is_closed() or not bridge.journey.permits(bridge.page.url):
                    return
                found = await bridge.discover()
                solved = any(i.field_key == 'account-challenge' for i in run.interventions) and any(a['account'].get('page') in {'create', 'sign_in', 'email_choice'} and not a['account'].get('form_error') for a in found.get('accounts', []))
                if solved or any(a['account'].get('signed_in') for a in found.get('accounts', [])):
                    run.verification_continued = any(i.kind == 'activation' for i in run.interventions)
                    run.status, run.interventions = 'queued', []
                    self.store.save_run(run)
                    self.resume_ready.emit(run)
                    return
        except (asyncio.CancelledError, Exception):
            return  # A closed browser or changed document leaves the explicit Continue action available.

    async def open_job(self, run, page):
        """Open the run's link. A careers-page listing is followed to one clear Apply destination on a supported
        hiring platform before any profile data or login is used. Returns (what stops it or '', links to choose from)."""
        self.hosts[run.id] = site_key(canonical_url(run.job_url))
        journey = getattr(self, 'journeys', {}).get(run.id)
        response = await page.goto(run.job_url, wait_until="domcontentloaded")
        # Only "not found" and "gone" are final: bot checks answer 403 or 503 and then let the page through.
        if response and response.status in {404, 410}:
            return f"The link returned HTTP {response.status}, so the posting can't be opened. Replace the link with the current posting.", []
        if not ats_name(run.job_url) and not recipe_for(self.store, run.job_url):
            await self.describe(run, page)
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
                run.listing_url, run.job_url = run.listing_url or run.job_url, stable_application_url(targets[0])
                self.hosts[run.id] = site_key(run.job_url)
                self.store.record_event(run.id, "listing_resolved", run.stage, f"Apply link leads to {ats_name(run.job_url)} ({site_key(run.job_url)}).")
                if page.url != run.job_url:
                    if journey:
                        journey.expect(page)
                    response = await page.goto(targets[0], wait_until="domcontentloaded")
                    if response and response.status in {404, 410}:
                        return f"The listing's Apply link returned HTTP {response.status}. The application may be closed; replace the link if you have another.", []
            elif re.search(r"no longer (available|accepting|open)|position has been filled|job (is |has been )?closed|posting (has )?expired|not accepting applications", await page.inner_text("body"), re.I):
                return "This posting says it's closed. Replace the link if you have an open one.", []
            else:
                apply_name = re.compile(r'^(?:apply(?: now| for .+| to .+)?|start (?:your )?application)[\s»›→]*$', re.I)
                apply = page.get_by_role('button', name=apply_name).or_(page.get_by_role('link', name=apply_name))
                if await apply.count() > 1:
                    hrefs = await apply.evaluate_all('es=>es.map(e=>e.href||"")')
                    if hrefs[0] and len(set(hrefs)) == 1:
                        apply = apply.first
                    else:
                        return 'More than one Apply control is available. Open the intended application manually, then resume.', []
                if await apply.count() == 1:
                    if journey:
                        journey.expect(page)
                    before = page.url
                    await apply.click()
                    for _ in range(40):
                        await asyncio.sleep(.1)
                        page = journey.page if journey else page
                        if await page.locator('input[type=password]:visible').count() or page.url != before and await page.locator('input:visible,button:visible,a[href]:visible,iframe:visible').count():
                            break
                    await page.wait_for_load_state('domcontentloaded')
                    if ats_name(page.url):
                        run.listing_url, run.job_url = run.listing_url or run.job_url, stable_application_url(page.url)
                        self.hosts[run.id] = site_key(run.job_url)
        if journey and journey.blocked_reason:
            return journey.blocked_reason, []
        if journey:
            journey.expected.clear()
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

    # Site recipes. Each works on the run's open Chromium tab; False/None means there is none (resume the application first).

    def _page(self, run_id):
        session = self.sessions.get(run_id)
        return session[1].page if session and not session[1].page.is_closed() else None

    def _call(self, coroutine, timeout=15):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    def teach_start(self, run_id):
        """Watch you fill this application: every button click reports the page before it navigates. Nothing is filled or clicked."""
        page = self._page(run_id)
        if not page or self.busy:
            return False
        self.teaching[run_id] = []
        def captured(source, observed):
            if run_id in self.teaching:  # Clicks after teaching ends are ignored.
                self.teaching[run_id].append(observed)
        async def install():
            if not getattr(page, "_intern_teach", False):
                await page.expose_binding("internTeach", captured)  # Once per tab: Playwright can't unbind.
                await page.add_init_script(f"({TEACH})()")
                page._intern_teach = True
            await page.evaluate(TEACH)
            await page.bring_to_front()
        self._call(install())
        return True

    def is_teaching(self, run_id):
        return run_id in self.teaching

    def teach_finish(self, run_id):
        """The clicks captured while teaching and the page as it is now, or None when the tab closed."""
        captures = self.teaching.pop(run_id, None)
        page = self._page(run_id)
        if captures is None or not page:
            return None
        return captures, self._call(page.evaluate(OBSERVE))

    def self_teach(self, run, profile, cfg):
        page = self._page(run.id)
        if not page or self.busy:
            return False
        self.busy, self.active_id, self._stop_request = True, run.id, None
        async def teach():
            teacher = SelfTeacher(self.store, self.progress.emit)
            self.engines[run.id] = teacher
            try:
                await page.bring_to_front()
                await teacher.start(run, profile, page, cfg)
            finally:
                self.busy, self.active_id = False, None
                self.finished.emit(run.model_copy(deep=True))
        self._future = asyncio.run_coroutine_threadsafe(teach(), self.loop)
        return True

    def capture_receipt(self, run_id):
        """After you submit on a recipe site: keep its confirmation heading so later sends can be confirmed."""
        page = self._page(run_id)
        recipe = page and recipe_for(self.store, page.url, approved=False)
        if not recipe or recipe.receipt:
            return ""
        observed = self._call(page.evaluate(OBSERVE))
        heading = next(iter(observed["headings"]), "") if not observed["fields"] else ""
        if heading:
            save_recipe(self.store, recipe.model_copy(update={"receipt": heading[:200]}))
        return heading

    def pause(self, run_id, cancel=False):
        watcher = self.verification_watchers.pop(run_id, None)
        if watcher:
            self.loop.call_soon_threadsafe(watcher.cancel)
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
            for watcher in self.verification_watchers.values():
                watcher.cancel()
            self.verification_watchers.clear()
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
