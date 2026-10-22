"""RequestEngine against a fake Workday tenant that answers the candidate API the way Workday's apply flow expects."""
import json
from types import SimpleNamespace

import pytest
from urllib.parse import parse_qs, urlsplit

from core.automation.models import ApplicationRun, ApprovedAnswer
from core.automation.request_engine import NEW_ACCOUNT, SINGLE, TEXT, RequestEngine, apply_url
from tests.support import profile_for

URL = 'https://example.wd1.myworkdayjobs.com/en-US/Careers/job/Singapore/Intern_R123'
API = '/wday/calypso/cxs/'
AUTHORIZED = {'id': 'q-auth', 'body': '<p>Are you legally authorized to work in <b>Singapore</b>?</p>', 'order': 'a', 'type': {'id': SINGLE},
              'possibleAnswers': [{'id': 'yes', 'answerText': 'Yes', 'order': 'a', 'branchingQuestion': True}, {'id': 'no', 'answerText': 'No', 'order': 'b'}]}
PASS = {'id': 'q-pass', 'body': '<p>Which pass do you hold?</p>', 'order': 'b', 'type': {'id': TEXT}}
SIGN_IN = '''<button onclick="this.remove();document.getElementById('form').hidden=false">Sign in with email</button>
<div id=form hidden><input data-automation-id=email><input type=password data-automation-id=password>
<button aria-hidden=true data-automation-id=signInSubmitButton>Sign In</button>
<div role=button aria-label="Sign In" data-automation-id=click_filter onclick="document.cookie='signed='+encodeURIComponent(document.querySelector('[data-automation-id=email]').value)+';path=/'">&nbsp;</div></div>'''
# Keppel opens on Create Account; its Sign In link swaps in the sign-in form.
CREATE_FIRST = '''<div id=create><input data-automation-id=email><input type=password><input type=password data-automation-id=verifyPassword>
<button data-automation-id=createAccountSubmitButton>Create Account</button>
<button data-automation-id=signInLink onclick="document.getElementById('create').remove();document.getElementById('form').hidden=false">Sign In</button></div>''' + SIGN_IN.split('</button>', 1)[1]


class Tenant:
    """Workday's candidate API for one posting with a primary questionnaire; `PASS` shows only after answering Yes."""
    def __init__(self, signed_in=True, sign_in=SIGN_IN):
        self.signed_in, self.sign_in, self.saved, self.posts, self.headers = signed_in, sign_in, [], [], []
        self.application_html = ''

    async def handle(self, route):
        request = route.request
        path, query = urlsplit(request.url).path, parse_qs(urlsplit(request.url).query)
        signed_in = self.signed_in or 'signed=ada%40example.test' in request.headers.get('cookie', '')
        if not path.startswith(API):
            page = '<script>window.workday={token:"tok",tenant:"example",siteId:"Careers"}</script>' + (self.application_html if signed_in else self.sign_in)
            return await route.fulfill(body=page, content_type='text/html')
        self.headers.append(request.headers)
        api = path[len(API):]
        body = request.post_data_json if request.method == 'POST' else None
        if api == 'candidatehome/example/Careers/userprofile':
            data = {'email': 'ada@example.test'} if signed_in else {}
        elif api == 'candidatehome/example/Careers/applications':
            assert query['jobPostingAnchorId'] == ['Job_Posting_Anchor_ID=Intern_R123']
            data = {'total': 1, 'data': [{'applicationId': 'app1', 'posting': {'isPosted': True}}]}
        elif api == 'jobapplication/example/jobpostings/Intern_R123/applyflowpages':
            data = {'data': [{'id': 'login', 'descriptor': 'Create Account/Sign In'}, {'id': '5eff652ad12a10000ef9477b27420000', 'descriptor': 'My Information'},
                             {'id': '5eff652ad12a10000f1c2d323fb00000', 'descriptor': 'Application Questions'}]}
        elif api == 'jobdetails/example/job/Intern_R123/info':
            data = {'questionnaireId': 'qn1'}
        elif api == 'common/example/questionnaire/qn1':
            data = {'id': 'qn1', 'questions': [AUTHORIZED, PASS]}
        elif api == 'common/example/questionnaire/qn1/definition':
            shown = [AUTHORIZED] + ([PASS] if body.get('q-auth') == {'id': 'yes'} else [])
            data = {'definitions': {'primaryQuestionnaire': {'required': [q['id'] for q in shown],
                                                             'properties': {q['id']: {'label': q['body'], 'order': q['order'], 'type': 'object'} for q in shown}}}}
        elif api == 'jobapplication/example/jobapplication/app1/questionnaireanswers':
            data = self.saved
        elif api == 'jobapplication/example/jobapplication/app1/questionnaireresponse':
            self.posts.append(body)
            self.saved = [{'questionItem': a['questionItem'], **({'questionMultipleChoiceAnswer': c} if 'questionMultipleChoiceAnswers' in a else {'answerText': a['answerText']})}
                          for a in body['questionnaireAnswers'] for c in a.get('questionMultipleChoiceAnswers', [None])]
            data = {'questionnaireAnswers': self.saved}
        else:
            return await route.fulfill(status=404, body='{}', content_type='application/json')
        await route.fulfill(body=json.dumps(data), content_type='application/json')


