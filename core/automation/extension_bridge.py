"""Direct Playwright service-worker commands, scoped to one run and document."""
import asyncio
from urllib.parse import urlsplit


class ExtensionBridge:
    def __init__(self, page, run_id):
        self.page = page
        self.run_id = run_id
        self.binding = None
        self.worker_url = next((worker.url for worker in page.context.service_workers if worker.url.startswith('chrome-extension://')), '')
        self.pending = set()
        page.on('request', self._request_started)
        page.on('requestfinished', lambda request: self.pending.discard(request))
        page.on('requestfailed', lambda request: self.pending.discard(request))

    def _request_started(self, request):
        # Only the employer's own traffic signals form activity; third-party trackers (LinkedIn's beacons) can stay pending forever.
        hosts = {urlsplit(url).hostname for url in (self.page.url, (self.binding or {}).get('url') or self.page.url)}
        if request.resource_type in {'document', 'script', 'xhr', 'fetch'} and urlsplit(request.url).hostname in hosts:
            self.pending.add(request)

    async def command(self, command, payload=None, binding=None):
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

    async def discover(self):
        for _ in range(20):
            result = await self.command('discover', {'url': self.page.url})
            if result.get('matches'):
                return result
            await asyncio.sleep(.1)
        return result

    async def stop(self):
        if self.binding:
            try:
                await self.command('stop')
            except Exception:
                pass  # Navigation already revoked the old document's mutation capability.
