"""Workday sign-in and account creation: each authentication click happens at most once and secrets stay in the keychain."""
import asyncio
import json

import pytest

from core.automation.engine import SIGN_IN_HANDOFF, ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, employer_key
from tests.support import account_pages, open_fixture, prepare

LOGIN, PASSWORD = 'acme_intern@apps.example.test', 'Fixture-only-1!'
SIGN_IN_PAGE = '''<div data-automation-id="signInPage"><label>Email<input autocomplete=email></label><label>Password<input type=password></label><button type=button data-automation-id=signInSubmitButton onclick="window.logins=(window.logins||0)+1">Sign In</button></div>'''


@pytest.mark.parametrize('replacement', [False, True])
async def test_authentication_waits_for_enabled_current_button(context, store, replacement):
    html = SIGN_IN_PAGE.replace('type=button', 'disabled type=button') + '''<script>
    document.querySelector('input[type=password]').addEventListener('input', () => setTimeout(() => {
      let button = document.querySelector('button');
      REPLACE_BUTTON
      button.disabled = false;
    }, 150));
    </script>'''.replace('REPLACE_BUTTON', 'const copy=button.cloneNode(true);button.replaceWith(copy);button=copy;' if replacement else '')
    page = await open_fixture(context, 'workday', html)
    run = ApplicationRun(job_url=page.url)
    engine = ApplicationEngine(store)
    credential = {'username': LOGIN, 'password': PASSWORD}
    await engine.start(run, ApplicantProfile(), ExtensionBridge(page, run.id), credential)
    assert await page.evaluate('window.logins || 0') == 1
    await engine.resume(run, ApplicantProfile(), ExtensionBridge(page, run.id), credential)
    assert await page.evaluate('window.logins') == 1


@pytest.mark.parametrize('stop', [False, True])
async def test_unavailable_authentication_button_never_clicks(context, store, stop):
    page = await open_fixture(context, 'workday', SIGN_IN_PAGE.replace('type=button', 'disabled type=button'))
    bridge, _, _, _, _ = await prepare(page, store, 'workday')
    task = asyncio.create_task(bridge.command('authenticate', {'credential': {'username': LOGIN, 'password': PASSWORD}}))
    await page.wait_for_function("document.querySelector('input[type=password]').value.length > 0")
    if stop:
        await bridge.stop()
        await page.locator('button').evaluate('e => e.disabled=false')
    with pytest.raises(Exception, match='Local adapter command failed'):
        await task
    assert await page.evaluate('window.logins || 0') == 0


async def test_authentication_waits_for_workday_overlay_button(context, store):
    html = SIGN_IN_PAGE.replace('<button type=button', '<button aria-hidden=true disabled type=button').replace('</button>', '''</button>
    <div role=button aria-label="Sign In" aria-disabled=true onclick="if(this.getAttribute('aria-disabled')==='false')window.logins=(window.logins||0)+1">Sign In</div>''')
    html += '''<script>document.querySelector('input[type=password]').addEventListener('input', () => {
      setTimeout(() => document.querySelector('[role=button]').setAttribute('aria-disabled','false'),150);
    });</script>'''
    page = await open_fixture(context, 'workday', html)
    bridge, _, _, _, _ = await prepare(page, store, 'workday')
    await bridge.command('authenticate', {'credential': {'username': LOGIN, 'password': PASSWORD}})
    assert await page.evaluate('window.logins || 0') == 1


POSTING = '''<div id=root></div><script>
const clicks = [], pages = {
  posting: '<h2>Intern</h2><a data-automation-id=adventureButton onclick="clicks.push(`apply`);show(`dialog`)">Apply</a>',
  dialog: '<h2>Intern</h2><a data-automation-id=adventureButton>Apply</a><div role=dialog><h2>Start Your Application</h2><a data-automation-id=autofillWithResume>Autofill with Resume</a><a data-automation-id=applyManually onclick="clicks.push(`manual`);setTimeout(()=>{history.pushState({},``,location.pathname+`/apply/applyManually`);show(`signin`)},1000)">Apply Manually</a></div>',
  signin: SIGN_IN,
};
function show(name) { document.getElementById('root').innerHTML = pages[name]; }
setTimeout(() => show('posting'), 500);  // Workday renders the posting after the document loads.
</script>'''.replace('SIGN_IN', json.dumps(SIGN_IN_PAGE))


