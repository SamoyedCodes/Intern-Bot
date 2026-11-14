"""Section verification around the local extension's site-specific filling work."""
import asyncio
from dataclasses import replace
import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from core.automation.answers import UNANSWERED, applicable, asks, canonical, field_value, linked, names_row, profile_rows, question_for, resolve
from core.automation.assistant import ai_config, askable, autofill, matchable, pointer_only
from core.automation.models import CHECKING_LOGIN, CREATING_ACCOUNT, SAVING_LOGIN, SIGNING_IN, CHOICE_KINDS, ApplicantProfile, ApprovedAnswer, FieldAssessment, InterventionRequest, normalized, now, employer_key, canonical_url, account_context, application_scope, same_choice, same_choices
from core.automation.accounts import login_address
from core.automation.journey import ApplicationJourney
from pathlib import Path
from core.automation.speedy_profile import translate
from core.automation.privacy import configure_privacy
from core.automation.fields import FormField
from core.automation.recipes import recipe_for, save_recipe
from core.storage.onepassword import AmbiguousLogins

ENGINE_VERSION = 'speedyapply-local-2.28.0-v2'
SIGN_IN_HANDOFF = 'Complete employer sign-in or activation in Chromium, then resume. Saved credentials remain in 1Password; an existing authentication attempt will not be repeated.'
ACTIVATION_HANDOFF = "Check {} for the employer's verification email and open its link, then choose Continue after verification."
# Controls the desktop may retype with real keystrokes when the form shows the approved value but rejected it.
TYPED_KINDS = {'text', 'textarea', 'spinbutton', 'tel', 'email', 'url', 'number', 'date'}
REJECTED_ACCOUNT = "The employer didn't accept the new account. It may already exist: sign in or reset the password in Chromium, save that login under Profile → Employer accounts, then resume."


def password_recipe(auth):
    """1Password's generator recipe for this account form's password rules, or '' when its length limits conflict."""
    policy = auth.get('policy', {})
    length = min(24, policy.get('maximum', 64))
    if length < max(1, policy.get('minimum', 0)):
        return ''
    return str(length) + ',letters,digits' + (',symbols' if policy.get('symbols', True) else '')


