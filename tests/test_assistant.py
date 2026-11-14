import json
from types import SimpleNamespace

import anthropic
import pytest

from core.automation import assistant
from core.automation.assistant import PROVIDERS, NoRedirect, askable, autofill, pointer_only, career_facts, endpoint, generate_text, check_connection
from core.automation.fields import FormField
from core.automation.models import ApplicantProfile, Education, Experience
from core.automation.privacy import redact


def cfg(provider='gemini', model='gemini-2.5-flash', key='key', url='', facts=False):
    return {'provider': provider, 'name': PROVIDERS.get(provider, {}).get('name', provider), 'model': model, 'key': key,
            'url': url, 'local': False, 'facts': facts}


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        assert limit == 1_000_001  # The response body is read with a bound.
        return json.dumps(self.payload).encode()


def reply(finish='STOP', text='Draft based on Python.'):
    return {'candidates': [{'finishReason': finish, 'content': {'parts': [{'text': text}]}}]}


def chat_reply(finish='stop', text='Chat draft.'):
    return {'choices': [{'finish_reason': finish, 'message': {'role': 'assistant', 'content': text}}]}


def openai_reply(status='completed', text='Luna draft.'):
    return {'status': status, 'output': [{'type': 'reasoning', 'summary': []},
                                         {'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}


@pytest.fixture
def network(monkeypatch):
    """Captures what generate_text would send; `payload` is what the provider answers."""
    sent = {'requests': [], 'handlers': [], 'payload': reply()}
    class Opener:
        def open(self, request, timeout):
            assert timeout == 40
            sent['requests'].append(request)
            return Response(sent['payload'])
    def build_opener(*handlers):
        sent['handlers'].extend(handlers)
        return Opener()
    monkeypatch.setattr(assistant, 'build_opener', build_opener)
    return sent


def test_career_facts_exclude_identity_contact_and_documents():
    profile = ApplicantProfile(first_name='Private name', email='secret@example.test', resume_path='/private/resume.pdf', gender='Private', skills='Python')
    facts = career_facts(profile)
    assert facts['skills'] == 'Python'
    assert career_facts(ApplicantProfile(language_proficiency=[{'language': 'Chinese', 'fluent': True}]))['language_proficiency'][0]['language'] == 'Chinese'
    assert not {'email', 'resume_path', 'gender', 'first_name'} & facts.keys()


def test_key_travels_only_in_a_header_and_redirects_are_refused(network):
    assert generate_text(cfg(), 'draft', '{"skills": "Python"}') == 'Draft based on Python.'
    request = network['requests'][0]
    assert 'key' not in request.full_url
    assert request.get_header('X-goog-api-key') == 'key'
    assert 'tools' not in json.loads(request.data)
    redirects = [h for h in network['handlers'] if isinstance(h, NoRedirect)]
    assert redirects and redirects[0].redirect_request(request, None, 302, 'Found', {}, 'https://evil.test/') is None


def test_connection_test_asks_for_a_tiny_reply_and_accepts_a_cut_short_one(network):
    network['payload'] = reply('MAX_TOKENS', '')
    assert 'accepted' in check_connection(cfg())
    assert json.loads(network['requests'][0].data)['generationConfig']['maxOutputTokens'] == 16
    with pytest.raises(ValueError, match='could not return'):
        generate_text(cfg(), 'draft', 'facts')  # Ordinary requests still reject a cut-short reply.
    network['payload'] = {'error': 'bad key'}
    with pytest.raises(ValueError, match='Check the model, key'):
        check_connection(cfg())


def test_openai_uses_the_responses_api_without_storage(network):
    network['payload'] = openai_reply()
    assert generate_text(cfg('openai', 'gpt-6-luna', 'sk-test'), 'draft', 'facts') == 'Luna draft.'
    request = network['requests'][0]
    body = json.loads(request.data)
    assert request.full_url == 'https://api.openai.com/v1/responses'
    assert request.get_header('Authorization') == 'Bearer sk-test'
    assert body['model'] == 'gpt-6-luna' and body['input'] == 'facts' and body['store'] is False and 'tools' not in body


@pytest.mark.parametrize('provider, model, payload, name', [
    ('gemini', 'gemini-2.5-flash', reply('MAX_TOKENS', 'Partial'), 'Gemini'),
    ('gemini', 'gemini-2.5-flash', reply('STOP', '  '), 'Gemini'),
    ('openai', 'gpt-6-luna', openai_reply('incomplete'), 'OpenAI'),
    ('openai', 'gpt-6-luna', openai_reply(text=' '), 'OpenAI'),
    ('deepseek', 'deepseek-flash', chat_reply('length', 'Partial'), 'DeepSeek'),
    ('deepseek', 'deepseek-flash', chat_reply(text=''), 'DeepSeek'),
])
def test_incomplete_or_empty_responses_are_rejected(network, provider, model, payload, name):
    network['payload'] = payload
    with pytest.raises(ValueError, match=f'{name} could not return a complete response'):
        generate_text(cfg(provider, model), 'draft', 'context')


@pytest.mark.parametrize('config, mode, context', [
    (cfg(model='../../evil'), 'draft', 'context'),
    (cfg('openai', '../../evil'), 'draft', 'context'),
    (cfg('nope', 'gpt-6-luna'), 'draft', 'context'),
    (cfg(), 'other', 'context'),
    (cfg(key=''), 'draft', 'context'),
    (cfg('deepseek', 'deepseek-flash', ''), 'draft', 'context'),
    (cfg('compatible', ''), 'draft', 'context'),
    (cfg(), 'draft', ' '),
    (cfg(), 'draft', 'a' * 60001),
    (cfg('compatible', 'qwen3:8b', '', 'http://example.com/v1'), 'draft', 'context'),
    (cfg('compatible', 'qwen3:8b', '', 'https://user:secret@example.com/v1'), 'draft', 'context'),
    (cfg('compatible', 'qwen3:8b', '', 'file:///etc/passwd'), 'draft', 'context'),
])
def test_invalid_requests_never_reach_the_network(network, config, mode, context):
    with pytest.raises(ValueError):
        generate_text(config, mode, context)
    assert network['requests'] == []


def test_deepseek_and_local_servers_use_chat_completions(network):
    network['payload'] = chat_reply()
    assert generate_text(cfg('deepseek', 'deepseek-flash', 'sk-ds'), 'draft', 'facts') == 'Chat draft.'
    assert generate_text(cfg('compatible', 'qwen3:8b', '', 'http://localhost:1234/v1/'), 'draft', 'facts') == 'Chat draft.'
    cloud, local = network['requests']
    assert cloud.full_url == 'https://api.deepseek.com/chat/completions' and cloud.get_header('Authorization') == 'Bearer sk-ds'
    assert local.full_url == 'http://localhost:1234/v1/chat/completions' and not local.has_header('Authorization')
    body = json.loads(local.data)
    assert body['model'] == 'qwen3:8b' and body['stream'] is False and [m['role'] for m in body['messages']] == ['system', 'user']


@pytest.mark.parametrize('url', ['http://127.0.0.1:11434/v1', 'http://[::1]:1234/v1', 'https://openrouter.ai/api/v1'])
def test_https_or_this_mac_server_urls_are_accepted(url):
    assert endpoint(url) == url + '/chat/completions'


class Claude:
    """Stands in for anthropic.Anthropic and records how it was built and called."""
    calls = []
    reply = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text='Claude draft.')])

    def __init__(self, **options):
        Claude.calls.append(options)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **request: Claude.calls.append(request) or Claude.reply))


