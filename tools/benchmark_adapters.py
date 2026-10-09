"""Benchmark the local engine on the four versioned offline forms."""
import argparse
import hashlib
import platform
from importlib.metadata import version
from playwright.async_api import async_playwright
import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path

from core.automation.models import ApplicantProfile, ApplicationRun
from core.browser.playwright_mgr import AsyncPlaywrightManager
from core.storage.local_store import LocalStore

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures/speedyapply'


async def benchmark(iterations):
    results={}
    urls=json.loads((FIXTURES/'urls.json').read_text())
    async with async_playwright() as playwright:
        executable = playwright.chromium.executable_path
    with tempfile.TemporaryDirectory() as td:
        manager=AsyncPlaywrightManager(executable_path=executable,user_data_dir=td+'/browser',extension_path=ROOT/'extension')
        try:
            context=await manager.start()
            for site in ('workday','greenhouse','lever','ashby'):
                samples=[]
                for i in range(iterations):
                    page=await context.new_page()
                    await page.route('**/*',lambda route:route.fulfill(body=(FIXTURES/f'{site}.html').read_text(),content_type='text/html'))
                    await page.goto(urls[site])
                    profile=ApplicantProfile(first_name='Ada',last_name='Example',email='ada@example.test',phone='5551234567')
                    run=ApplicationRun(job_url=urls[site],auto_advance=False)
                    store=LocalStore(Path(td)/f'{site}-{i}.db')
                    from core.automation.extension_bridge import ExtensionBridge
                    from core.automation.engine import ApplicationEngine
                    engine,adapter=ApplicationEngine(store),ExtensionBridge(page,run.id)
                    start=time.perf_counter()
                    await engine.start(run,profile,adapter)
                    samples.append(dict(seconds=time.perf_counter()-start,correct_fields=sum(a.disposition=='verified' for a in run.fields.values()),interventions=sum(not i.message.startswith('Section verified') for i in run.interventions)))
                    await page.close()
                results[site]=dict(median_seconds=statistics.median(s['seconds'] for s in samples),samples=samples)
        finally:
            await manager.stop()
    return dict(engine="extension",iterations=iterations,fixture_fields=3,playwright=version('playwright'),python=platform.python_version(),browser_executable=Path(executable).name,fixture_sha256={site:hashlib.sha256((FIXTURES/f'{site}.html').read_bytes()).hexdigest() for site in results},results=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--iterations',type=int,default=5)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=asyncio.run(benchmark(args.iterations))
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
