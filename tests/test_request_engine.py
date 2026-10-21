"""RequestEngine against a fake Workday tenant that answers the candidate API the way Workday's apply flow expects."""
import json
from types import SimpleNamespace

import pytest
from urllib.parse import parse_qs, urlsplit

from core.automation.models import ApplicationRun, ApprovedAnswer
from core.automation.request_engine import HANDOFF, NEW_ACCOUNT, SINGLE, TEXT, RequestEngine, apply_url
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

    async def handle(self, route):
        request = route.request
        path, query = urlsplit(request.url).path, parse_qs(urlsplit(request.url).query)
        if not path.startswith(API):
            page = '<script>window.workday={token:"tok",tenant:"example",siteId:"Careers"}</script>' + ('' if self.signed_in else self.sign_in)
            return await route.fulfill(body=page, content_type='text/html')
        self.headers.append(request.headers)
        signed_in = self.signed_in or 'signed=ada%40example.test' in request.headers.get('cookie', '')
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
    await RequestEngine(store).start(run, profile_for('workday'), SimpleNamespace(page=page, binding=None), credential)
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
    assert [i.message for i in run.interventions] == [HANDOFF]
    assert tenant.posts == [{'questionnaireAnswers': [{'questionItem': {'id': 'q-auth'}, 'questionMultipleChoiceAnswers': [{'id': 'yes'}]},
                                                      {'questionItem': {'id': 'q-pass'}, 'answerText': 'Student Pass'}]}]
    assert {f.label: f.disposition for f in run.fields.values()} == {'Are you legally authorized to work in Singapore?': 'verified', 'Which pass do you hold?': 'verified'}
    assert run.steps[2] == 'Application Questions' and run.step == 2
    assert all(h['x-calypso-csrf-token'] == 'tok' for h in tenant.headers)
    # Resuming re-verifies without writing again.
    await run_request(context, store, tenant, run)
    assert len(tenant.posts) == 1 and run.interventions[0].message == HANDOFF


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
    assert [i.message for i in run.interventions] == [HANDOFF] and not run.authentication_attempted


async def test_request_mode_never_creates_accounts(context, store):
    tenant = Tenant(signed_in=False)
    run, _ = await run_request(context, store, tenant, credential={'username': 'a@example.test', 'password': 'x', 'state': 'new'})
    assert [i.message for i in run.interventions] == [NEW_ACCOUNT] and not run.authentication_attempted
