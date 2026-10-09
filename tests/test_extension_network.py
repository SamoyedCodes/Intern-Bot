"""Observe actual page and extension-worker network channels for every adapter."""
import asyncio
import json

from core.automation.fields import FormField
from tests.test_extension_adapters import URLS, open_fixture, prepare, with_extension


def test_all_adapters_make_zero_vendor_network_requests(tmp_path):
    async def scenario(context,store):
        page_requests=[]
        context.on('request',lambda request:page_requests.append(request.url))
        workers=[w for w in context.service_workers if w.url.startswith('chrome-extension://')]
        ready=workers[0] if workers else await context.wait_for_event(
            'serviceworker', predicate=lambda w:w.url.startswith('chrome-extension://'), timeout=5000)
        assert await ready.evaluate('typeof internBot === "object"')
        probe=context.pages[0]
        session=await context.new_cdp_session(probe)
        targets=await session.send('Target.getTargets')
        worker=next(t for t in targets['targetInfos'] if t['type']=='service_worker' and t['url'].startswith('chrome-extension://'))
        attached=await session.send('Target.attachToTarget',{'targetId':worker['targetId'],'flatten':False})
        worker_requests=[]
        responses=[]
        def event(data):
            if data.get('sessionId')!=attached['sessionId']:return
            message=json.loads(data['message'])
            if message.get('method')=='Network.requestWillBeSent':worker_requests.append(message['params']['request']['url'])
            if message.get('id')==1:responses.append(message)
        session.on('Target.receivedMessageFromTarget',event)
        await session.send('Target.sendMessageToTarget',{'sessionId':attached['sessionId'],'message':json.dumps({'id':1,'method':'Network.enable'})})
        for _ in range(30):
            if responses:break
            await asyncio.sleep(.05)
        assert responses and 'error' not in responses[0],'Worker Network domain was not enabled'
        record=[]
        for site in URLS:
            page=await open_fixture(context,site)
            bridge,engine,run,profile,config=await prepare(page,store,site)
            await bridge.command('start')
            snapshot=await engine.wait_for_section(run,profile)
            assert snapshot and not snapshot['problems'],(site,snapshot)
            fields=[FormField(**f) for f in (await bridge.command('scan'))['fields']]
            assert engine.verify(run,profile,fields,config)
            record.append(site)
            await bridge.stop();await page.close()
        assert len(record)==28
        assert worker_requests==[],worker_requests
        assert not any('speedyapply' in u.lower() or 'supabase' in u.lower() for u in page_requests)
        assert set(page_requests)<=set(u.split('#')[0] for u in URLS.values())
        (tmp_path/'network-capture.json').write_text(json.dumps({'adapters':record,'page_urls':page_requests,'worker_urls':worker_requests,'vendor_requests':0},indent=2))
        await session.detach()
    asyncio.run(with_extension(tmp_path,scenario))