@pytest.mark.parametrize('model, fallback', [('claude-opus-5-5', True), ('claude-haiku-5-5', False)])
def test_claude_is_called_through_the_sdk_without_retries(monkeypatch, model, fallback):
    monkeypatch.setattr(anthropic, 'Anthropic', Claude)
    Claude.calls = []
    assert generate_text(cfg('anthropic', model, 'sk-ant'), 'draft', 'facts') == 'Claude draft.'
    options, request = Claude.calls
    assert options == {'api_key': 'sk-ant', 'max_retries': 0, 'timeout': 40}
    assert request['model'] == model and request['output_config'] == {'effort': 'low'} and request['messages'][0]['content'] == 'facts'
    assert ('fallbacks' in request) is fallback


def test_a_refused_or_truncated_claude_reply_is_rejected(monkeypatch):
    monkeypatch.setattr(anthropic, 'Anthropic', Claude)
    monkeypatch.setattr(Claude, 'reply', SimpleNamespace(stop_reason='refusal', content=[]))
    with pytest.raises(ValueError, match='Claude could not return a complete response'):
        generate_text(cfg('anthropic', 'claude-opus-5-5', 'sk-ant'), 'draft', 'facts')


PERSON = ApplicantProfile(first_name='Jonathan', last_name='Tanaka', email='jon@private.test', phone='+65 9123 4567',
                         address_line1='88 Hidden Road', postal_code='424242', linkedin_url='https://linkedin.com/in/jon-private',
                         skills='Python, SQL', summary='Jonathan Tanaka (jon@private.test, 9123 4567) builds data tools.',
                         education=[Education(school='Example University', degree='BSc Data Science', end_date='2027-05')],
                         experience=[Experience(employer='Fictional Co', job_title='Analyst Intern')])


