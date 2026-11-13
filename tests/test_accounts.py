"""Shared account flows use fictional forms, an in-memory vault and no live network."""
import json

import pytest

from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.models import ApplicationRun, ApprovedAnswer, account_context, application_scope
from tests.support import FIXTURES, open_fixture, profile_for

SAP = 'https://career44.sapsf.com/career?company=fictional&career_job_req_id=42'
GENERIC = 'https://careers.example.test/job/42'


def signup(after='verification', extra='', action=''):
    application = '<button>Sign Out</button>' + (FIXTURES / 'sap-successfactors.html').read_text().split('<body>', 1)[1].split('</body>', 1)[0]
    create = '''<form onsubmit="event.preventDefault();created()"><h1>Create an Account</h1>
      <label>Email Address<input type=email required></label><label>Retype Email Address<input type=email required></label>
      <label>Choose Password<input type=password minlength=12 maxlength=20 required></label>
      <label>Retype Password<input type=password minlength=12 maxlength=20 required></label>
      <p>Password must be at least 12 characters long. Password must be no longer than 20 characters.</p>
      <label>First Name<input name=firstName required></label><label>Last Name<input name=lastName required></label>
      <label><input type=checkbox required>I agree to the terms and privacy statement</label>
      <label><input type=checkbox checked>Send marketing emails</label>EXTRA
      <button>Create Account</button></form>'''.replace('EXTRA', extra)
    if action:
        create = create.replace('<form ', f'<form action="{action}" ')
    signin = '''<form onsubmit="event.preventDefault();window.logins=(window.logins||0)+1;show('application')">
      <label>Email Address<input type=email required></label><label>Password<input type=password required></label><button>Sign In</button></form>'''
    pages = {'create': create, 'sign_in': signin, 'application': application,
             'verification': '<h1>Check your email for the verification email</h1><button onclick="show(\'sign_in\')">Sign In</button>',
             'error': create + '<div role=alert>An account with this email already exists.</div>',
             'uncertain': '<h1>Loading</h1>'}
    return '''<div id=root></div><script>
      const pages=PAGES;function show(name){document.getElementById('root').innerHTML=pages[name];}
      function created(){window.creates=(window.creates||0)+1;window.sent=[...document.querySelectorAll('input')].map(e=>e.type==='checkbox'?e.checked:e.value);show(AFTER);}
      show('create');</script>'''.replace('PAGES', json.dumps(pages)).replace('AFTER', json.dumps(after))


async def run_account(context, store, url=SAP, html=None, run=None):
    page = await open_fixture(context, 'sap-successfactors', html or signup(), url=url)
    run = run or ApplicationRun(job_url=url)
    engine = ApplicationEngine(store)
    engine.SECTION_POLLS = 2
    engine.AUTH_POLLS = 3
    await engine.start(run, profile_for('sap-successfactors'), ExtensionBridge(page, run.id))
    return run, page, engine


@pytest.mark.parametrize('url', [SAP, GENERIC])
async def test_missing_login_is_saved_before_signup_and_waits_for_email(context, store, vault, url):
    store.put('auto_create_accounts', True)
    checkpoints = []
    original = vault.set_account_state
    def state(site, value):
        checkpoints.append((value, bool(vault.credential(site))))
        original(site, value)
    vault.set_account_state = state
    run, page, _ = await run_account(context, store, url)
    login = vault.credential(url)
    assert login['username'] == 'ada@example.test' and len(login['password']) == 20
    assert checkpoints == [('creation_attempted', True), ('pending_verification', True)]
    assert run.registration_attempted and not run.login_attempted
    assert await page.evaluate('window.creates') == 1
    assert await page.evaluate('window.sent.slice(-2)') == [True, False]
    assert await page.evaluate('window.sent.slice(0,4)') == [login['username'], login['username'], login['password'], login['password']]
    assert run.interventions[-1].kind == 'activation'
    assert login['password'].encode() not in store.path.read_bytes()
    assert login['password'] not in json.dumps(await context.service_workers[0].evaluate('chrome.storage.session.get(null)'))


async def test_verification_then_login_continues_the_selected_application(context, store, vault):
    store.put('auto_create_accounts', True)
    run, page, engine = await run_account(context, store)
    await engine.resume(run, profile_for('sap-successfactors'), ExtensionBridge(page, run.id))
    assert not await page.evaluate('window.logins||0') and await page.evaluate('window.creates') == 1
    run.verification_continued = True
    await engine.resume(run, profile_for('sap-successfactors'), ExtensionBridge(page, run.id))
    assert await page.evaluate('window.logins') == 1
    assert await page.evaluate('window.creates') == 1
    assert vault.credential(SAP)['state'] == 'verified'
    assert await page.locator('#fName').input_value() == 'Ada'
    await engine.resume(run, profile_for('sap-successfactors'), ExtensionBridge(page, run.id))
    assert await page.evaluate('window.logins') == 1


