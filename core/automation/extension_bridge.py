"""Direct Playwright service-worker commands, scoped to one run and document."""
import asyncio
import re
import secrets
from urllib.parse import urlsplit


class ExtensionBridge:
    def __init__(self, page, run_id):
        self.page = page
        self.run_id = run_id
        self.binding = None
        self.worker_url = next((worker.url for worker in page.context.service_workers if worker.url.startswith('chrome-extension://')), '')
        self.pending = set()
        self.journey = None
        self._listen(page)

    def _listen(self, page):
        page.on('request', self._request_started)
        page.on('requestfinished', lambda request: self.pending.discard(request))
        page.on('requestfailed', lambda request: self.pending.discard(request))

    def sync_page(self):
        if self.journey and self.page != self.journey.page:
            self.page = self.journey.page
            self.binding = None
            self.pending.clear()
            self._listen(self.page)

    def _request_started(self, request):
        # Only the employer's own traffic signals form activity; third-party trackers (LinkedIn's beacons) can stay pending forever.
        hosts = {urlsplit(url).hostname for url in (self.page.url, (self.binding or {}).get('url') or self.page.url)}
        url = urlsplit(request.url)
        # Workday's fire-and-forget terms-display timestamp does not update or validate application fields.
        if request.method == 'POST' and (url.hostname or '').endswith('.myworkdayjobs.com') and re.fullmatch(r'/wday/calypso/cxs/jobapplication/[^/]+/jobapplication/[^/]+/termslockmoment', url.path):
            return
        if request.resource_type in {'document', 'script', 'xhr', 'fetch'} and urlsplit(request.url).hostname in hosts:
            self.pending.add(request)

    async def command(self, command, payload=None, binding=None):
        self.sync_page()
        if self.journey and command in {'open_application', 'open_sign_in', 'open_create_account', 'authenticate'}:
            self.journey.expect()
        if self.journey and (command in {'start', 'authenticate', 'validate_authentication'} or command == 'authorize' and any(p.get('value') is not None for p in (payload or {}).get('policies', {}).values())):
            self.journey.data_entered = True
        workers = [w for w in self.page.context.service_workers if w.url.startswith('chrome-extension://') and w.url.endswith('/background.js')]
        worker = workers[-1] if workers else None
        if worker:
            self.worker_url = worker.url
            try:
                await asyncio.wait_for(worker.evaluate('typeof internBot === "object"'), 1)
            except Exception:
                worker = None
        if worker is None:
            if not self.worker_url:
                worker = await self.page.context.wait_for_event('serviceworker', timeout=5000)
                self.worker_url = worker.url
            else:
                wake = await self.page.context.new_page()
                try:
                    await wake.goto(self.worker_url.rsplit('/', 1)[0] + '/wake.html', wait_until='commit')
                    worker = self.page.context.service_workers[-1]
                    await asyncio.wait_for(worker.evaluate('typeof internBot === "object"'), 5)
                finally:
                    if not wake.is_closed():
                        await wake.close()
        response = await asyncio.wait_for(worker.evaluate('(message) => internBot.command(message)', {
            'command': command, 'run': self.run_id, 'binding': binding or self.binding, 'payload': payload or {},
        }), 8)
        if response.get('binding'):
            self.binding = response['binding']
        return response

    async def discover(self, recipes=()):
        self.sync_page()
        for _ in range(20):
            result = await self.command('discover', {'url': self.page.url, 'recipes': list(recipes)})
            if result.get('problem') == 'A unique application tab could not be identified.':
                nonce = secrets.token_urlsafe(24)
                await self.page.evaluate('(nonce)=>document.documentElement.dataset.internBotPage=nonce', nonce)
                result = await self.command('discover', {'url': self.page.url, 'recipes': list(recipes), 'nonce': nonce})
            if result.get('matches') or result.get('accounts'):
                if self.journey:
                    self.journey.expected.clear()
                return result
            await asyncio.sleep(.1)
        return result

    async def stop(self):
        if self.binding:
            try:
                await self.command('stop')
            except Exception:
                pass  # Navigation already revoked the old document's mutation capability.