async def test_a_job_posting_opens_the_manual_application_once(context, store):
    page = await open_fixture(context, 'workday', POSTING)
    run = ApplicationRun(job_url=page.url)
    for _ in range(2):
        await ApplicationEngine(store).start(run, ApplicantProfile(), ExtensionBridge(page, run.id))
        assert run.interventions[-1].message == SIGN_IN_HANDOFF
    assert await page.evaluate('clicks') == ['apply', 'manual']


async def test_a_slow_sign_in_continues_into_the_application(context, store, monkeypatch):
    monkeypatch.setattr(ApplicationEngine, 'AUTH_POLLS', 40)
    monkeypatch.setattr(ApplicationEngine, 'SECTION_POLLS', 20)  # The plain follow-up form is not a section any adapter completes.
    html = account_pages('signin', 'signin').replace('window.logins=(window.logins||0)+1', 'window.logins=(window.logins||0)+1,setTimeout(()=>show(`form`),1500)')
    page = await open_fixture(context, 'workday', html)
    run = ApplicationRun(job_url=page.url)
    await ApplicationEngine(store).start(run, ApplicantProfile(), ExtensionBridge(page, run.id), {'username': LOGIN, 'password': PASSWORD})
    assert await page.evaluate('window.logins') == 1
    assert run.interventions and all(i.kind != 'verification' for i in run.interventions), run.interventions


async def test_sign_in_waits_out_workdays_spam_bot_timer(context, store):
    # Workday drops a sign-in submitted within 500ms of its form appearing, and the bot opens that form itself.
    html = account_pages('create', 'create').replace('function show(name){', 'function show(name){window.shown=performance.now();').replace(
        'window.logins=(window.logins||0)+1', 'performance.now()-window.shown>=500&&(window.logins=(window.logins||0)+1)')
    page = await open_fixture(context, 'workday', html)
    run = ApplicationRun(job_url=page.url)
    await ApplicationEngine(store).start(run, ApplicantProfile(), ExtensionBridge(page, run.id), {'username': LOGIN, 'password': PASSWORD})
    assert await page.evaluate('window.logins || 0') == 1, run.interventions


@pytest.fixture(autouse=True)
def static_sign_in_pages(monkeypatch):
    monkeypatch.setattr(ApplicationEngine, 'AUTH_POLLS', 2)  # Most fixtures keep showing their form after the click.


def approve_terms(store, run):
    store.save_answer(ApprovedAnswer(question='I agree to the terms', profile_name=run.profile_name, value=True,
                                     scope='employer', scope_key=employer_key(run.job_url)))


async def test_a_saved_login_signs_in_once_and_never_leaves_the_keychain(context, store):
    page = await open_fixture(context, 'workday', SIGN_IN_PAGE)
    run = ApplicationRun(job_url=page.url)
    engine = ApplicationEngine(store)
    credential = {'username': 'fictional@example.test', 'password': 'fixture-only-secret'}
    await engine.start(run, ApplicantProfile(), ExtensionBridge(page, run.id), credential)
    assert await page.evaluate('window.logins') == 1 and run.authentication_attempted
    await engine.resume(run, ApplicantProfile(), ExtensionBridge(page, run.id), credential)
    assert await page.evaluate('window.logins') == 1
    assert b'fixture-only-secret' not in store.path.read_bytes()
    assert 'fixture-only-secret' not in json.dumps(await context.service_workers[0].evaluate('chrome.storage.session.get(null)'))


