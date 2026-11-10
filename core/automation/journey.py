"""Navigation may discover another origin; only a selected Apply journey grants write access."""
import time
import json
import secrets
from urllib.parse import parse_qsl, urlsplit, urlencode

from playwright.async_api import Error as PlaywrightError

from core.automation.models import application_scope, canonical_url, account_context, ats_name

SAP_HANDOFF_FIELDS = {'correlation_Id', 'company', 'lang', 'clientId', 'socialApply', 'career_ns', 'site',
                      'career_job_req_id', 'jobPipeline', 'isInternalUser', 'showAlertCreated', 'requestParams', '_s.crb'}


class ApplicationJourney:
    def __init__(self, run, page):
        self.run, self.page = run, page
        self.scopes = {application_scope(run.job_url)}
        if run.listing_url:
            self.scopes.add(application_scope(run.listing_url))
        if run.account:
            self.scopes.add(run.account.key)
        self.expected = {}
        self.requests = set()
        self.intent_token = secrets.token_urlsafe(24)
        self.data_entered = False
        self.blocked_reason = ''

    def permits(self, url):
        try:
            return application_scope(canonical_url(url)) in self.scopes
        except ValueError:
            return False

    def expect(self, page=None):
        page = page or self.page
        if self.permits(page.url):
            self.expected[page] = time.monotonic() + 20

    async def adopt_frame(self, url):
        if not self.permits(self.page.url) or not ats_name(url):
            return False
        frames = [frame for frame in self.page.frames if frame.url == url and frame.parent_frame == self.page.main_frame]
        if len(frames) != 1:
            return False
        element = await frames[0].frame_element()
        source = await element.evaluate('e=>e.src')
        if application_scope(source) != application_scope(url):
            return False
        self.scopes.add(application_scope(url))
        return True

    async def install(self):
        context = self.page.context

        async def intent(source, token):
            if token == self.intent_token and source["frame"] == source["page"].main_frame and self.permits(source["frame"].url):
                self.expect(source["page"])

        await context.expose_binding("internBotApplicationIntent", intent)
        await context.add_init_script("""(() => {
          document.addEventListener('click', event => {
            const e=event.target.closest('a,button,input[type=submit],[role=button]');
            if(event.isTrusted && e && /\\b(apply|sign in|log in|register|create (an? )?account|sign up|continue application)\\b/i.test((e.innerText||e.value||'')+' '+(e.getAttribute('aria-label')||'')))
              window.internBotApplicationIntent(INTENT_TOKEN).catch(()=>{});
          }, true);
        })();""".replace('INTENT_TOKEN', json.dumps(self.intent_token)))
        context.on('page', self.popup)
        context.on('response', self.arrived)
        await context.route("**/*", self.route)

    def arrived(self, response):
        request = response.request
        while request is not None:
            if request in self.requests:
                try:
                    self.scopes.add(application_scope(canonical_url(response.url)))
                    if ats_name(response.url):
                        self.expected.clear()
                except ValueError:
                    pass
                return
            request = request.redirected_from

    async def popup(self, page):
        opener = await page.opener()
        if not opener or time.monotonic() >= self.expected.get(opener, 0):
            return
        self.page = page

        def arrived(frame):
            if frame != page.main_frame or time.monotonic() >= self.expected.get(opener, 0):
                return
            try:
                self.scopes.add(application_scope(canonical_url(frame.url)))
                self.expected.pop(opener, None)
            except ValueError:
                pass

        page.on('framenavigated', arrived)
        arrived(page.main_frame)

    async def route(self, route):
        request = route.request
        if not request.is_navigation_request():
            return await route.fallback()
        try:
            canonical_url(request.url)
        except ValueError:
            self.blocked_reason = 'The application tried to leave HTTPS or use an unsupported address. Open the employer’s HTTPS application link before resuming.'
            return await route.abort("blockedbyclient")
        try:
            frame = request.frame
        except PlaywrightError:
            # Chromium issues the first popup GET before creating its frame; popup() grants access after arrival.
            return await route.fallback() if request.method == 'GET' else await route.abort('blockedbyclient')
        if frame != frame.page.main_frame:
            return await route.fallback()
        page = frame.page
        opener = await page.opener()
        source = opener or page
        follows = request.redirected_from in self.requests
        intended = time.monotonic() < self.expected.get(source, 0)
        trusted = self.permits(request.url)
        if trusted and request.method == 'GET':
            self.blocked_reason = ''
        if request.method == 'POST' and self.permits(page.url) and urlsplit(request.url).hostname == urlsplit(page.url).hostname:
            # A tenant's form action may omit its company query; an explicit different tenant is never accepted.
            trusted = trusted or account_context(request.url) is None and not any(key == 'company' for key, _ in parse_qsl(urlsplit(request.url).query))
        discovery_post = request.method == 'POST' and intended and not self.data_entered and self.permits(page.url)
        if request.method == 'POST' and intended and self.permits(page.url) and ats_name(request.url) == 'SAP SuccessFactors':
            fields = parse_qsl(request.post_data or '', keep_blank_values=True)
            # SAP's public job handoff is a form POST, including when returning after sign-in.
            companies = [value for key, value in fields if key == 'company']
            safe_handoff = bool(fields) and {key for key, _ in fields} <= SAP_HANDOFF_FIELDS and len(companies) == 1 and bool(companies[0])
            discovery_post = discovery_post or safe_handoff
            if safe_handoff:
                tenant_url = urlsplit(request.url)._replace(query=urlencode({'company': dict(fields)['company']})).geturl()
                self.scopes.add(account_context(tenant_url).key)
        if request.method != "GET" and not trusted and not discovery_post:
            self.blocked_reason = 'The application tried to send form data to an unverified site. No form data was forwarded. Open the selected application before resuming.'
            return await route.abort("blockedbyclient")
        if follows or intended or trusted:
            self.requests.add(request)
            self.scopes.add(application_scope(request.url))
            deadline = self.expected.pop(source, None)
            # Public job portals also use HTML/JavaScript intermediate redirects, without an HTTP redirect chain.
            if not ats_name(request.url) and (deadline or page.url == 'about:blank'):
                self.expected[page] = deadline or time.monotonic() + 20
            if opener and (intended or follows):
                self.page = page
        # Unrelated GETs can be inspected, but never acquire permission to fill data.
        await route.fallback()