async def run_request(context, store, tenant, run=None, credential=None):
    await context.clear_cookies()  # A sign-in cookie from an earlier test must not sign this one in.
    page = await context.new_page()
    await page.route('**/*', tenant.handle)
    run = run or ApplicationRun(job_url=URL, mode='request')
    await RequestEngine(store).answer_questions(run, profile_for('workday'), SimpleNamespace(page=page, binding=None), credential)
    return run, page


def answer(store, question, value):
    store.save_answer(ApprovedAnswer(question=question, value=value, scope='global'))


def test_apply_url_opens_apply_manually_from_the_posting_or_any_apply_route():
    assert apply_url(URL) == URL + '/apply/applyManually'
    assert apply_url(URL + '/apply/autofillWithResume?source=x') == URL + '/apply/applyManually'


async def test_questions_are_answered_in_one_post_and_verified_by_read_back(context, store):
    answer(store, 'Are you legally authorized to work in Singapore?', True)
    answer(store, 'Which pass do you hold?', 'Student Pass')
    tenant = Tenant()
    run, _ = await run_request(context, store, tenant)
    assert [i.message for i in run.interventions] == []
    assert tenant.posts == [{'questionnaireAnswers': [{'questionItem': {'id': 'q-auth'}, 'questionMultipleChoiceAnswers': [{'id': 'yes'}]},
                                                      {'questionItem': {'id': 'q-pass'}, 'answerText': 'Student Pass'}]}]
    assert {f.label: f.disposition for f in run.fields.values()} == {'Are you legally authorized to work in Singapore?': 'verified', 'Which pass do you hold?': 'verified'}
    assert run.steps[2] == 'Application Questions' and run.step == 2
    assert all(h['x-calypso-csrf-token'] == 'tok' for h in tenant.headers)
    # Resuming re-verifies without writing again.
    await run_request(context, store, tenant, run)
    assert len(tenant.posts) == 1 and not run.interventions


async def test_an_unanswered_question_offers_workdays_own_options_and_writes_nothing(context, store):
    tenant = Tenant()
    run, _ = await run_request(context, store, tenant)
    assert not tenant.posts and run.status == 'needs_input'
    [request] = run.interventions
    assert request.options == ['Yes', 'No'] and request.field_kind == 'combobox' and request.required


async def test_a_branching_answer_reveals_its_follow_up_question(context, store):
    answer(store, 'Are you legally authorized to work in Singapore?', True)
    tenant = Tenant()
    run, _ = await run_request(context, store, tenant)
    assert not tenant.posts
    assert [i.question for i in run.interventions] == ['Which pass do you hold?']


@pytest.mark.parametrize('form', [SIGN_IN, CREATE_FIRST], ids=['sign-in-with-email', 'create-account-first'])
async def test_a_saved_login_signs_in_through_the_page_once(context, store, form):
    answer(store, 'Are you legally authorized to work in Singapore?', False)
    tenant = Tenant(signed_in=False, sign_in=form)
    credential = {'username': 'ada@example.test', 'password': 'secret', 'state': 'verified'}
    run, _ = await run_request(context, store, tenant, credential=credential)
    assert [i.message for i in run.interventions] == [] and not run.authentication_attempted


async def test_request_mode_never_creates_accounts(context, store):
    tenant = Tenant(signed_in=False)
    run, _ = await run_request(context, store, tenant, credential={'username': 'a@example.test', 'password': 'x', 'state': 'new'})
    assert [i.message for i in run.interventions] == [NEW_ACCOUNT] and not run.authentication_attempted


