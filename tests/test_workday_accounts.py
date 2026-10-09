"""Workday sign-in and account creation: each authentication click happens at most once and secrets stay in the keychain."""
import json

import pytest

from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, employer_key
from tests.support import account_pages, open_fixture

LOGIN, PASSWORD = 'acme_intern@apps.example.test', 'Fixture-only-1!'
SIGN_IN_PAGE = '''<div data-automation-id="signInPage"><label>Email<input autocomplete=email></label><label>Password<input type=password></label><button type=button data-automation-id=signInSubmitButton onclick="window.logins=(window.logins||0)+1">Sign In</button></div>'''


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