def sent_text(network):
    return json.loads(network['requests'][-1].data)['contents'][0]['parts'][0]['text']


def test_autofill_keeps_only_replies_inside_the_closed_sets(network):
    questions = [FormField('a', 'Email', '', 'email'), FormField('b', 'Graduation year', '', 'text'),
                 FormField('c', 'Degree level', '', 'select-one', options=["Bachelor's", "Master's"]),
                 FormField('d', 'Internship period', '', 'text'), FormField('e', 'Gender', '', 'text'),
                 FormField('f', 'Email again', '', 'text'), FormField('g', 'Start', '', 'text')]
    network['payload'] = reply(text='```json\n' + json.dumps({
        '1': {'fact': 'email'}, '2': {'fact': 'education.0.end_date.year'}, '3': {'value': "Bachelor's"},
        'q4': {'saved': 's1'}, '5': {'fact': 'gender'}, '6': {'fact': 'email.year'}, 'q7': {'saved': 's9'}, 'q9': {'fact': 'email'}, 'x': None}) + '\n```')
    assert autofill(cfg(), questions, ['When can you start?'], PERSON) == {
        'Email': ('fact', 'email'), 'Graduation year': ('fact', 'education.0.end_date.year'), 'Internship period': ('saved', 0)}


@pytest.mark.parametrize('field, value, expected', [
    (FormField('a', 'Degree level', '', 'select-one', options=["Bachelor's", "Master's"]), "bachelor's", "Bachelor's"),
    (FormField('a', 'Degree level', '', 'select-one', options=["Bachelor's", "Master's"]), 'PhD', None),
    (FormField('a', 'Currently enrolled', '', 'radio', options=['Yes', 'No']), True, 'Yes'),
    (FormField('a', 'Years of Python', '', 'text'), '2', '2'),
    (FormField('a', 'Years of Python', '', 'text'), 'x' * 121, None),
    (FormField('a', 'Years of Python', '', 'text'), 'two\nyears', None),
])
def test_autofill_values_need_career_facts_and_must_fit_the_form(network, field, value, expected):
    network['payload'] = reply(text=json.dumps({'1': {'value': value}}))
    assert autofill(cfg(facts=True), [field], [], PERSON) == ({field.label: ('value', expected)} if expected is not None else {})
    assert autofill(cfg(facts=False), [field], [], PERSON) == {}