async def test_signup_that_authenticates_immediately_skips_another_login(context, store, vault):
    store.put('auto_create_accounts', True)
    run, page, _ = await run_account(context, store, html=signup('application'))
    assert await page.evaluate('window.creates') == 1 and not await page.evaluate('window.logins||0')
    assert vault.credential(SAP)['state'] == 'verified'
    assert await page.locator('#fName').input_value() == 'Ada'


async def test_identical_tab_urls_still_bind_only_the_selected_application(context, store):
    store.put('auto_create_accounts', True)
    other = await open_fixture(context, 'sap-successfactors', signup(), url=SAP)
    run, selected, _ = await run_account(context, store)
    assert run.registration_attempted and await selected.evaluate('window.creates') == 1
    assert not await other.evaluate('window.creates||0')
    assert await other.locator('input[type=password]').first.input_value() == ''


@pytest.mark.parametrize('outcome', ['error', 'uncertain'])
async def test_uncertain_or_rejected_creation_is_never_replayed_after_restart(context, store, vault, outcome):
    store.put('auto_create_accounts', True)
    run, page, _ = await run_account(context, store, html=signup(outcome))
    assert run.registration_attempted and vault.credential(SAP)['state'] == 'creation_attempted'
    run = store.get_run(run.id)
    await page.evaluate("show('create')")
    await ApplicationEngine(store).start(run, profile_for('sap-successfactors'), ExtensionBridge(page, run.id))
    assert await page.evaluate('window.creates') == 1
    assert run.interventions[-1].kind == 'verification'


async def test_saved_login_is_reused_for_another_job_at_the_same_sap_tenant(context, store, vault):
    vault.save_credential(SAP, 'existing@example.test', 'Existing1!')
    url = SAP.replace('req_id=42', 'req_id=43')
    run, page, _ = await run_account(context, store, url, signup().replace("show('create');</script>", "show('sign_in');</script>"))
    assert await page.evaluate('window.logins') == 1 and not await page.evaluate('window.creates||0')
    assert run.account.key == account_context(SAP).key


@pytest.mark.parametrize('url', ['https://career44.sapsf.com/career', 'https://accounts.google.com/signup'])
async def test_unidentified_shared_or_sso_accounts_receive_no_credentials(context, store, vault, url):
    store.put('auto_create_accounts', True)
    run, page, _ = await run_account(context, store, url)
    assert not vault.logins.items and not run.registration_attempted
    assert not await page.evaluate('window.creates||0')
    assert await page.locator('input[type=password]').first.input_value() == ''


async def test_vault_failure_does_not_trigger_account_creation(context, store, vault):
    store.put('auto_create_accounts', True)
    def unavailable(site):
        raise RuntimeError('1Password is unavailable.')
    vault.credential = unavailable
    run, page, _ = await run_account(context, store)
    assert not run.registration_attempted and not await page.evaluate('window.creates||0')
    assert run.interventions[-1].message == '1Password is unavailable.'


async def test_an_account_form_with_an_unverified_receiver_gets_no_credentials(context, store, vault):
    store.put('auto_create_accounts', True)
    html = signup(action='https://unrelated.example.test/collect')
    run, page, _ = await run_account(context, store, html=html)
    assert not vault.logins.items and not run.registration_attempted
    assert await page.locator('input[type=password]').first.input_value() == ''
    assert 'unverified account site' in run.interventions[-1].message


async def test_unknown_required_signup_fact_and_non_terms_consent_need_an_answer(context, store, vault):
    store.put('auto_create_accounts', True)
    for extra in ['<label>Employee reference<input required></label>', '<label><input type=checkbox required>I consent to a background check</label>']:
        run, page, _ = await run_account(context, store, html=signup(extra=extra))
        assert run.interventions[-1].kind == 'answer' and not run.registration_attempted
        assert not await page.evaluate('window.creates||0')
        await page.close()


async def test_password_validation_failure_keeps_the_account_unsubmitted(context, store, vault):
    vault.save_credential(SAP, 'ada@example.test', 'too-short', 'new')
    run, page, _ = await run_account(context, store)
    assert not run.registration_attempted and vault.credential(SAP)['state'] == 'new'
    assert not await page.evaluate('window.creates||0')