class ApplicationEngine:
    # Bounded polls (~0.1s and 0.25s apart); tests shrink them to fail fast.
    SECTION_POLLS = 210
    RECEIPT_POLLS = 20
    AUTH_POLLS = 40
    # The page's adapter stops 20 s after it starts, so fills must not wait on a slow AI reply.
    # A session's first cloud call also loads the SDK and opens a connection: ~5-6 s with Claude, seen live.
    AI_MATCH_SECONDS = 10
    AI_LOCAL_SECONDS = 30  # A local model may need to load into memory first.

    def __init__(self, store, emit=None):
        configure_privacy()
        self.store, self.emit = store, emit or (lambda run: None)
        self._pause = self._cancel = False
        self.bridge = None
        self.recipe = None  # the approved site recipe driving an otherwise unsupported site
        self.retyped = set()  # Fields already retyped with real keystrokes by this engine.
        self.account_credential = None
        self.verification_returned = False

    def pause(self):
        self._pause = True
        if self.bridge:
            asyncio.create_task(self.bridge.stop())

    def cancel(self):
        self._cancel = True
        if self.bridge:
            asyncio.create_task(self.bridge.stop())

    def report_phase(self, run, phase):
        if run.work_phase != phase:
            run.work_phase = phase
            self.emit(run.model_copy(deep=True))

    def checkpoint(self, run):
        self.store.save_run(run)
        self.emit(run.model_copy(deep=True))

    def intervene(self, run, message, kind='browser', field=None, value=''):
        run.status = 'needs_input'
        run.intervention_count += 1
        request = InterventionRequest(kind=kind, message=message, value=value)
        if field:
            # Row questions name their row, so the answer you give fills only that language, school or employer.
            request.field_key, request.question = field.key, question_for(field, run.profile_snapshot or ApplicantProfile())
            request.required, request.options, request.field_kind = field.required, field.options, field.kind
        run.interventions.append(request)
        # The question (never its value) goes in the log, so tools/stops.py can say which field stopped the run.
        self.store.record_event(run.id, kind, run.stage, f'{message} [{request.question}]' if request.question else message)
        self.checkpoint(run)

    async def start(self, run, profile, bridge, credential=None):
        self.bridge = bridge
        if bridge.journey is None:
            bridge.journey = ApplicationJourney(run, bridge.page)
        self.account_credential = credential
        self.verification_returned = False
        self._pause = self._cancel = False
        self.recipe = recipe_for(self.store, run.job_url)
        if run.is_submitted:
            return run
        started = time.monotonic()
        run.interventions = []
        run.status = 'running'
        run.work_phase = 'intake'
        try:
            config = translate(profile, run, self.store.answers())
            digest = config['files'].get(profile.resume_path, {}).get('digest', '')
            documents_digest = hashlib.sha256(json.dumps({path: file['digest'] for path, file in config['files'].items()}, sort_keys=True).encode()).hexdigest()
            if run.engine_version != ENGINE_VERSION or run.profile_revision != profile.revision or run.documents_digest != documents_digest:
                run.fields, run.completed_sections = {}, []
                self.store.record_event(run.id, 'checkpoints_invalidated', run.stage, 'Local adapters require fresh verification of the current draft.')
            run.engine_version = ENGINE_VERSION
            run.documents_digest = documents_digest
            run.profile_snapshot, run.profile_revision, run.resume_digest = profile.model_copy(deep=True), profile.revision, digest
            self.checkpoint(run)
            if run.submission_attempted:
                await self.confirm_submission(run)
                return run
            last_advanced_stage = None
            returned_to_job = False
            stalls = 0
            verification_retries = 0
            repaired = set()  # Sections filled again after an AI repair; each gets one.
            def stage_of(match, result, fields):
                section = match['url'] + '|' + (result.get('section') or '|'.join(f.key for f in fields))
                return match['adapter']['name'] + ':' + hashlib.sha256(section.encode()).hexdigest()[:10]
            for _ in range(100):
                if self._pause or self._cancel:
                    break
                bridge.sync_page()
                if bridge.journey and bridge.journey.blocked_reason:
                    self.intervene(run, bridge.journey.blocked_reason, 'link')
                    return run
                canonical_url(bridge.page.url)
                permitted = bridge.journey.permits(bridge.page.url) if bridge.journey else application_scope(bridge.page.url) == application_scope(run.job_url)
                if not permitted:
                    self.intervene(run, 'The tab left the selected employer. Open the selected application before resuming.')
                    return run
                self.recipe = recipe_for(self.store, bridge.page.url)
                found = await bridge.discover([self.recipe.model_dump()] if self.recipe else [])
                if self._pause or self._cancel:
                    return run
                matches = found.get('matches', [])
                accounts = [a for a in found.get('accounts', []) if a['account'].get('page')]
                if accounts:
                    matches = accounts
                if not accounts and not matches and run.account and bridge.journey and hasattr(bridge.journey, 'reopen_job') and not returned_to_job:
                    returned_to_job = True
                    problem, _ = await bridge.journey.reopen_job()
                    if problem:
                        self.intervene(run, problem, 'link')
                        return run
                    continue
                if len(matches) != 1:
                    self.intervene(run, 'More than one adapter or application frame matched. Choose the application manually.' if matches else 'No supported application form was detected. Open the application form or continue manually.')
                    return run
                match = matches[0]
                canonical_url(match['url'])
                permitted = bridge.journey.permits(match['url']) if bridge.journey else application_scope(match['url']) == application_scope(run.job_url)
                if not permitted and match['frame'] != 0 and bridge.binding is None and bridge.journey:
                    permitted = await bridge.journey.adopt_frame(match['url'])
                if not permitted:
                    self.intervene(run, 'The application frame left the selected employer. Inspect the redirect before resuming.')
                    return run
                config['adapter'] = match['adapter']['id']
                config['recipe'] = self.recipe.model_dump() if self.recipe and config['adapter'] == self.recipe.id else None
                result = await bridge.command('prepare', config, binding=match)
                if self._pause or self._cancel:
                    return run
                fields = [FormField(**f) for f in result['fields']]
                run.stage = stage_of(match, result, fields)
                if config['adapter'] == 'account':
                    if await self.account_step(run, profile, fields, bridge, self.account_credential):
                        last_advanced_stage = None
                        continue
                    return run
                await self.settle_sign_in(run, found)
                if result.get('steps'):
                    run.steps, run.step = result['steps'], result['step']
                if run.stage == last_advanced_stage:
                    # Workday saves a step before showing the next one; give the click a few seconds to land.
                    if stalls < 8:
                        stalls += 1
                        await asyncio.sleep(.5)
                        continue
                    self.intervene(run, 'The previous continuation did not reach a distinguishable section. Inspect the draft before continuing again.')
                    return run
                stalls = 0
                await self.authorize(run, profile, fields)
                if any(f.kind == 'password' for f in fields):
                    if match['adapter']['id'] == 'workday':
                        if await self.account_step(run, profile, fields, bridge, self.account_credential):
                            continue
                    else:
                        self.intervene(run, SIGN_IN_HANDOFF, 'verification')
                    return run
                if fields and (run.login_attempted or run.authentication_attempted):
                    # An application section without a sign-in form proves the sign-in worked. Workday hides Sign Out in a menu,
                    # so signed_in alone misses it, and a stale flag would refuse the saved login once the session expires overnight.
                    run.login_attempted = run.authentication_attempted = False
                    if self.account_credential and self.account_credential.get('state') != 'verified':
                        # A new account that opens its application needs no email check (seen on Halliburton's SuccessFactors).
                        await self.account_state(run, 'verified')
                    self.checkpoint(run)
                opened = not fields and (await bridge.command('open_application')).get('opened')
                if opened == 'ready':
                    continue  # A native adapter's form rendered after this scan.
                if opened:
                    # The job posting or its Start Your Application dialog. Apply Manually skips Workday's resume parser;
                    # its route (and Continue Application's) can take seconds to load, while Apply opens the dialog in place.
                    url = bridge.page.url
                    for _ in range(2 if opened == 'adventureButton' else 40):
                        await asyncio.sleep(.25)
                        if bridge.page.url != url:
                            break
                    last_advanced_stage = run.stage
                    continue
                if not fields and run.account and bridge.journey and hasattr(bridge.journey, 'reopen_job') and not returned_to_job:
                    returned_to_job = True
                    problem, _ = await bridge.journey.reopen_job()
                    if problem:
                        self.intervene(run, problem, 'link')
                        return run
                    continue
                self.report_phase(run, 'fill')
                await bridge.command('start')
                settled = await self.wait_for_section(run, profile)
                if run.login_attempted or run.authentication_attempted or (self.account_credential or {}).get('state', 'verified') != 'verified':
                    # SuccessFactors renders Sign Out seconds after its application page is first seen (Halliburton), so look again.
                    await self.settle_sign_in(run, await bridge.discover([self.recipe.model_dump()] if self.recipe else []))
                if settled and match['frame'] == 0 and settled['url'] != bridge.page.url and not (self._pause or self._cancel):
                    # Workday normalizes /apply/applyManually to /apply after rendering the form.
                    continue
                if settled and settled.get('expired') and not any(f.kind == 'password' for f in fields) and not (self._pause or self._cancel):
                    # The site's adapter ran out of time waiting on a control that never appeared, with the rest of the section untouched.
                    # A fresh runtime, which never starts the adapter, fills every field that has an approved value directly.
                    result = await bridge.command('prepare', {**config, 'direct': True}, binding=match)
                    left = [FormField(**f) for f in result['fields']]
                    if any(f.kind == 'password' for f in left):
                        # The sign-in form rendered while the adapter waited on an empty page (seen on Acronis's Workday). Filled here, its
                        # email box got the profile address, which the account flow then refused against a catch-all login.
                        await bridge.stop()
                        continue
                    # The first approved control still empty is where the adapter most likely waited; the log names it to find the cause.
                    answers = self.store.answers()
                    stuck = next((f.label for f in left if f.value in ('', False) and f.kind != 'file' and not (f.readonly or f.disabled) and resolve(f, profile, run, answers).value is not None), '')
                    self.store.record_event(run.id, 'adapter_stalled', run.stage, "The site's adapter stopped partway" + (f' near “{stuck}”' if stuck else '') +
                                            '; the rest was filled directly from your profile and answers.')
                    await self.authorize(run, profile, left)
                    settled = await self.wait_for_section(run, profile)
                # Each choose stays inside the bridge's command limit; repeat while it still selects approved options or has controls left.
                for _ in range(20):
                    if not settled or self._pause or self._cancel:
                        break
                    picked = await bridge.command('choose')
                    # A search that found no exact option still leaves the site busy (seen on Keppel's Workday picker), so it settles first too.
                    settled = await self.wait_for_section(run, profile)
                    if not (picked.get('chosen') or picked.get('more')):
                        break
                if not settled or self._pause or self._cancel:
                    return run
                self.report_phase(run, 'verify')
                scanned = await bridge.command('scan')
                fields = [FormField(**f) for f in scanned['fields']]
                if await self.retype(run, profile, fields):
                    await asyncio.sleep(.6)  # Let the site re-validate before the section is read back.
                    scanned = await bridge.command('scan')
                    fields = [FormField(**f) for f in scanned['fields']]
                await asyncio.sleep(.35)
                check = await bridge.command('snapshot')
                confirmed = [FormField(**f) for f in (await bridge.command('scan'))['fields']]
                # A change here restarts the section rather than re-reading it: a revealed conditional field or a re-render that
                # cleared values needs filling, not just verifying.
                if fields != confirmed or not check['settled'] or bridge.pending:
                    if verification_retries < 3:
                        verification_retries += 1
                        await bridge.stop()
                        await asyncio.sleep(.5)
                        continue
                    self.intervene(run, 'The form changed during section verification. Inspect it and resume.', 'validation')
                    return run
                verification_retries = 0
                settled = check
                # The section named before filling may have been a page still loading or one being left; record what was filled.
                run.stage = stage_of(match, scanned, fields)
                if scanned.get('steps'):
                    run.steps, run.step = scanned['steps'], scanned['step']
                if any(f.kind == 'password' for f in confirmed):
                    # A delayed sign-in form must go through the guarded credential flow.
                    await bridge.stop()
                    continue
                run.authentication_attempted = False
                verified = self.verify(run, profile, fields, config)
                if not verified and config['recipe']:
                    self.recipe.failures += 1
                    save_recipe(self.store, self.recipe)
                    self.store.record_event(run.id, 'recipe_stale', run.stage, 'Some fields on this recipe site could not be filled. If the site changed, teach it again or repair it with AI.')
                # A field's blocked choice (a typeahead suggestion that isn't the approved answer) is asked with the other questions,
                # even though its typed text reads back as the answer.
                asked = {i.field_key for i in run.interventions if i.field_key}
                # A problem about a control no longer on the page (seen live: one left over between Workday steps) has nothing to answer.
                present = {f.key for f in fields}
                problems = [p for p in settled['problems'] if (not p.get('field') or p['field'] in present) and (verified or (p.get('field') and p['field'] not in asked))]
                for problem in problems:
                    field = next((f for f in fields if f.key == problem.get('field')), None)
                    self.intervene(run, problem['message'], problem['kind'], field)
                if not verified or problems:
                    await self.list_options(run, profile, fields)
                    if run.stage not in repaired and await self.repair(run, profile, fields):
                        # The AI named listed options for questions still open: fill the section again with them, once.
                        repaired.add(run.stage)
                        run.intervention_count -= len(run.interventions)
                        run.interventions = []
                        await bridge.stop()
                        continue
                    return run
                if settled.get('errors'):
                    self.intervene(run, 'The application reports validation errors. Correct them before continuing.', 'validation')
                    return run
                if not fields and not settled.get("summary"):
                    # Seen on UOB's Workday after you submitted the application yourself. Only you can confirm it was sent.
                    if re.search(r"you(?:'|’)ve already applied|you have already applied", await bridge.page.inner_text('body'), re.I):
                        self.intervene(run, "The employer says you've already applied for this job. If you sent it, press I submitted it.", 'validation')
                    else:
                        self.intervene(run, 'No verifiable fields were found in this section. Review the application manually before continuing.')
                    return run
                self.checkpoint(run)
                if self._pause or self._cancel:
                    return run
                actions = settled['actions']
                if len(actions) > 1:
                    self.intervene(run, 'Several continuation or submission controls are available. Continue manually.')
                    return run
                if run.stage not in run.completed_sections:
                    run.completed_sections.append(run.stage)
                if actions and actions[0]['kind'] == 'submit':
                    if not self.verify_review(run, profile, settled.get('summary', [])):
                        return run
                    run.status = 'ready_for_review'
                    from core.automation.review import review_changes, review_values
                    changed = run.approved_review and review_changes(run.approved_review, review_values(run))
                    if changed:
                        # Approval covers exactly what you saw; anything different needs a fresh look.
                        run.approved_review = {}
                        message = f'Changed since you approved it: {", ".join(changed[:5])}{" and more" if len(changed) > 5 else ""}. Review the application again before sending.'
                        run.interventions = [InterventionRequest(kind='validation', message=message)]
                        self.store.record_event(run.id, 'approval_invalidated', run.stage, message)
                    self.checkpoint(run)
                    if run.approved_review and not self._pause and not self._cancel:
                        unconfirmed = self.unconfirmed(run)
                        if unconfirmed:
                            self.intervene(run, f'{unconfirmed} answer{"s" if unconfirmed > 1 else ""} filled by AI need your confirmation. Review the application and approve it again.', 'validation')
                            return run
                        if config['recipe'] and not self.recipe.receipt:
                            # Without a known confirmation page a send could never be confirmed, so it isn't attempted.
                            self.intervene(run, "This site's recipe doesn't know its confirmation page yet. Submit it yourself in Chromium, then press I submitted it.", 'validation')
                            return run
                        run.submission_attempted = True
                        self.checkpoint(run)
                        if self._pause or self._cancel:
                            return run
                        await bridge.command('action', {'id': actions[0]['id'], 'fields': [f.__dict__ for f in confirmed], 'summary': settled.get('summary', [])})
                        await self.confirm_submission(run)
                    return run
                if not run.auto_advance:
                    self.intervene(run, 'Section verified. Continue in the browser, then resume to fill the next section.')
                    return run
                if not actions:
                    self.intervene(run, 'Section verified. The adapter did not identify a continuation control; continue in the browser and resume.')
                    return run
                last_advanced_stage = run.stage
                await bridge.command('action', {'id': actions[0]['id'], 'fields': [f.__dict__ for f in confirmed], 'summary': settled.get('summary', [])})
                await asyncio.sleep(.5)
            if not self._pause and not self._cancel:
                self.intervene(run, 'The workflow reached its bounded section limit. Inspect the draft before resuming.')
        except asyncio.CancelledError:
            run.status = 'cancelled' if self._cancel else 'needs_input'
            raise
        except (OSError, ValueError) as exc:
            self.intervene(run, f'Check the selected profile and document files ({type(exc).__name__}).', 'profile')
        except Exception as exc:
            message = 'Check the employer receipt; automatic resubmission is disabled.' if run.submission_attempted else 'The document or extension connection changed. Inspect the draft and resume.'
            self.intervene(run, f'{message} ({type(exc).__name__})')
        finally:
            await bridge.stop()
            self.account_credential = None
            # An approval is good for one send attempt; a stop on the way there needs a fresh one.
            run.approved_review = {}
            if self._cancel:
                run.status = 'cancelled'
            elif self._pause:
                run.status = 'needs_input'
                run.interventions = [InterventionRequest(kind='browser', message='Paused by you. Resume when ready.')]
            run.elapsed_seconds += time.monotonic() - started
            self.store.record_event(run.id, run.status, run.stage)
            self.checkpoint(run)
        return run

    resume = start

    async def settle_sign_in(self, run, found):
        """A signed-in page settles the sign-in attempt and proves the saved login works."""
        if not any(a['account'].get('signed_in') for a in found.get('accounts', [])):
            return
        if run.login_attempted or run.authentication_attempted:
            # A session that expires later (overnight) needs a new attempt.
            run.login_attempted = run.authentication_attempted = False
            self.checkpoint(run)
        if run.account and not self.account_credential:
            self.account_credential = await asyncio.to_thread(self.store._vault().credential, run.account)
        if self.account_credential and self.account_credential.get('state') != 'verified':
            await self.account_state(run, 'verified')

    async def account_state(self, run, state):
        await asyncio.to_thread(self.store._vault().set_account_state, run.account, state)
        self.account_credential['state'] = state
        self.checkpoint(run)

    async def account_signed_in(self):
        return False

    async def switch_account_page(self, run, bridge, create=False):
        if not (await bridge.command('open_create_account' if create else 'open_sign_in')).get('opened'):
            return False
        document = (bridge.binding or {}).get('document')
        expected = 'create' if create else 'sign_in'
        for _ in range(self.AUTH_POLLS):
            await asyncio.sleep(.25)
            if self._pause or self._cancel:
                return False
            found = await bridge.discover()
            accounts = found.get('accounts', [])
            if len(accounts) == 1 and (accounts[0]['account'].get('page') == expected or accounts[0]['document'] != document or accounts[0]['account'].get('signed_in')):
                return True
        return False

    async def account_step(self, run, profile, fields, bridge, credential=None):
        """One document-bound account step; a saved attempt is never replayed automatically."""
        auth = await bridge.command('auth_page')
        if auth['page'] == 'loading':
            await asyncio.sleep(.25)
            return True
        if auth['page'] == 'email_choice':
            if await self.switch_account_page(run, bridge):
                return True
            self.intervene(run, SIGN_IN_HANDOFF, 'verification')
            return False
        if auth['page'] in {'challenge', 'ambiguous'}:
            self.intervene(run, 'Complete CAPTCHA, MFA or the unfamiliar sign-in form in Chromium, then resume.', 'verification')
            if auth['page'] == 'challenge':
                run.interventions[-1].field_key = 'account-challenge'
                self.checkpoint(run)
            return False
        context = account_context(bridge.binding['url'])
        if context is None:
            self.intervene(run, 'This shared sign-in site does not identify the employer tenant. Complete sign-in manually; no credentials were sent.', 'verification')
            return False
        if auth.get('action'):
            try:
                action = canonical_url(auth['action'])
                receiver = account_context(action)
                if urlsplit(action).hostname != urlsplit(bridge.binding['url']).hostname or receiver and receiver.key != context.key:
                    self.intervene(run, 'The account form sends credentials to a different or unverified account site. Complete sign-in manually; no credentials were entered.', 'verification')
                    return False
            except ValueError:
                self.intervene(run, 'The account form has an unsupported destination. No credentials were entered.', 'verification')
                return False
        context.return_url = run.listing_url or run.job_url
        if run.account and run.account.key == context.key:
            context.item_id = run.account.item_id
        elif run.account:
            credential = None
            run.registration_attempted = run.login_attempted = False
        run.account = context
        try:
            run.stage = CHECKING_LOGIN
            self.checkpoint(run)
            if credential is None:
                credential = await asyncio.to_thread(self.store._vault().credential, context)
                if credential:
                    self.store.record_event(run.id, 'login_found', run.stage, f'Found the saved login for {context.tenant} in 1Password.')
            if credential:
                credential.setdefault('state', 'verified')
            self.account_credential = credential
            self.checkpoint(run)
            if auth.get('signed_in'):
                if credential:
                    await self.account_state(run, 'verified')
                return True
            if auth['page'] == 'verification':
                if credential and credential.get('state') == 'creation_attempted':
                    await self.account_state(run, 'pending_verification')
                if not run.verification_continued:
                    self.intervene(run, ACTIVATION_HANDOFF.format((credential or {}).get('username', profile.email)), 'activation')
                    return False
                if await self.switch_account_page(run, bridge):
                    return True
                # A verification page may not offer Sign In. Re-enter through the job, never an expired signup URL.
                if self.verification_returned:
                    self.intervene(run, 'The employer still shows email verification. Complete it in Chromium, then choose Continue after verification.', 'activation')
                    return False
                self.verification_returned = True
                if bridge.journey:
                    bridge.journey.expect()
                await bridge.page.goto(context.return_url, wait_until='domcontentloaded')
                return True
            if not credential:
                if auth['page'] == 'created':
                    self.intervene(run, 'The employer confirms account creation, but its login is missing from 1Password. Save the existing login in Job Sites, then resume; no new registration was attempted.', 'verification')
                    return False
                if run.registration_attempted:
                    self.intervene(run, 'Registration was already attempted, but its saved login is missing. Restore the login in 1Password or sign in manually; no new account was created.', 'verification')
                    return False
                if not self.store.get('auto_create_accounts', self.store.get('auto_create_workday_accounts', False)):
                    self.intervene(run, 'No login is saved for this employer. Enable automatic account creation under Profile → Employer accounts, or sign in manually.', 'verification')
                    return False
                if auth['page'] != 'create':
                    if await self.switch_account_page(run, bridge, create=True):
                        return True
                    self.intervene(run, 'No account-creation link could be identified. Open Create Account in Chromium, then resume.', 'verification')
                    return False
                recipe = password_recipe(auth)
                if not recipe:
                    self.intervene(run, 'The password requirements could not be satisfied. Create the login in 1Password and continue manually.', 'verification')
                    return False
                username = login_address(context.tenant.split('/')[-1], profile.email, self.store.get('catchall_domain', ''), self.store.get('catchall_format', ''))
                run.stage = SAVING_LOGIN
                self.checkpoint(run)
                await asyncio.to_thread(self.store._vault().save_credential, context, username, None, 'new', password_recipe=recipe)
                credential = await asyncio.to_thread(self.store._vault().credential, context)
                if not credential.get('username') or not credential.get('password'):
                    raise RuntimeError('The saved 1Password login could not be read back. No account was submitted.')
                self.store.record_event(run.id, 'login_saved', run.stage, f'Saved a new login for {context.tenant} in 1Password.')
                self.account_credential = credential
                self.checkpoint(run)
            state = credential.get('state', 'verified')
            policy = auth.get('policy', {})
            if state == 'new' and auth['page'] == 'create' and self.store.get('auto_create_accounts', self.store.get('auto_create_workday_accounts', False)) and not policy.get('minimum', 0) <= len(credential['password']) <= policy.get('maximum', 64) and password_recipe(auth):
                # A login the bot saved but never submitted, whose password this form's length rule rejects (seen on Halliburton: 24 saved, 20 allowed).
                await asyncio.to_thread(self.store._vault().regenerate_password, context, password_recipe(auth))
                credential = await asyncio.to_thread(self.store._vault().credential, context)
                self.store.record_event(run.id, 'login_saved', run.stage, f'Replaced the unused password for {context.tenant} in 1Password with one the form accepts.')
                self.account_credential = credential
            if auth['page'] == 'created':
                await self.account_state(run, 'created')
                if await self.switch_account_page(run, bridge):
                    return True
                self.intervene(run, 'The account was created. Open the employer sign-in page in Chromium, then resume.', 'verification')
                return False
            if state in {'creation_attempted', 'pending_verification'} and not run.verification_continued:
                if auth.get('form_error'):
                    self.intervene(run, REJECTED_ACCOUNT, 'verification')
                elif state == 'pending_verification':
                    self.intervene(run, ACTIVATION_HANDOFF.format(credential['username']), 'activation')
                else:
                    self.intervene(run, 'Account creation was attempted, but its outcome is uncertain. Check the employer page or email before continuing; registration will not be repeated.', 'verification')
                return False
            create = state == 'new'
            expected = 'create' if create else 'sign_in'
            if auth['page'] != expected:
                if await self.switch_account_page(run, bridge, create=create):
                    return True
                self.intervene(run, 'Open the employer Create Account page in Chromium, then resume.' if create else SIGN_IN_HANDOFF, 'verification')
                return False
            if run.verification_continued:
                run.login_attempted = False
                run.authentication_attempted = False
                run.verification_continued = False
                self.checkpoint(run)
            attempted = run.registration_attempted if create else run.login_attempted or (run.authentication_attempted and not run.registration_attempted)
            if attempted:
                self.intervene(run, REJECTED_ACCOUNT if create else SIGN_IN_HANDOFF, 'verification')
                return False
            credentials = set(auth['credentials'])
            policies = {}
            for field in fields:
                if field.selector in credentials:
                    continue
                label = normalized(field.label)
                marketing = field.kind == 'checkbox' and (field.selector in auth.get('marketing', []) or bool(re.search(r'marketing|newsletter|job alerts|promotional|future opportunities|talent community', label)))
                terms = field.kind == 'checkbox' and (field.required or field.selector in auth.get('required_terms', [])) and bool(re.search(r'terms|privacy', label))
                resolution = resolve(field, profile, run, self.store.answers())
                value = False if marketing else True if terms else resolution.value
                # An optional box nobody answered ("Notification: receive new job postings", seen on Halliburton) stays unticked; one that reads like consent is still asked.
                optional = field.kind == 'checkbox' and value is None and not resolution.omit and not field.required and not re.search(r'terms|privacy|agree|consent|accept', label)
                if optional:
                    value = False
                omit = resolution.omit or value is None and not field.required and field.kind != 'checkbox'
                if value is None and not omit:
                    self.intervene(run, resolution.reason, 'answer', field)
                    return False
                policies[field.selector] = dict(key=field.key, label=field.label, value=value, omit=omit, ref=resolution.ref, replace=terms or marketing or optional)
            await bridge.command('authorize', {'policies': policies})
            try:
                await bridge.command('validate_authentication', {'credential': {'username': credential['username'], 'password': credential['password']}})
            except Exception:
                self.intervene(run, 'The account form changed or rejected the saved values. Inspect the form and check the login in 1Password; nothing was submitted.', 'verification')
                return False
            if self._pause or self._cancel:
                return False
            # Write the uncertain state before the remote click, including across runs for the same account.
            run.stage = CREATING_ACCOUNT if create else SIGNING_IN
            self.store.record_event(run.id, 'account_creation_attempted' if create else 'sign_in_attempted', run.stage,
                                    f"{'Creating an account on' if create else 'Signing in to'} {context.tenant} with the 1Password login.")
            if create:
                await self.account_state(run, 'creation_attempted')
                run.registration_attempted = True
            else:
                run.login_attempted = True
            run.authentication_attempted = True
            self.checkpoint(run)
            if self._pause or self._cancel:
                return False
            await bridge.command('authenticate', {'credential': {'username': credential['username'], 'password': credential['password']}})
            for _ in range(self.AUTH_POLLS):
                await asyncio.sleep(.25)
                if self._pause or self._cancel:
                    return False
                if bridge.journey and bridge.journey.blocked_reason:
                    self.intervene(run, bridge.journey.blocked_reason, 'link')
                    return False
                found = await bridge.discover()
                accounts = found.get('accounts', [])
                observation = accounts[0]['account'] if len(accounts) == 1 else {}
                if observation.get('signed_in') or await self.account_signed_in():
                    self.store.record_event(run.id, 'signed_in', run.stage, f'Signed in to {context.tenant}.')
                    if credential.get('state') != 'verified':
                        await self.account_state(run, 'verified')
                    return True
                if observation.get('page') == 'verification':
                    if create:
                        await self.account_state(run, 'pending_verification')
                    self.intervene(run, ACTIVATION_HANDOFF.format(credential['username']), 'activation')
                    return False
                if observation.get('form_error') or observation.get('page') not in {None, expected}:
                    return True
                if not accounts and found.get('matches'):
                    return True
            self.intervene(run, 'Account creation was attempted, but its outcome is uncertain. Check the employer page before continuing; registration will not be repeated.' if create else SIGN_IN_HANDOFF, 'verification')
            return False
        except AmbiguousLogins as exc:
            self.intervene(run, str(exc), 'verification')
            run.interventions[-1].field_key = '1password-item'
            run.interventions[-1].options = exc.options
            self.checkpoint(run)
            return False
        except (RuntimeError, ValueError) as exc:
            self.intervene(run, str(exc), 'verification')
            return False

    async def authorize(self, run, profile, fields):
        await self.ai_autofill(run, profile, fields)
        answers = self.store.answers()
        policies = {}
        for field in fields:
            resolution = resolve(field, profile, run, answers)
            policies[field.selector] = dict(key=field.key, label=field.label, value=resolution.value, omit=resolution.omit, ref=resolution.ref,
                                           replace=resolution.ref.startswith('answer:') and not resolution.ai)
            if resolution.value is not None and field.kind not in ('file', 'password') and field.value not in ('', False) and self.holds(field, resolution.value, resolution.ref, fields):
                policies[field.selector]['held'] = field.value  # Already right: the page keeps it while it still shows this.
        await self.bridge.command('authorize', {'policies': policies})

    def unconfirmed(self, run):
        """How many of this run's fields were filled from AI answers you haven't confirmed."""
        ids = {'answer:' + a.id for a in self.store.answers() if a.origin == 'ai'}
        return sum(f.answer_ref in ids for f in run.fields.values())

    async def ai_autofill(self, run, profile, fields, listed=False):
        """Ask the optional AI provider about unanswered factual questions and record what it can answer from your own data.

        listed: the fields carry options listed by opening their dropdowns after verification failed. Those questions are asked once more,
        and an answer the form didn't take (no listed option has its wording) goes with them, so the reply can name the form's option for it.
        Returns how many answers were saved."""
        answers = self.store.answers()
        questions, current = {}, {}
        asked, rows = {}, set()
        standing = bool(profile.standing_answers.strip())
        for field in fields:
            # A personal or legal question goes as wording only, to be pointed at your saved answer or profile field; your answer to
            # one never leaves, so it has no repair.
            factual = askable(field, standing)
            if not (factual or pointer_only(field)):
                continue
            found = resolve(field, profile, run, answers)
            mismatched = factual and listed and field.options and found.value is not None and not isinstance(found.value, bool) and not any(same_choice(o, found.value) for o in field.options)
            # A row's listed question is asked and answered under its row's name ("Language — Chinese (Mandarin)"): saved under the bare
            # label, an answer counts as the first row's (seen live: a match for the Mandarin row would have changed the English row).
            name = question_for(field, profile) if listed and field.group else field.label
            # A different answer the form didn't take is a new question for the AI; the same one is never sent twice.
            key = normalized(name) + ('|listed' if listed else '') + ('' if factual else '|pointer') + ('=' + normalized(str(found.value)) if mismatched else '')
            if key in run.ai_asked:
                continue
            if found.reason == UNANSWERED or mismatched:
                asked[name] = key
                if name != field.label:
                    rows.add(name)
                question = questions.setdefault(name, replace(field, label=name, options=list(field.options)))
                if field.kind == 'radio' and field.option and field.option not in question.options:
                    question.options.append(field.option)  # Each radio button is its own field; the question offers them all.
                if mismatched:
                    current[name] = (found.value, found.ref)
        if not questions or not self.store.get('automation_options', {}).get('ai_match', True):
            return 0
        try:
            cfg = ai_config(self.store)
        except Exception:
            cfg = None  # The keychain could not be read; the questions are asked as usual.
        if not cfg:
            return 0
        if not cfg['facts']:
            # Your answers, and the schools, employers and languages that name your rows, are career data: they leave only where career facts may.
            questions = {label: q for label, q in questions.items() if label not in current and label not in rows}
            current = {}
            if not questions:
                return 0
        pointers = {label for label, q in questions.items() if not askable(q, standing)}
        usable = applicable(answers, profile, run)
        # A saved question that names one of your rows is career data, like the row questions above.
        offered = lambda a: matchable(a, bool(pointers)) and (cfg['facts'] or not names_row(a.question, profile))
        known = [a for a in usable if offered(a)]
        # Your own answers given for another application or employer are offered too, by wording alone. Each wording is offered once,
        # and only when every answer to it agrees.
        # ponytail: a wording with differing answers ("Why us?") is skipped; rank by recency if that drops too much.
        taken, others = {canonical(a.question) for a in known}, {}
        for a in answers if run.reuse_answers else ():
            if (a not in usable and a.profile_name == run.profile_name and a.origin == 'you' and not a.omit and not a.rewords
                    and (not a.country or normalized(a.country) == normalized(profile.country)) and offered(a)
                    and canonical(a.question) not in taken):
                others.setdefault(canonical(a.question), []).append(a)
        said = lambda a: (normalized(str(field_value(FormField('', '', '', 'text'), a.value))), a.fact)  # True is "Yes" wherever it was saved.
        known += [group[0] for group in others.values() if len({said(a) for a in group}) == 1]
        seconds = self.AI_LOCAL_SECONDS if cfg['local'] else self.AI_MATCH_SECONDS
        run.ai_requests += 1
        # The log records what kind of data left, never the content.
        self.store.record_event(run.id, 'ai_request', run.stage, f"{cfg['name']} {'on this Mac' if cfg['local'] else '(cloud)'}: "
                                f"{len(questions)} question{'s' if len(questions) > 1 else ''}; career facts {'included' if cfg['facts'] else 'not sent'}{'; standing answers included' if profile.standing_answers.strip() else ''}.")
        try:
            results = await asyncio.wait_for(asyncio.to_thread(autofill, cfg, list(questions.values()), [a.question for a in known], profile,
                                                               {label: value for label, (value, _) in current.items()}), seconds)
        except TimeoutError:
            self.store.record_event(run.id, 'ai_match_failed', run.stage, f'The AI did not answer within {seconds} s; these questions are asked instead.')
            return 0
        except Exception as exc:
            # AI is a convenience: unanswered questions are still asked as usual.
            self.store.record_event(run.id, 'ai_match_failed', run.stage, str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
            return 0  # Not recorded as asked, so the next section or resume tries these questions again.
        # Kept with the run once answered, so a resume never sends the same question again.
        run.ai_asked.extend(asked[label] for label in questions)
        saved = 0
        for label, (kind, value) in results.items():
            saved += 1
            if label in current and kind != 'value':
                saved -= 1
                continue  # Only one of the listed options can replace an answer the form didn't take.
            field = questions[label]
            if label in pointers and kind not in ('saved', 'fact'):
                saved -= 1
                continue  # A personal or legal question is never answered in the AI's words.
            if kind == 'saved':
                answer = known[value]
                if (answer in usable and asks(answer, label)) or (label not in pointers and not matchable(answer)):
                    saved -= 1
                    continue  # Matched to the answer it already has (seen live), or a factual question to a personal answer: nothing new.
                if answer in usable and label not in pointers:
                    answer.variants.append(label)
                    self.store.save_answer(answer)
                    self.store.record_event(run.id, 'answer_matched', run.stage, f'AI matched “{label}” to your answer for “{answer.question}”.')
                    continue
                # Borrowed from another application or employer, or a personal or legal match: copied here on this Mac for this
                # application only, and unconfirmed until you review it.
                found = linked(field, profile, answer.fact).value if answer.fact else field_value(field, answer.value)
                if found in (None, '') or (field.options and not any(same_choice(o, found) for o in field.options)):
                    saved -= 1
                    continue  # Your answer isn't one of this form's options; ask instead.
                answer = ApprovedAnswer(question=label, value=answer.value, fact=answer.fact, profile_name=run.profile_name, scope='application',
                                        scope_key=run.id, country=answer.country, origin='ai')
                note = f'AI matched “{label}” to your answer for “{known[value].question}”.'
            elif kind == 'fact':
                found = linked(field, profile, value).value
                if found is None or (field.options and not any(same_choice(o, found) for o in field.options)):
                    saved -= 1
                    continue  # The profile's wording isn't one of the form's options; ask instead.
                answer = ApprovedAnswer(question=label, fact=value, profile_name=run.profile_name, origin='ai',
                                        **(dict(scope='application', scope_key=run.id) if label in pointers else dict(scope='global')))
                note = f'AI linked “{label}” to your profile ({value}).'
            elif label in current:
                # The form's own option for your answer, at your answer's scope; one for every employer is kept for this employer,
                # whose form will list the same options next time.
                mine, ref = current[label]
                source = next((a for a in answers if 'answer:' + a.id == ref), None)
                scope = 'employer' if source is None or source.scope == 'global' else source.scope
                answer = ApprovedAnswer(question=label, value=value, profile_name=run.profile_name, scope=scope, rewords=str(mine),
                                        scope_key=employer_key(run.job_url) if scope == 'employer' else source.scope_key, origin='ai')
                note = f'AI matched your answer for “{label}” to the form\'s option “{value}”.'
            elif kind == 'standing':
                # Your standing statements hold for every application, and this employer's next form words the question the same way.
                answer = ApprovedAnswer(question=label, value=value, profile_name=run.profile_name, scope='employer', scope_key=employer_key(run.job_url), origin='ai')
                note = f'AI answered “{label}” from your standing answers.'
            else:
                # Derived from today's career facts, so it applies to this application only.
                answer = ApprovedAnswer(question=label, value=value, profile_name=run.profile_name, scope='application', scope_key=run.id, origin='ai')
                note = f'AI answered “{label}” from your career facts.'
            self.store.save_answer(answer)
            self.store.record_event(run.id, 'answer_ai', run.stage, note + ' Confirm it under Answers.')
        return saved

    @staticmethod
    def shows(field, value):
        """Whether the control displays this value (a month spinbutton may show "06" for 6)."""
        held, wanted = str(field.value), str(value)
        return normalized(held) == normalized(wanted) or field.kind == 'spinbutton' and held.isdigit() and wanted.isdigit() and int(held) == int(wanted)

    @staticmethod
    def holds(field, value, ref, fields):
        """Whether a (non-file) control already shows this approved value. Verification and the page's fill both use it,
        so the bot never calls its own earlier fill a conflict."""
        if field.kind == 'radio':
            offered = any(f.kind == 'radio' and f.label == field.label and f.group == field.group and f.row == field.row and same_choice(f.option, value) for f in fields)
            return offered and field.value == same_choice(field.option, value)
        if field.kind in CHOICE_KINDS and not isinstance(value, bool):
            return same_choices(field.value, value)  # "Mr." for "Mr", "Singapore, SGP" for "Singapore", every skill of a list.
        if field.kind == 'spinbutton' and str(field.value).isdigit() and str(value).isdigit():
            return int(field.value) == int(value)  # A typed month reads back "06" for 6.
        if ref in ('profile:phone', 'profile:phone_number') or field.kind == 'tel':
            # Employers reformat phone numbers ("55512345" becomes "5551 2345") and may prefix the country code ("(+65) 55512345").
            held, wanted = re.sub(r'\D', '', str(field.value)), re.sub(r'\D', '', str(value))
            return held == wanted or len(wanted) >= 6 and held.endswith(wanted) and len(held) - len(wanted) <= 3
        if isinstance(value, bool):
            return field.value == value
        # Location typeaheads add the region to the place you picked ("Singapore" becomes "Singapore, SGP" on Lever).
        return normalized(str(field.value)) == normalized(str(value)) or bool(re.search(r'location|city', field.label, re.I)) and same_choice(field.value, value)

    async def retype(self, run, profile, fields):
        """Retype, with real keystrokes, approved values that a control shows but the site rejected.

        Seen on Workday: a date part filled by the extension looks right, yet the form calls it invalid until a person types it."""
        answers, typed = self.store.answers(), 0
        binding = (self.bridge.binding or {}).get('url')
        frame = next((f for f in self.bridge.page.frames if f.url == binding), self.bridge.page.main_frame)
        for field in fields:
            if not field.invalid or field.kind not in TYPED_KINDS or (run.stage, field.key) in self.retyped or self._pause or self._cancel:
                continue
            value = resolve(field, profile, run, answers).value
            if value is None or isinstance(value, bool) or not self.shows(field, value):
                continue
            self.retyped.add((run.stage, field.key))
            if not (await self.bridge.command('mark', {'selector': field.selector})).get('marked'):
                continue
            control = frame.locator('[data-intern-retype]')
            text = f'{int(value):02d}' if field.kind == 'spinbutton' and normalized(field.label).endswith('month') and str(value).isdigit() else str(value)
            try:
                await control.click(timeout=2000)
                await control.press('ControlOrMeta+a')
                await control.press('Backspace')
                await control.press_sequentially(text, delay=40)
                await control.press('Tab')  # Workday saves date parts and text on blur.
            except Exception:
                continue  # The control moved or vanished; verification asks for it as before.
            typed += 1
            self.store.record_event(run.id, 'retyped', run.stage, f'The form rejected “{field.label}” as filled, so it was typed again key by key.')
        return typed

    async def wait_for_section(self, run, profile):
        for _ in range(self.SECTION_POLLS):
            if self._pause or self._cancel:
                return None
            snapshot = await self.bridge.command('snapshot')
            if snapshot['proposals']:
                fields = [FormField(**f) for f in (await self.bridge.command('scan'))['fields']]
                await self.authorize(run, profile, fields)
            if snapshot['settled'] and not self.bridge.pending and (snapshot['status'] in {'prepared','autofill-complete','page-complete','complete-required','complete-manually','action-pending'} or not snapshot['live']):
                return snapshot
            await asyncio.sleep(.1)
        self.intervene(run, 'The adapter did not finish within its bounded wait. Inspect the form and resume.')
        return None

    async def repair(self, run, profile, fields):
        """The one AI call made after the free fixes: questions still open whose dropdown options are now listed."""
        answers = self.store.answers()
        # Options the scan already had (radios, selects) went with the first request; only an answer they didn't take goes again.
        listed = [replace(field, options=request.options) for request in run.interventions if request.options and request.field_key
                  for field in fields if field.key == request.field_key and field.kind in CHOICE_KINDS
                  and not (field.options and resolve(field, profile, run, answers).reason == UNANSWERED)]
        return await self.ai_autofill(run, profile, listed, listed=True) if listed else 0

    async def list_options(self, run, profile, fields):
        # Workday dropdowns render their options only while open; list them so the answer can be an exact choice.
        # Prompts show results only for a search: the approved answer, else whatever is typed in them.
        answers = self.store.answers()
        for request in run.interventions:
            field = next((f for f in fields if f.key == request.field_key and f.kind == 'combobox' and not f.options), None)
            if field and not request.options:
                query = resolve(field, profile, run, answers).value
                try:
                    request.options = (await self.bridge.command('options', {'selector': field.selector, 'query': '' if query is None else str(query)})).get('options', [])
                except TimeoutError:
                    continue  # A slow search leaves this question without listed options instead of ending the run.
        self.checkpoint(run)

    def verify(self, run, profile, fields, config):
        answers = self.store.answers()
        ok = True
        # Replace this section's evidence as a unit; removed conditional controls are no longer applicable.
        run.fields = {k: v for k, v in run.fields.items() if v.section != run.stage}
        for field in fields:
            resolution = resolve(field, profile, run, answers)
            reason = ''
            # A control with no readable label has no question to ask or answer to keep: what you set in the browser stands.
            unlabelled = not field.label and resolution.value is None
            # An optional question with no answer is left blank (the review shows it) instead of stopping the run.
            omitted = (resolution.omit or unlabelled or resolution.reason == UNANSWERED) and not field.required and field.value in ('', False)
            if omitted:
                matched = True
            elif unlabelled:
                matched = field.value not in ('', False) and not field.invalid
                reason = 'This field has no readable label. Set it in Chromium, then resume.'
            elif resolution.value is None:
                matched = False
                reason = resolution.reason
            elif field.kind == 'file':
                descriptor = config['files'].get(str(resolution.value), {})
                matched = bool(descriptor) and field.file_digest == descriptor['digest'] and not field.invalid
                reason = 'The exact uploaded file and its accepted state could not be verified.'
            else:
                matched = self.holds(field, resolution.value, resolution.ref, fields) and not field.invalid
            if not matched:
                ok = False
                reason = reason or ('The form rejected this value. Answer it in the format the form asks for.' if field.invalid and field.value not in ('', False) and resolution.value is not None and self.shows(field, resolution.value)
                                    else 'Existing browser value conflicts with the profile. Resolve it before resuming.' if field.value not in ('', False)
                                    else 'The form did not take the approved value. Set this field in Chromium, then resume, or correct the answer.')
            key = run.stage + ':' + field.key
            run.fields[key] = FieldAssessment(key=key, label=field.label or 'Unlabelled field', section=run.stage, required=field.required, group=field.group, row=field.row, kind=field.kind,
                answer_ref=resolution.ref, disposition='intentionally_omitted' if omitted else 'verified' if matched else 'needs_input',
                evidence='Exact file digest and DOM validity' if matched and field.kind == 'file' else 'Section DOM read-back' if matched else '',reason='' if matched else reason,
                value='' if field.kind == 'password' else field.value, option=field.option)
            if not matched:
                # The question is asked starting from what the form holds (a radio group's selected choice), else the saved answer it didn't take.
                held = '' if field.kind in ('file', 'password') else field.value if field.kind != 'radio' else next(
                    (f.option for f in fields if f.kind == 'radio' and f.value is True and (f.label, f.group, f.row) == (field.label, field.group, field.row)), '')
                start = held if held not in ('', False) else '' if resolution.value is None else resolution.value
                self.intervene(run, reason, 'conflict' if 'conflict' in reason else 'answer', field, start)
        if config.get('adapter') == 'workday':
            # Workday adds one row per profile entry; a stalled adapter (or a direct fill, which never clicks Add) can leave some out,
            # and every field of the rows that do exist would still verify.
            for group, noun in (('education', 'education'), ('experience', 'work experience'), ('language_proficiency', 'language')):
                wanted = len(profile_rows(profile, group))
                shown = {f.row for f in fields if f.group == group and f.row < wanted}
                if shown and len(shown) < wanted:
                    ok = False
                    self.intervene(run, f'The form shows {len(shown)} of your {wanted} {noun} entries. Add the missing ones in Chromium, then resume.', 'validation')
        return ok

    def verify_review(self, run, profile, summary):
        previous = [a for a in run.fields.values() if a.section != run.stage and a.disposition == "verified"]
        if previous and summary and all(s.get('layout') == 'workday' for s in summary):
            from core.automation.review import workday_review_error
            evidence = [a for a in run.fields.values() if a.section != run.stage and a.disposition in {'verified', 'intentionally_omitted'}]
            error = workday_review_error(evidence, summary, profile, run, self.store.answers())
            if error:
                self.intervene(run, error, 'validation')
            return not error
        if not previous and not summary:
            if any(a.section == run.stage and a.disposition == "verified" for a in run.fields.values()):
                return True
            self.intervene(run, "No verified application fields are available for final review.", "validation")
            return False
        if not previous:
            self.intervene(run, "This review has no verified preparation checkpoints. Return to the first application section and resume.", "validation")
            return False
        accounted = set()
        for assessment in previous:
            field = FormField(key=assessment.key, label=assessment.label, selector='', kind=assessment.kind,
                              group=assessment.group, row=assessment.row, required=assessment.required)
            resolution = resolve(field, profile, run, self.store.answers())
            value = Path(str(resolution.value)).name if field.kind == 'file' else resolution.value
            accepted = ({'yes', 'true', 'checked'} if value else {'no', 'false', 'unchecked'}) if isinstance(value, bool) else {normalized(str(value))}
            identity = (normalized(field.label), field.group, field.row)
            candidates = [s for s in summary if (normalized(s['label']), s['group'], s['row']) == identity]
            if resolution.value is None or len(candidates) != 1 or normalized(candidates[0]['value']) not in accepted:
                self.intervene(run, f"Cannot independently reconcile '{field.label}' on this review. Inspect the saved value before submitting.", 'validation', field)
                return False
            accounted.add(identity)
        if any((normalized(s['label']), s['group'], s['row']) not in accounted and s['value'] for s in summary):
            self.intervene(run, 'The review contains a value without a verified preparation checkpoint. Inspect the application before submitting.', 'validation')
            return False
        return True

    async def confirm_submission(self, run):
        # Confirmation is read-only and deliberately separate from vendor saved-application events.
        for _ in range(self.RECEIPT_POLLS):
            from urllib.parse import urlsplit
            expected = urlsplit(self.bridge.binding['url'] if self.bridge.binding else run.job_url)
            frames = [frame for frame in self.bridge.page.frames if urlsplit(frame.url).scheme == 'https' and urlsplit(frame.url).hostname == expected.hostname]
            received = False
            if len(frames) == 1:
                receipts = frames[0].locator('[data-automation-id="applicationSubmitted"],#application_confirmation,.application-confirmation,.ashby-application-form-success-message,.thanks,h1,h2,[role=status]')
                for receipt in await receipts.all():
                    if await receipt.is_visible() and normalized(await receipt.inner_text()) in {'application submitted','your application has been submitted','thank you for applying','your application has been received', *([normalized(self.recipe.receipt)] if self.recipe and self.recipe.receipt else [])}:
                        received = True
                        break
            if received:
                run.submission_confirmed = True
                run.submitted_at = run.submitted_at or now()
                run.pipeline, run.status = 'applied', 'ready_for_review'
                self.store.record_event(run.id, 'submission_confirmed', run.stage)
                return
            if self._pause or self._cancel:
                break
            await asyncio.sleep(.25)
        self.intervene(run, 'Submission was attempted once, but an employer receipt could not be verified. Inspect the browser or confirm it manually; automatic resubmission is disabled.', 'verification')
