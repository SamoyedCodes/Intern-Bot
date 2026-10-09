"""Section verification around the local extension's site-specific filling work."""
import asyncio
import hashlib
import json
import time

from core.automation.answers import resolve
from core.automation.models import FieldAssessment, InterventionRequest, normalized, now, employer_key, canonical_url
from pathlib import Path
from core.automation.speedy_profile import translate
from core.automation.privacy import configure_privacy
from core.automation.fields import FormField

ENGINE_VERSION = 'speedyapply-local-2.28.0-v1'
SIGN_IN_HANDOFF = 'Complete employer sign-in or activation in Chromium, then resume. Saved credentials remain in the operating-system keychain; an existing authentication attempt will not be repeated.'
ACTIVATION_HANDOFF = "Check {} for Workday's verification email and open its link, then click I've verified my account."
REJECTED_ACCOUNT = "Workday didn't accept the new account. It may already exist: sign in or reset the password in Chromium, save that login under Profile → Workday logins, then resume."


class ApplicationEngine:
    def __init__(self, store, emit=None):
        configure_privacy()
        self.store, self.emit = store, emit or (lambda run: None)
        self._pause = self._cancel = False
        self.bridge = None

    def pause(self):
        self._pause = True
        if self.bridge:
            asyncio.create_task(self.bridge.stop())

    def cancel(self):
        self._cancel = True
        if self.bridge:
            asyncio.create_task(self.bridge.stop())

    def checkpoint(self, run):
        self.store.save_run(run)
        self.emit(run.model_copy(deep=True))

    def intervene(self, run, message, kind='browser', field=None):
        run.status = 'needs_input'
        run.intervention_count += 1
        request = InterventionRequest(kind=kind, message=message)
        if field:
            request.field_key, request.question = field.key, field.label
            request.required, request.options = field.required, field.options
        run.interventions.append(request)
        self.store.record_event(run.id, kind, run.stage, message)
        self.checkpoint(run)

    async def start(self, run, profile, bridge, credential=None):
        self.bridge = bridge
        self._pause = self._cancel = False
        if run.is_submitted:
            return run
        started = time.monotonic()
        run.interventions = []
        run.status = 'running'
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
            for _ in range(60):
                if self._pause or self._cancel:
                    break
                canonical_url(bridge.page.url)
                if employer_key(bridge.page.url) != employer_key(run.job_url):
                    self.intervene(run, 'The tab left the selected employer. Open the selected application before resuming.')
                    return run
                found = await bridge.discover()
                if self._pause or self._cancel:
                    return run
                matches = found.get('matches', [])
                if len(matches) != 1:
                    self.intervene(run, 'More than one adapter or application frame matched. Choose the application manually.' if matches else 'No supported application form was detected. Open the application form or continue manually.')
                    return run
                match = matches[0]
                canonical_url(match['url'])
                if bridge.binding and employer_key(match['url']) != employer_key(bridge.binding['url']):
                    self.intervene(run, 'The application frame left the selected employer. Inspect the redirect before resuming.')
                    return run
                config['adapter'] = match['adapter']['id']
                result = await bridge.command('prepare', config, binding=match)
                if self._pause or self._cancel:
                    return run
                fields = [FormField(**f) for f in result['fields']]
                section = match['url'] + '|' + (result.get('section') or '|'.join(f.key for f in fields))
                run.stage = match['adapter']['name'] + ':' + hashlib.sha256(section.encode()).hexdigest()[:10]
                if run.stage == last_advanced_stage:
                    self.intervene(run, 'The previous continuation did not reach a distinguishable section. Inspect the draft before continuing again.')
                    return run
                await self.authorize(run, profile, fields)
                if any(f.kind == 'password' for f in fields):
                    if match['adapter']['id'] == 'workday' and credential:
                        if await self.account_step(run, profile, fields, bridge, credential):
                            continue
                    else:
                        self.intervene(run, SIGN_IN_HANDOFF, 'verification')
                    return run
                if run.authentication_attempted and fields and credential and credential.get('state') == 'pending_verification':
                    # This run's Create Account click led straight into the application: the tenant needed no email verification.
                    self.store._vault().set_account_state(run.job_url, 'verified')
                    credential['state'] = 'verified'
                run.authentication_attempted = False
                await bridge.command('start')
                settled = await self.wait_for_section(run, profile)
                if not settled or self._pause or self._cancel:
                    return run
                fields = [FormField(**f) for f in (await bridge.command('scan'))['fields']]
                await asyncio.sleep(.35)
                check = await bridge.command('snapshot')
                confirmed = [FormField(**f) for f in (await bridge.command('scan'))['fields']]
                if fields != confirmed or not check['settled'] or bridge.pending:
                    self.intervene(run, 'The form changed during section verification. Inspect it and resume.', 'validation')
                    return run
                settled = check
                if not self.verify(run, profile, fields, config):
                    return run
                problems = settled['problems']
                if problems:
                    for problem in problems:
                        field = next((f for f in fields if f.key == problem.get('field')), None)
                        self.intervene(run, problem['message'], problem['kind'], field)
                    return run
                if settled.get('errors'):
                    self.intervene(run, 'The application reports validation errors. Correct them before continuing.', 'validation')
                    return run
                if not fields and not settled.get("summary"):
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
                    self.checkpoint(run)
                    if run.auto_submit and not self._pause and not self._cancel:
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

    async def account_step(self, run, profile, fields, bridge, credential):
        """One guarded Workday create-account or sign-in step. True continues the section loop; False hands off or pauses."""
        state = credential.get('state', 'verified')
        auth = await bridge.command('auth_page')
        if state == 'pending_verification':
            if auth['page'] == 'create' and run.authentication_attempted and (await bridge.command('snapshot'))['errors']:
                self.intervene(run, REJECTED_ACCOUNT, 'verification')
            else:
                self.intervene(run, ACTIVATION_HANDOFF.format(credential['username']), 'activation')
            return False
        create = state == 'new'
        if run.authentication_attempted:
            self.intervene(run, SIGN_IN_HANDOFF, 'verification')
            return False
        expected = 'create' if create else 'sign_in'
        if auth['page'] != expected:
            if (await bridge.command('open_create_account' if create else 'open_sign_in')).get('opened'):
                await asyncio.sleep(.3)
                return True
            self.intervene(run, "Open Workday's Create Account page in Chromium, then resume." if create else SIGN_IN_HANDOFF, 'verification')
            return False
        # The runtime refuses unapproved extra questions (such as a terms checkbox); ask before consuming the single attempt.
        credentials, answers = set(auth['credentials']), self.store.answers()
        for field in fields:
            resolution = resolve(field, profile, run, answers)
            if field.selector not in credentials and resolution.value is None and not resolution.omit:
                self.intervene(run, resolution.reason, 'answer', field)
                return False
        if create:
            # Persist before the click: a crash afterwards must never create a second account.
            self.store._vault().set_account_state(run.job_url, 'pending_verification')
            credential['state'] = 'pending_verification'
        run.authentication_attempted = True
        self.checkpoint(run)
        if self._pause or self._cancel:
            return False
        await bridge.command('authenticate', {'credential': {'username': credential['username'], 'password': credential['password']}})
        await asyncio.sleep(.5)
        return True

    async def authorize(self, run, profile, fields):
        answers = self.store.answers()
        policies = {}
        for field in fields:
            resolution = resolve(field, profile, run, answers)
            policies[field.selector] = dict(key=field.key, label=field.label, value=resolution.value, omit=resolution.omit, ref=resolution.ref,
                                           replace=resolution.ref.startswith('answer:'))
        await self.bridge.command('authorize', {'policies': policies})

    async def wait_for_section(self, run, profile):
        for _ in range(210):
            if self._pause or self._cancel:
                return None
            snapshot = await self.bridge.command('snapshot')
            if snapshot['proposals']:
                fields = [FormField(**f) for f in (await self.bridge.command('scan'))['fields']]
                await self.authorize(run, profile, fields)
            if snapshot['settled'] and not self.bridge.pending and (snapshot['status'] in {'autofill-complete','page-complete','complete-required','complete-manually','action-pending'} or not snapshot['live']):
                return snapshot
            await asyncio.sleep(.1)
        self.intervene(run, 'The adapter did not finish within its bounded wait. Inspect the form and resume.')
        return None

    def verify(self, run, profile, fields, config):
        answers = self.store.answers()
        ok = True
        # Replace this section's evidence as a unit; removed conditional controls are no longer applicable.
        run.fields = {k: v for k, v in run.fields.items() if v.section != run.stage}
        for field in fields:
            resolution = resolve(field, profile, run, answers)
            reason = ''
            omitted = resolution.omit and not field.required and field.value in ('', False)
            if omitted:
                matched = True
            elif resolution.value is None:
                matched = False
                reason = resolution.reason
            elif field.kind == 'file':
                descriptor = config['files'].get(str(resolution.value), {})
                matched = bool(descriptor) and field.file_digest == descriptor['digest'] and not field.invalid
                reason = 'The exact uploaded file and its accepted state could not be verified.'
            elif field.kind == 'radio':
                offered = any(f.kind == 'radio' and f.label == field.label and f.group == field.group and f.row == field.row and normalized(f.option) == normalized(str(resolution.value)) for f in fields)
                matched = offered and field.value == (normalized(field.option) == normalized(str(resolution.value))) and not field.invalid
            else:
                matched = (field.value == resolution.value if isinstance(resolution.value, bool) else normalized(str(field.value)) == normalized(str(resolution.value))) and not field.invalid
            if not matched:
                ok = False
                reason = reason or ('Existing browser value conflicts with the profile. Resolve it before resuming.' if field.value not in ('', False) else 'The adapter did not fill this field with the approved value. Complete it manually or correct the profile.')
            key = run.stage + ':' + field.key
            run.fields[key] = FieldAssessment(key=key, label=field.label, section=run.stage, required=field.required, group=field.group, row=field.row, kind=field.kind,
                answer_ref=resolution.ref, disposition='intentionally_omitted' if omitted else 'verified' if matched else 'needs_input',
                evidence='Exact file digest and DOM validity' if matched and field.kind == 'file' else 'Section DOM read-back' if matched else '',reason='' if matched else reason)
            if not matched:
                self.intervene(run, reason, 'conflict' if 'conflict' in reason else 'answer', field)
        return ok

    def verify_review(self, run, profile, summary):
        previous = [a for a in run.fields.values() if a.section != run.stage and a.disposition == "verified"]
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
        for _ in range(20):
            from urllib.parse import urlsplit
            expected = urlsplit(self.bridge.binding['url'] if self.bridge.binding else run.job_url)
            frames = [frame for frame in self.bridge.page.frames if urlsplit(frame.url).scheme == 'https' and urlsplit(frame.url).hostname == expected.hostname]
            received = False
            if len(frames) == 1:
                receipts = frames[0].locator('[data-automation-id="applicationSubmitted"],#application_confirmation,.application-confirmation,.ashby-application-form-success-message,.thanks,h1,h2,[role=status]')
                for receipt in await receipts.all():
                    if await receipt.is_visible() and normalized(await receipt.inner_text()) in {'application submitted','your application has been submitted','thank you for applying','your application has been received'}:
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