async def test_sap_hidden_password_rules_and_acknowledgement_marketing_are_respected(context, store, vault):
    store.put('auto_create_accounts', True)
    html = signup().replace('no longer than', 'not be longer than').replace('maxlength=20', '').replace('<p>Password', '<p hidden>Password')
    # The actual SAP field is labelled Acknowledgement; the adjacent copy identifies the email opt-in.
    html = html.replace('<label><input type=checkbox checked>Send marketing emails</label>', '<label for=optin>Acknowledgement:</label><div><input type=checkbox id=optin checked>I would like to receive emails about job opportunities from Synapxe.</div>')
    run, page, _ = await run_account(context, store, html=html)
    assert len(vault.credential(SAP)['password']) == 20
    assert run.registration_attempted and await page.evaluate('window.sent.at(-1)') is False


async def test_sap_residence_visibility_notification_and_terms_dialog(context, store, vault):
    # Halliburton's sign-up form: a country picker, a required radiogroup named by aria-labelledby, an optional opt-in, terms in a dialog.
    store.put('auto_create_accounts', True)
    extra = '''<select aria-label="Country/Region of Residence" required><option value="">- Select -<option value=SG>Singapore<option value=MY>Malaysia</select>
      <label id=vis>Make My Profile Visible to:<span>*</span></label><div role=radiogroup aria-labelledby=vis aria-required=true>
        <input type=radio name=pref value=1 aria-label="Any company recruiter worldwide"><label>Any company recruiter worldwide</label>
        <input type=radio name=pref value=2 aria-label="Only recruiters managing jobs I apply to"><label>Only recruiters managing jobs I apply to</label></div>
      <label for=notify>Notification:</label><div><input type=checkbox id=notify><span>Receive new job posting notifications</span></div>
      <a id=dataPrivacyId role=button onclick="document.getElementById('dlg').hidden=false">Read and accept the data privacy statement.</a>
      <input type=hidden id=fbclc_dpcsId><div id=dlg role=dialog hidden><button type=button onclick="document.getElementById('fbclc_dpcsId').value='7';this.parentElement.hidden=true">Accept</button><button type=button>Decline</button></div>'''
    html = signup(extra=extra).replace('window.sent=', "window.form=[document.querySelector('select').value,document.querySelector('[name=pref]:checked')?.value,document.getElementById('notify').checked,document.getElementById('fbclc_dpcsId').value];window.sent=")
    profile = profile_for('sap-successfactors').model_copy(update={'country': 'Singapore'})
    page = await open_fixture(context, 'sap-successfactors', html, url=SAP)
    run, engine = ApplicationRun(job_url=SAP), ApplicationEngine(store)
    engine.SECTION_POLLS, engine.AUTH_POLLS = 2, 3
    await engine.start(run, profile, ExtensionBridge(page, run.id))
    # Only the visibility choice is yours to make; the country came from the profile and the opt-in was never asked.
    assert not run.registration_attempted and [i.question for i in run.interventions] == ['Make My Profile Visible to:']
    store.save_answer(ApprovedAnswer(question='Make My Profile Visible to:', value='Only recruiters managing jobs I apply to', scope='global'))
    await engine.resume(run, profile, ExtensionBridge(page, run.id))
    assert run.registration_attempted and await page.evaluate('window.form') == ['SG', '2', False, '7']


async def test_captcha_pauses_before_signup_and_can_continue_after_manual_completion(context, store):
    store.put('auto_create_accounts', True)
    extra = '<iframe src="https://captcha.example.test/recaptcha/api2/anchor" srcdoc="Challenge"></iframe><textarea name=g-recaptcha-response hidden></textarea>'
    run, page, engine = await run_account(context, store, html=signup(extra=extra))
    assert not run.registration_attempted and run.interventions[-1].field_key == 'account-challenge'
    await page.locator('[name=g-recaptcha-response]').evaluate("e=>e.value='solved-fixture-token'")
    await engine.resume(run, profile_for('sap-successfactors'), ExtensionBridge(page, run.id))
    assert run.registration_attempted and run.interventions[-1].kind == 'activation'
    assert b'solved-fixture-token' not in store.path.read_bytes()


def test_account_identity_ignores_job_locale_and_temporary_tokens_but_keeps_tenants():
    assert application_scope(SAP) == application_scope(SAP.replace('req_id=42', 'req_id=99') + '&lang=fr_FR&requestParams=expired')
    assert application_scope(SAP) != application_scope(SAP.replace('company=fictional', 'company=other'))


def test_sap_records_keep_the_job_but_not_expiring_authentication_parameters(store):
    run = ApplicationRun(job_url=SAP + '&requestParams=temporary-secret&_s.crb=temporary-token&login_ns=register')
    store.save_run(run)
    saved = store.get_run(run.id)
    assert 'career_job_req_id=42' in saved.job_url and 'career_ns=job_listing' in saved.job_url
    assert b'temporary-secret' not in store.path.read_bytes() and b'temporary-token' not in store.path.read_bytes()