@pytest.mark.parametrize('saved_login, attempted', [(True, False), (False, False), (True, True)])
async def test_login_appearing_after_prepare_uses_authentication_flow(context, store, saved_login, attempted):
    page = await open_fixture(context, 'workday', SIGN_IN_PAGE)
    run = ApplicationRun(job_url=page.url, authentication_attempted=attempted)
    bridge = ExtensionBridge(page, run.id)
    command, first_prepare = bridge.command, True

    async def delayed_fields(name, payload=None, binding=None):
        nonlocal first_prepare
        result = await command(name, payload, binding)
        if name == 'prepare' and first_prepare:
            first_prepare = False
            result['fields'] = []  # The sign-in controls appear after the first scan.
        return result

    bridge.command = delayed_fields
    credential = {'username': LOGIN, 'password': PASSWORD} if saved_login else None
    engine = ApplicationEngine(store)
    await engine.start(run, ApplicantProfile(), bridge, credential)
    assert run.interventions and all(i.kind == 'verification' for i in run.interventions)
    assert await page.evaluate('window.logins || 0') == int(saved_login and not attempted)
    await engine.resume(run, ApplicantProfile(), bridge, credential)
    assert await page.evaluate('window.logins || 0') == int(saved_login and not attempted)
    assert PASSWORD.encode() not in store.path.read_bytes()


async def test_a_new_account_is_created_once_then_waits_for_verification_before_one_sign_in(context, store, vault):
    page = await open_fixture(context, 'workday', account_pages('signin', 'signin'))
    url = page.url
    vault.save_credential(url, LOGIN, PASSWORD, 'new')
    run = ApplicationRun(job_url=url)
    states = []
    engine = ApplicationEngine(store, lambda r: states.append((r.authentication_attempted, vault.credential(url)['state'])))
    start = lambda: engine.resume(run, ApplicantProfile(), ExtensionBridge(page, run.id), vault.credential(url))

    # Sign In is shown first: the bot opens Create Account, then asks about the unapproved terms checkbox.
    await start()
    assert run.interventions[-1].kind == 'answer', run.interventions
    assert not await page.evaluate('Boolean(window.creates)') and not run.authentication_attempted
    assert vault.credential(url)['state'] == 'new'

    approve_terms(store, run)
    await start()
    assert await page.evaluate('window.creates') == 1
    assert await page.evaluate('window.created') == [LOGIN, PASSWORD, PASSWORD, True]
    # The keychain recorded the attempt before the click could happen.
    assert next(s for s in states if s[0]) == (True, 'pending_verification')
    assert run.interventions[-1].kind == 'activation' and LOGIN in run.interventions[-1].message

    # Resuming without confirming verification neither re-creates nor signs in.
    await start()
    assert await page.evaluate('window.creates') == 1 and not await page.evaluate('Boolean(window.logins)')
    assert run.interventions[-1].kind == 'activation'

    # "I've verified my account": exactly one sign-in, never repeated.
    vault.set_account_state(url, 'verified')
    run.authentication_attempted = False
    await start()
    assert await page.evaluate('window.logins') == 1
    await start()
    assert await page.evaluate('window.logins') == 1 and await page.evaluate('window.creates') == 1
    assert PASSWORD.encode() not in store.path.read_bytes()


@pytest.mark.parametrize('after, state, handoff', [
    ('error', 'pending_verification', "didn't accept"),
    ('form', 'verified', None),
], ids=['rejected', 'signed-in-immediately'])
async def test_the_creation_outcome_updates_the_saved_login(context, store, vault, monkeypatch, after, state, handoff):
    monkeypatch.setattr(ApplicationEngine, 'SECTION_POLLS', 20)  # The plain follow-up form is not a section any adapter completes.
    page = await open_fixture(context, 'workday', account_pages('create', after))
    vault.save_credential(page.url, LOGIN, PASSWORD, 'new')
    run = ApplicationRun(job_url=page.url)
    approve_terms(store, run)
    await ApplicationEngine(store).start(run, ApplicantProfile(), ExtensionBridge(page, run.id), vault.credential(page.url))
    assert await page.evaluate('window.creates') == 1, run.interventions
    assert vault.credential(page.url)['state'] == state
    if handoff:
        assert run.interventions[-1].kind == 'verification' and handoff in run.interventions[-1].message
