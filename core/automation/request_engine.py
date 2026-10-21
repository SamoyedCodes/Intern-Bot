"""Request mode: sign in through the browser, then answer Workday's application questions through its own candidate API."""
import asyncio
import html
import re
import time
from urllib.parse import quote, urlsplit

from core.automation.answers import resolve
from core.automation.engine import ACTIVATION_HANDOFF, SIGN_IN_HANDOFF, ApplicationEngine
from core.automation.fields import FormField
from core.automation.models import FieldAssessment, InterventionRequest, normalized

ENGINE_VERSION = 'workday-request-v1'
NEW_ACCOUNT = "Request mode signs in with an existing Workday login. Sign in or create this employer's account in Chromium, then resume."
NO_DRAFT = 'No Workday draft was found for this job. In Chromium, choose Apply, then Apply Manually, and resume once the first page shows.'
HANDOFF = 'Application questions are saved in Workday and verified. Finish the other pages in Chromium (they show the saved answers) and submit there yourself.'
NO_QUESTIONS = 'This posting has no application questions for request mode to answer. Finish the application in Chromium.'

# Workday's question types, from its apply-flow code (common/questionnaire/{id}).
DATE, MULTI, NUMBER, SINGLE, TEXT, UPLOAD = ('85fb160ed47910001589e3a427670070', 'c4d9bd57996c100025ab7d705b150045', '53d73448d8de1000063827b5cb68003f',
                                             'c4d9bd57996c10002583f04b9fc30042', 'c4d9bd57996c100025ab7d7f5aed0046', '287357c143e210001cddbc6df0719cba')
KINDS = {DATE: 'date', MULTI: 'select-multiple', NUMBER: 'text', SINGLE: 'combobox', TEXT: 'text', UPLOAD: 'file'}
ANSWER_KEYS = {TEXT: 'answerText', NUMBER: 'answerNumeric', DATE: 'answerDate'}
# (job info key, questionnaire type, apply page id) for each questionnaire a posting can carry.
QUESTIONNAIRES = (('questionnaireId', 'primary', '5eff652ad12a10000f1c2d323fb00000'),
                  ('secondaryQuestionnaireId', 'secondary', '5eff652ad12a10000f2b959dfeb90000'),
                  ('supplementaryQuestionnaireId', 'supplementary', '5eff652ad12a10000f34b78ac38f0000'))

# Runs inside the signed-in page, so the call carries the browser's own cookies, CSRF token and Cloudflare clearance.
FETCH = """async ({method, path, body, session}) => {
  const headers = {accept: 'application/json', 'content-type': 'application/json', 'X-CALYPSO-CSRF-TOKEN': window.workday?.token || ''};
  if (session !== null) headers['X-Cxs-Session-Id'] = session;
  const response = await fetch(path, {method, headers, credentials: 'same-origin', body: body === null ? undefined : JSON.stringify(body)});
  let json = null;
  try { json = await response.json(); } catch (error) {}
  return {status: response.status, json};
}"""


def apply_url(job_url):
    """The posting's Apply Manually route, which skips Workday's resume parser."""
    parts = urlsplit(job_url)
    return parts._replace(path=parts.path.split('/apply')[0].rstrip('/') + '/apply/applyManually', query='', fragment='').geturl()


def plain(text):
    """Question bodies are HTML; the browser shows (and the answer bank stores) their text."""
    blocks = re.sub(r'<(?:br|/?p|/?div|/?li)\b[^>]*>', ' ', text or '')
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', blocks))).strip()


