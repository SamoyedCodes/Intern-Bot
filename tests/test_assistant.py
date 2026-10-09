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


@pytest.mark.parametrize('finish, text', [('MAX_TOKENS', 'Partial'), ('STOP', '  ')])
def test_incomplete_or_empty_responses_are_rejected(network, finish, text):
    network['payload'] = reply(finish, text)
    with pytest.raises(ValueError, match='could not return a complete response'):
        generate_text('key', 'gemini-2.5-flash', 'draft', 'context')


@pytest.mark.parametrize('key, model, mode, context', [
    ('key', '../../evil', 'draft', 'context'),
    ('key', 'gemini-2.5-flash', 'other', 'context'),
    ('', 'gemini-2.5-flash', 'draft', 'context'),
    ('key', 'gemini-2.5-flash', 'draft', ' '),
    ('key', 'gemini-2.5-flash', 'draft', 'a' * 60001),
])
def test_invalid_requests_never_reach_the_network(network, key, model, mode, context):
    with pytest.raises(ValueError):
        generate_text(key, model, mode, context)
    assert network['requests'] == []