class QuestionnairePage:
    """Candidate API transport: exercises RequestEngine.call as well as questionnaire logic."""
    def __init__(self):
        self.questions = [PASS]
        self.required = ['q-pass']
        self.saved = []
        self.posts = []
        self.on_definition = lambda: None
        self.keep_old_answers = False

    async def evaluate(self, script, request):
        path = request['path']
        if '/definition?' in path:
            self.on_definition()
            data = {'definitions': {'primaryQuestionnaire': {'required': self.required,
                    'properties': {q['id']: {} for q in self.questions}}}}
        elif '/questionnaireresponse?' in path:
            self.posts.append(request['body'])
            if not self.keep_old_answers:
                self.saved = request['body']['questionnaireAnswers']
            data = {'questionnaireAnswers': self.saved}
        elif '/questionnaireanswers?' in path:
            data = self.saved
        else:
            data = {'questions': self.questions}
        return {'status': 200, 'json': data}


def questionnaire_engine(store):
    engine = RequestEngine(store)
    engine.page = QuestionnairePage()
    engine.tenant, engine.site, engine.application = 'example', 'Careers', 'app1'
    run = ApplicationRun(job_url=URL, mode='request', status='running', stage='Workday API: primary questions')
    engine.run_id = run.id
    return engine, run


@pytest.mark.parametrize('stop', ['pause', 'cancel'])
async def test_stop_during_definition_prevents_questionnaire_save(store, stop):
    import asyncio
    engine, run = questionnaire_engine(store)
    answer(store, 'Which pass do you hold?', 'Student Pass')
    engine.page.on_definition = getattr(engine, stop)
    try:
        await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
    except asyncio.CancelledError:
        pass
    assert engine.stopped
    assert engine.page.posts == []


@pytest.mark.parametrize('keep_old', [False, True])
async def test_omission_is_saved_and_independently_verified(store, keep_old):
    engine, run = questionnaire_engine(store)
    engine.page.required = []
    engine.page.saved = [{'questionItem': {'id': 'q-pass'}, 'answerText': 'Old answer'}]
    engine.page.keep_old_answers = keep_old
    store.save_answer(ApprovedAnswer(question='Which pass do you hold?', scope='global', omit=True))
    ok = await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
    assert engine.page.posts == [{'questionnaireAnswers': []}]
    assert ok is not keep_old
    [field] = run.fields.values()
    assert field.disposition == ('needs_input' if keep_old else 'intentionally_omitted')
    if not keep_old:
        await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
        assert len(engine.page.posts) == 1


async def test_missing_answer_replaces_previous_verification(store):
    engine, run = questionnaire_engine(store)
    answer(store, 'Which pass do you hold?', 'Student Pass')
    assert await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
    run.completed_sections.append(run.stage)
    store.delete_answer(store.answers()[0].id)
    assert not await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
    assert run.stage not in run.completed_sections
    [field] = run.fields.values()
    assert field.disposition == 'needs_input'
    assert not field.evidence
    assert len(engine.page.posts) == 1


async def test_omitting_text_preserves_an_existing_required_upload(store):
    from core.automation.request_engine import UPLOAD
    engine, run = questionnaire_engine(store)
    engine.page.questions = [PASS, {'id': 'upload', 'body': 'Supporting document', 'type': {'id': UPLOAD}}]
    engine.page.required = ['upload']
    attachment = {'questionItem': {'id': 'upload'}, 'questionnaireAttachments': [{'id': 'file1'}]}
    engine.page.saved = [{'questionItem': {'id': 'q-pass'}, 'answerText': 'Old answer'}, attachment]
    store.save_answer(ApprovedAnswer(question='Which pass do you hold?', scope='global', omit=True))
    assert await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
    assert engine.page.posts == [{'questionnaireAnswers': [attachment]}]
    assert engine.page.saved == [attachment]


async def test_required_omission_never_clears_a_saved_answer(store):
    engine, run = questionnaire_engine(store)
    engine.page.saved = [{'questionItem': {'id': 'q-pass'}, 'answerText': 'Old answer'}]
    store.save_answer(ApprovedAnswer(question='Which pass do you hold?', scope='global', omit=True))
    assert not await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
    assert not engine.page.posts
    assert run.interventions[0].required