class RequestEngine(ApplicationEngine):
    DRAFT_POLLS = 40

    async def start(self, run, profile, bridge, credential=None):
        self.bridge, self.page, self.run_id, self.job_url = bridge, bridge.page, run.id, run.job_url
        self._pause = self._cancel = False
        if run.is_submitted:
            return run
        started = time.monotonic()
        run.interventions = []
        run.status = 'running'
        try:
            if run.engine_version != ENGINE_VERSION or run.profile_revision != profile.revision:
                run.fields, run.completed_sections = {}, []
            run.engine_version, run.profile_snapshot, run.profile_revision = ENGINE_VERSION, profile.model_copy(deep=True), profile.revision
            self.checkpoint(run)
            self.job = [p for p in urlsplit(apply_url(run.job_url)).path.split('/') if p][-3]
            await self.open()
            self.tenant, self.site = await self.page.evaluate('() => [workday.tenant, workday.siteId]')
            if not await self.sign_in(run, credential) or self.stopped:
                return run
            # The page itself creates the draft once a signed-in candidate opens Apply Manually.
            await self.open()
            draft = None
            for _ in range(self.DRAFT_POLLS):
                drafts = await self.call('GET', self.calypso('candidatehome', f'applications?type=active&jobPostingAnchorId=Job_Posting_Anchor_ID={quote(self.job)}&draftsOnly=true', site=True))
                draft = next((d for d in (drafts or {}).get('data', []) if d.get('applicationId')), None)
                if draft or self.stopped:
                    break
                await asyncio.sleep(.25)
            if not draft:
                if not self.stopped:
                    self.intervene(run, NO_DRAFT)
                return run
            self.application = draft['applicationId']
            pages = (await self.call('GET', self.calypso('jobapplication', f'jobpostings/{quote(self.job)}/applyflowpages?applyDetail=applyManually')) or {}).get('data', [])
            run.steps = [p.get('descriptor', '') for p in pages]
            info = await self.call('GET', self.calypso('jobdetails', f'job/{quote(self.job)}/info')) or {}
            found = [(info[key], kind, page) for key, kind, page in QUESTIONNAIRES if info.get(key)]
            for questionnaire, kind, page in found:
                run.step = next((i for i, p in enumerate(pages) if p.get('id') == page), run.step)
                run.stage = f'Workday API: {kind} questions'
                self.checkpoint(run)
                if not await self.questionnaire(run, profile, questionnaire, kind) or self.stopped:
                    return run
                if run.stage not in run.completed_sections:
                    run.completed_sections.append(run.stage)
            # Show the saved answers rather than the page as it was before the API calls.
            await self.open()
            self.intervene(run, HANDOFF if found else NO_QUESTIONS)
        except asyncio.CancelledError:
            run.status = 'cancelled' if self._cancel else 'needs_input'
            raise
        except Exception as exc:
            self.intervene(run, f'Workday did not answer as request mode expects. Inspect the draft in Chromium and resume ({type(exc).__name__}).')
        finally:
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

    @property
    def stopped(self):
        return self._pause or self._cancel

    async def open(self):
        await self.page.goto(apply_url(self.job_url), wait_until='domcontentloaded')
        await self.page.wait_for_function('() => window.workday?.token && window.workday?.tenant', timeout=30000)

    def calypso(self, service, path, site=False):
        return f'/wday/calypso/cxs/{service}/{self.tenant}' + (f'/{self.site}' if site else '') + '/' + path

    async def call(self, method, path, body=None, session=None):
        """One API call; returns its JSON, or raises so nothing is written on a misunderstood response."""
        response = await self.page.evaluate(FETCH, {'method': method, 'path': path, 'body': body, 'session': session})
        if response['status'] >= 400:
            self.store.record_event(self.run_id, 'http_error', '', f"{response['status']} {method} {urlsplit(path).path}")
            raise RuntimeError(f"HTTP {response['status']}")
        return response['json']

    async def signed_in(self):
        try:
            return bool(await self.call('GET', self.calypso('candidatehome', 'userprofile', site=True)))
        except Exception:
            return False  # A page still loading after the sign-in click.

    async def sign_in(self, run, credential):
        if await self.signed_in():
            run.authentication_attempted = False
            return True
        state = (credential or {}).get('state', 'verified')
        if state == 'pending_verification':
            self.intervene(run, ACTIVATION_HANDOFF.format(credential['username']), 'activation')
            return False
        if not credential or state == 'new':
            self.intervene(run, NEW_ACCOUNT, 'verification')
            return False
        if run.authentication_attempted:
            self.intervene(run, SIGN_IN_HANDOFF, 'verification')
            return False
        page = self.page
        email_button = page.get_by_role('button', name=re.compile(r'^sign in with email$', re.I))
        sign_in_link = page.locator('[data-automation-id="signInLink"]:visible')
        email, password = page.locator('input[data-automation-id="email"]:visible'), page.locator('input[type=password]:visible')
        try:
            await email_button.or_(sign_in_link).or_(email).first.wait_for(timeout=15000)
            if await email_button.count() == 1:
                await email_button.click()
            elif await sign_in_link.count() == 1 and await page.locator('[data-automation-id="createAccountSubmitButton"]').count():
                # Tenants such as Keppel open on Create Account; its Sign In link swaps in the sign-in form.
                await sign_in_link.click()
                await page.locator('[data-automation-id="createAccountSubmitButton"]').wait_for(state='detached', timeout=10000)
            await email.first.wait_for(timeout=10000)
        except Exception:
            self.intervene(run, SIGN_IN_HANDOFF, 'verification')
            return False
        if await email.count() != 1 or await password.count() != 1:
            self.intervene(run, SIGN_IN_HANDOFF, 'verification')
            return False
        # One attempt per run, persisted before the click, as in classic mode.
        run.authentication_attempted = True
        self.checkpoint(run)
        await email.fill(credential['username'])
        await password.fill(credential['password'])
        # Workday drops a sign-in sent within 500ms of the form appearing, and only accepts a real click on the
        # transparent overlay it lays over the submit button.
        await page.wait_for_timeout(1000)
        overlay = page.locator('[data-automation-id="click_filter"]:visible')
        await (overlay if await overlay.count() == 1 else page.locator('[data-automation-id="signInSubmitButton"]')).click()
        for _ in range(self.AUTH_POLLS):
            await asyncio.sleep(.25)
            if self.stopped:
                return False
            if await self.signed_in():
                run.authentication_attempted = False
                self.checkpoint(run)
                return True
        self.intervene(run, SIGN_IN_HANDOFF, 'verification')
        return False

    async def questionnaire(self, run, profile, questionnaire_id, kind):
        """Answer one questionnaire in a single POST, then verify Workday's saved answers. False hands off."""
        questions = {q['id']: q for q in (await self.call('GET', self.calypso('common', f'questionnaire/{questionnaire_id}')))['questions']}
        branching = {q['id'] for q in questions.values() if any(a.get('branchingQuestion') for a in q.get('possibleAnswers') or [])}
        branches = lambda values: {k: v[0] for k, v in values.items() if k in branching}
        answers, chosen, saved = self.store.answers(), {}, await self.saved(kind)
        # Which questions show depends on the answers to branching ones; settle that before asking anything.
        for _ in range(len(branching) + 1):
            asked = branches(chosen)
            definition = (await self.call('POST', self.calypso('common', f'questionnaire/{questionnaire_id}/definition?type={kind}'), asked))['definitions'][f'{kind}Questionnaire']
            required = set(definition.get('required', []))
            shown = [self.field(questions[k], k in required) for k, p in sorted(definition['properties'].items(), key=lambda item: item[1].get('order', ''))
                     if k in questions and not p.get('hidden')]
            missing, chosen = [], {}
            for field in shown:
                if field.kind == 'file':
                    # Uploads stay with the browser; one you already made is kept below.
                    if not isinstance(saved.get(field.selector), dict) and field.required:
                        missing.append((field, f'Upload your answer to “{field.label}” in Chromium; request mode does not upload files.'))
                    continue
                resolution = resolve(field, profile, run, answers)
                if resolution.omit and not field.required:
                    continue
                value = None if resolution.value is None else self.answer(questions[field.selector], resolution.value)
                if value is not None:
                    chosen[field.selector] = value
                elif resolution.value is None:
                    missing.append((field, resolution.reason))
                else:
                    missing.append((field, 'Workday has no option matching the approved answer. Choose one of its options.' if field.options
                                    else 'Request mode cannot send this kind of answer. Answer it in Chromium.'))
            if branches(chosen) == asked:
                break
        if missing:
            for field, reason in missing:
                self.intervene(run, reason, *(('browser',) if field.kind == 'file' else ('answer', field)))
            return False
        if any(saved.get(k) != self.comparable(v) for k, v in chosen.items()):
            # The POST replaces the whole questionnaire, so uploads already made are sent back as they are.
            kept = [{'questionItem': {'id': f.selector}, **saved[f.selector]} for f in shown if f.kind == 'file' and isinstance(saved.get(f.selector), dict)]
            body = {'questionnaireAnswers': [{'questionItem': {'id': k}, **self.payload(questions[k], v)} for k, v in chosen.items()] + kept}
            response = await self.call('POST', self.calypso('jobapplication', f'jobapplication/{self.application}/questionnaireresponse?type={kind}'), body, session='')
            if isinstance(response, list):
                # Workday returns its validation errors as a list.
                for error in response:
                    self.intervene(run, str(error.get('message') or error) if isinstance(error, dict) else str(error), 'validation')
                return False
            saved = await self.saved(kind)
        ok = True
        run.fields = {k: v for k, v in run.fields.items() if v.section != run.stage}
        for field in shown:
            if field.selector not in chosen:
                continue
            matched = saved.get(field.selector) == self.comparable(chosen[field.selector])
            ok = ok and matched
            key = run.stage + ':' + field.key
            run.fields[key] = FieldAssessment(key=key, label=field.label, section=run.stage, required=field.required, kind=field.kind,
                                              answer_ref=resolve(field, profile, run, answers).ref, disposition='verified' if matched else 'needs_input',
                                              evidence='Workday API read-back' if matched else '', reason='' if matched else 'Workday did not keep the answer that was sent.')
        if not ok:
            self.intervene(run, 'Workday saved different answers than request mode sent. Inspect Application Questions in Chromium.', 'validation')
        return ok

    @staticmethod
    def field(question, required):
        options = [a['answerText'] for a in sorted(question.get('possibleAnswers') or [], key=lambda a: a.get('order', ''))]
        return FormField(key='question:' + question['id'], label=plain(question.get('body')), selector=question['id'],
                         kind=KINDS.get(question['type']['id'], 'text'), options=options, required=required)

    @staticmethod
    def answer(question, value):
        """The approved value in Workday's terms: chosen answer ids, text, a positive number or an ISO date. None when it cannot be sent."""
        kind, text = question['type']['id'], str(value).strip()
        if kind in (SINGLE, MULTI):
            # ponytail: a multi-select answer lists its options separated by semicolons.
            wanted = [text] if kind == SINGLE else [v for v in re.split(r'\s*;\s*', text) if v]
            ids = [[a['id'] for a in question.get('possibleAnswers') or [] if normalized(a['answerText']) == normalized(w)] for w in wanted]
            return [{'id': i[0]} for i in ids] if ids and all(len(i) == 1 for i in ids) else None
        if kind == TEXT:
            return text
        if kind == NUMBER and re.fullmatch(r'[1-9]\d*', text):
            return int(text)  # Workday's own form drops zero and negative numbers.
        if kind == DATE and re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            return text
        return None

    @staticmethod
    def payload(question, value):
        kind = question['type']['id']
        return {'questionMultipleChoiceAnswers': value} if kind in (SINGLE, MULTI) else {ANSWER_KEYS[kind]: value}

    @staticmethod
    def comparable(value):
        return sorted(v['id'] for v in value) if isinstance(value, list) else value

    async def saved(self, kind):
        """What Workday holds now, per question: chosen answer ids (sorted), the text, number or date, or the uploaded attachments."""
        saved = {}
        for answer in await self.call('GET', self.calypso('jobapplication', f'jobapplication/{self.application}/questionnaireanswers?type={kind}'), session='') or []:
            question = answer['questionItem']['id']
            if answer.get('questionnaireAttachments'):
                saved[question] = {'questionnaireAttachments': [{'id': a['id']} for a in answer['questionnaireAttachments']]}
            elif answer.get('questionMultipleChoiceAnswer'):
                saved[question] = sorted(saved.get(question, []) + [answer['questionMultipleChoiceAnswer']['id']])
            else:
                saved[question] = next((answer[k] for k in ANSWER_KEYS.values() if answer.get(k) not in (None, '')), None)
        return saved