def test_without_career_facts_no_profile_value_leaves_this_mac(network):
    network['payload'] = reply(text='{}')
    autofill(cfg(), [FormField('a', 'School name', '', 'text')], ['Saved question?'], PERSON)
    text = sent_text(network)
    assert 'education.0.school' in text and 'Saved question?' in text
    for value in ('Jonathan', 'Tanaka', 'jon@private.test', '9123', 'Hidden Road', '424242', 'jon-private', 'Python', 'Example University', 'Fictional Co', '2027'):
        assert value not in text


def test_career_facts_are_sent_masked_only_when_allowed(network):
    network['payload'] = reply(text='{}')
    autofill(cfg(facts=True), [FormField('a', 'School name', '', 'text')], [], PERSON)
    text = sent_text(network)
    assert 'Example University' in text and 'Python' in text
    for value in ('Jonathan', 'Tanaka', 'jon@private.test', '9123', 'Hidden Road', '424242', 'jon-private'):
        assert value not in text


def test_redaction_masks_identity_but_keeps_dates_and_skills():
    person = ApplicantProfile(first_name='May', last_name='Lim', email='may@x.test', phone_number='91234567', address_line1='1 Secret Ave')
    text = redact('May Lim, may@x.test, +65 9123-4567, 1 Secret Ave, www.maylim.dev, github.com/maylim. Interned May 2025 using Python.', person)
    assert text == 'May [name], [email], +65 [phone], [address], [link] [link] Interned May 2025 using Python.'


@pytest.mark.parametrize('field, sent', [
    (FormField('a', 'Expected graduation date', '', 'text'), True),
    (FormField('a', 'Highest degree', '', 'combobox'), True),
    (FormField('a', 'Why do you want to work here?', '', 'textarea'), False),
    (FormField('a', 'Cover letter', '', 'file'), False),
    (FormField('a', 'Gender', '', 'select-one'), False),
    (FormField('a', 'Are you authorized to work in Canada?', '', 'radio'), False),
    (FormField('a', 'Will you now or in the future require sponsorship?', '', 'radio'), False),
    (FormField('a', 'I agree to the terms and conditions', '', 'checkbox'), False),
    (FormField('a', 'Expected salary', '', 'text'), False),
    (FormField('a', 'Are you fully Covid-19 vaccinated?', '', 'radio'), False),
    (FormField('a', 'Confirm', '', 'checkbox'), False),
    (FormField('a', 'Confirm', '', 'radio'), False),
    (FormField('a', 'Currently enrolled', '', 'checkbox'), False),
    (FormField('a', 'Primary language', '', 'text'), True),
])
def test_only_factual_non_sensitive_questions_are_asked(field, sent):
    assert askable(field) is sent


def test_an_unparseable_reply_fills_nothing(network):
    network['payload'] = reply(text='No idea.')
    with pytest.raises(ValueError, match='not a question mapping'):
        autofill(cfg(), [FormField('a', 'Q?', '', 'text')], ['Saved?'], PERSON)


def test_standing_answers_settle_declarations_with_one_of_the_forms_options(network):
    person = PERSON.model_copy(update={'standing_answers': 'I, Jonathan Tanaka, am a Singapore citizen. I am not related to any employee of any employer.'})
    relative = FormField('a', 'Are you a relative of any UOB employee?', '', 'select-one', options=['Yes', 'No'])
    citizen = FormField('b', 'Citizenship status', '', 'select-one', options=['Singapore Citizen', 'Permanent Resident', 'Foreigner'])
    assert askable(citizen, True) and not askable(citizen)  # Legal-status questions are sent only with standing answers.
    assert not askable(FormField('c', 'Gender', '', 'select-one'), True)
    network['payload'] = reply(text=json.dumps({'q1': {'standing': 'no'}, 'q2': {'standing': 'Singaporean'}}))
    assert autofill(cfg(), [relative, citizen], [], person) == {relative.label: ('standing', 'No')}  # "Singaporean" is not an option.
    text = sent_text(network)
    assert 'not related to any employee' in text and 'Jonathan' not in text
    assert autofill(cfg(), [relative], [], PERSON) == {}  # Without statements the same reply is dropped.
    assert 'standing_answers' not in sent_text(network)