@pytest.mark.parametrize('stop', ['pause', 'cancel'])
async def test_stop_before_sign_in_click_does_not_consume_login_attempt(context, store, stop):
    tenant = Tenant(signed_in=False)
    await context.clear_cookies()
    page = await context.new_page()
    await page.route('**/*', tenant.handle)
    engine = RequestEngine(store)
    # Cancel during the deliberate pre-click delay, after the credentials have been filled.
    original_wait = page.wait_for_timeout
    async def wait_then_stop(ms):
        await original_wait(ms)
        getattr(engine, stop)()
    page.wait_for_timeout = wait_then_stop
    from unittest.mock import AsyncMock
    run = ApplicationRun(job_url=URL, mode='request')
    await engine.start(run, profile_for('workday'), SimpleNamespace(page=page, binding=None, stop=AsyncMock()),
                       {'username': 'ada@example.test', 'password': 'secret', 'state': 'verified'})
    assert not run.authentication_attempted
    assert run.status == ('cancelled' if stop == 'cancel' else 'needs_input')
    assert not any(c['name'] == 'signed' for c in await context.cookies())
    assert not tenant.posts


@pytest.mark.parametrize('auto_submit', [False, True])
@pytest.mark.parametrize('modern_review', [False, True])
async def test_request_mode_continues_from_api_to_browser_review_and_authorized_receipt(context, store, auto_submit, modern_review):
    from core.automation.extension_bridge import ExtensionBridge
    await context.clear_cookies()
    tenant = Tenant(signed_in=False)
    tenant.application_html = '''<div id="application"><h2>My Information</h2><div data-automation-id="contactInformationPage">
    <label>First Name<input data-automation-id="legalNameSection_firstName"></label>
    <label>Last Name<input data-automation-id="legalNameSection_lastName"></label>
    <label>Email<input data-automation-id="email"></label></div>
    <button type="button" data-automation-id="bottom-navigation-next-button" onclick="review()">Next</button></div>
    <script>function review(){
      const labels=['First Name','Last Name','Email'];
      const summary=[...document.querySelectorAll('input')].map((e,i)=>'<dt>'+labels[i]+'</dt><dd>'+e.value+'</dd>').join('');
      document.getElementById('application').innerHTML='<h2>Review</h2><div data-automation-id="reviewJobApplicationPage"><dl>'+summary+'</dl></div><button type="button" data-automation-id="bottom-navigation-next-button">Submit</button>';
      document.querySelector('button').onclick=()=>{window.submissions=(window.submissions||0)+1;document.getElementById('application').innerHTML='<h1>Application submitted</h1>';};
    }</script>'''
    if modern_review:
        tenant.application_html = tenant.application_html.replace('reviewJobApplicationPage', 'applyFlowReviewPage').replace(
            "'<dt>'+labels[i]+'</dt><dd>'+e.value+'</dd>'",
            "'<div><label for=review'+i+'>'+labels[i]+'</label><div><span id=review'+i+'>'+e.value+'</span></div></div>'")
    answer(store, 'Are you legally authorized to work in Singapore?', False)
    page = await context.new_page()
    await page.route('**/*', tenant.handle)
    run = ApplicationRun(job_url=URL, mode='request', auto_submit=auto_submit)
    engine = RequestEngine(store)
    await engine.start(run, profile_for('workday'), ExtensionBridge(page, run.id),
                       {'username': 'ada@example.test', 'password': 'secret', 'state': 'verified'})
    assert len(tenant.posts) == 1
    assert run.status == 'ready_for_review', run.interventions
    assert run.submission_attempted == auto_submit and run.submission_confirmed == auto_submit
    assert await page.evaluate('window.submissions || 0') == int(auto_submit)
    if auto_submit:
        await engine.resume(run, profile_for('workday'), engine.bridge)
        assert await page.evaluate('window.submissions') == 1
        assert len(tenant.posts) == 1


@pytest.mark.parametrize('response', [None, {}])
async def test_unrecognized_saved_answers_cannot_be_treated_as_blank(store, response):
    engine, run = questionnaire_engine(store)
    engine.page.required = []
    engine.page.saved = response
    store.save_answer(ApprovedAnswer(question='Which pass do you hold?', scope='global', omit=True))
    with pytest.raises(ValueError):
        await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
    assert not engine.page.posts and not run.fields


async def test_empty_validation_list_still_requires_successful_readback(store):
    engine, run = questionnaire_engine(store)
    answer(store, 'Which pass do you hold?', 'Student Pass')
    engine.page.keep_old_answers = True
    evaluate = engine.page.evaluate
    async def empty_validation(script, request):
        response = await evaluate(script, request)
        if '/questionnaireresponse?' in request['path']:
            response['json'] = []
        return response
    engine.page.evaluate = empty_validation
    assert not await engine.questionnaire(run, profile_for('workday'), 'qn1', 'primary')
    assert run.status == 'needs_input' and run.interventions
    assert all(f.disposition == 'needs_input' for f in run.fields.values())
