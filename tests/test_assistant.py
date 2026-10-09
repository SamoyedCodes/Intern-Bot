import json

import pytest

from core.automation import assistant
from core.automation.assistant import NoRedirect, career_facts, generate_text
from core.automation.models import ApplicantProfile


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
    assert not {'email', 'resume_path', 'gender', 'first_name'} & facts.keys()


def test_key_travels_only_in_a_header_and_redirects_are_refused(network):
    assert generate_text('key', 'gemini-2.5-flash', 'draft', '{"skills": "Python"}') == 'Draft based on Python.'
    request = network['requests'][0]
    assert 'key' not in request.full_url
    assert request.get_header('X-goog-api-key') == 'key'
    assert 'tools' not in json.loads(request.data)
    redirects = [h for h in network['handlers'] if isinstance(h, NoRedirect)]
    assert redirects and redirects[0].redirect_request(request, None, 302, 'Found', {}, 'https://evil.test/') is None


def test_openai_uses_the_responses_api_without_storage(network):
    network['payload'] = openai_reply()
    assert generate_text('sk-test', 'gpt-6-luna', 'draft', 'facts', 'openai') == 'Luna draft.'
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
])
def test_incomplete_or_empty_responses_are_rejected(network, provider, model, payload, name):
    network['payload'] = payload
    with pytest.raises(ValueError, match=f'{name} could not return a complete response'):
        generate_text('key', model, 'draft', 'context', provider)


@pytest.mark.parametrize('key, model, mode, context, provider', [
    ('key', '../../evil', 'draft', 'context', 'gemini'),
    ('key', '../../evil', 'draft', 'context', 'openai'),
    ('key', 'gpt-6-luna', 'draft', 'context', 'nope'),
    ('key', 'gemini-2.5-flash', 'other', 'context', 'gemini'),
    ('', 'gemini-2.5-flash', 'draft', 'context', 'gemini'),
    ('key', 'gemini-2.5-flash', 'draft', ' ', 'gemini'),
    ('key', 'gemini-2.5-flash', 'draft', 'a' * 60001, 'gemini'),
])
def test_invalid_requests_never_reach_the_network(network, key, model, mode, context, provider):
    with pytest.raises(ValueError):
        generate_text(key, model, mode, context, provider)
    assert network['requests'] == []