def test_an_answer_the_form_did_not_take_is_sent_masked_and_matched_only_to_a_listed_option(network):
    heard = FormField('a', 'How Did You Hear About Us?', '', 'combobox', options=['UOB Careers Website', 'LinkedIn'])
    prefix = FormField('b', 'Prefix', '', 'combobox', options=['Mr.', 'Ms.'])
    network['payload'] = reply(text=json.dumps({'q1': {'value': 'UOB Careers Website'}, 'q2': {'value': 'Sir'}}))
    found = autofill(cfg(), [heard, prefix], [], PERSON, {heard.label: f'Company website, said {PERSON.first_name}'})
    assert found == {heard.label: ('value', 'UOB Careers Website')}  # "Sir" is not listed, and q2 had no answer to match.
    text = sent_text(network)
    assert '"answer": "Company website, said [name]"' in text and PERSON.first_name not in text


def test_personal_and_legal_questions_go_as_wording_and_come_back_only_as_pointers(network):
    person = PERSON.model_copy(update={'gender': 'Non-binary', 'citizenship': 'Singaporean', 'requires_sponsorship': False})
    questions = [FormField('a', 'Gender', '', 'select-one', options=['Female', 'Male', 'Non-binary']), FormField('b', 'Visa sponsorship needed?', '', 'radio', options=['Yes', 'No']),
                 FormField('c', 'Expected salary', '', 'text'), FormField('d', 'Nationality', '', 'text')]
    network['payload'] = reply(text=json.dumps({'q1': {'fact': 'gender'}, 'q2': {'value': 'No'}, 'q3': {'standing': '5000'}, 'q4': {'saved': 's1'}}))
    assert autofill(cfg(facts=True), questions, ['Country of citizenship?'], person) == {'Gender': ('fact', 'gender'), 'Nationality': ('saved', 0)}
    text = sent_text(network).split('Career facts:')[0]
    assert '"pointer_only": true' in text and '"gender": "gender"' in text
    assert 'Singaporean' not in sent_text(network) and '"requires_sponsorship": false' not in text
    assert [pointer_only(FormField('a', label, '', kind)) for label, kind in
            (('Gender', 'text'), ('Visa status', 'text'), ('I agree to share my gender', 'radio'), ('School', 'text'), ('Gender', 'checkbox'))] == [True, True, False, False, False]


def test_organising_sends_wordings_and_fact_names_only_and_keeps_replies_inside_the_closed_sets(network):
    from core.automation.assistant import organise
    from core.automation.models import ApprovedAnswer
    answers = [ApprovedAnswer(question='When can you start?', value='SECRET-A', scope='employer', scope_key='secret-employer.example'),
               ApprovedAnswer(question='Earliest start date?', value='SECRET-B', variants=['Start']), ApprovedAnswer(question='Email', fact='email'),
               ApprovedAnswer(question='I agree to the terms', value=True), ApprovedAnswer(question='when can you start', value='SECRET-C')]
    network['payload'] = reply(text=json.dumps({'same': [['t1', 't2', 't9'], ['t3'], 'x'], 'facts': {'t3': 'email', 't1': 'password', 't8': 'email'},
                                                'category': {'t1': 'Availability', 't2': 'Nonsense'}, 'generic': ['t1', 't7']}))
    assert organise(cfg(), answers, PERSON) == {'same': [['when can you start', 'earliest start date']], 'facts': {'email': 'email'},
                                                'category': {'when can you start': 'Availability'}, 'generic': ['when can you start']}
    text = sent_text(network)
    assert json.loads(text)['questions'] == {'t1': 'When can you start?', 't2': 'Earliest start date?', 't3': 'Email'}
    for value in ('SECRET', 'secret-employer', 'agree', 'Jonathan', 'jon@private.test', 'Example University'):
        assert value not in text
    network['payload'] = reply(text='Sorry.')
    with pytest.raises(ValueError, match='nothing was changed'):
        organise(cfg(), answers, PERSON)
