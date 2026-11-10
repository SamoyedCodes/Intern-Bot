import json

import pytest

from core.storage import onepassword
from core.storage.onepassword import VAULT, OnePasswordLogins

SITE = 'acme.wd5.myworkdayjobs.com'
TOKEN = 'ops_test_token'


class FakeOp:
    """Plays the op CLI against an in-memory vault and records every call."""
    def __init__(self, items=()):
        self.items, self.calls = list(items), []

    def __call__(self, args, stdin, env):
        self.calls.append((args, stdin, env))
        # Service accounts must name the vault on every command.
        assert args[:2] == ['vault', 'get'] or args[args.index('--vault') + 1] == VAULT
        if args[:2] == ['item', 'list']:
            return json.dumps([{k: i[k] for k in ('id', 'urls', 'tags')} for i in self.items])
        if args[:2] == ['item', 'get']:
            return json.dumps(next(i for i in self.items if i['id'] == args[2]))
        if args[:2] == ['item', 'create']:
            item = {**json.loads(stdin), 'id': f'id{len(self.items)}'}
            if any(a.startswith('--generate-password') for a in args):
                item['fields'].append({'purpose': 'PASSWORD', 'value': 'op-generated-secret'})
            self.items.append(item)
            return json.dumps(item)
        if args[:2] == ['item', 'edit']:
            label, value = args[-1].split('[text]=')
            item = next(i for i in self.items if i['id'] == args[2])
            item['fields'] = [f for f in item['fields'] if f.get('label') != label] + [{'label': label, 'value': value}]
            return '{}'
        return '{}'


def logins(fake, token=TOKEN):
    return OnePasswordLogins(lambda: token, fake)


def hand_made(item_id, url, username, password, tags=()):
    return {'id': item_id, 'urls': [{'href': url}], 'tags': list(tags),
            'fields': [{'purpose': 'USERNAME', 'value': username}, {'purpose': 'PASSWORD', 'value': password}]}


def test_a_hand_made_login_is_found_by_url_host_and_reads_as_verified():
    fake = FakeOp([hand_made('x', 'https://other.wd1.myworkdayjobs.com', 'no', 'no'),
                   hand_made('y', f'https://{SITE}/en-US/careers', 'me@example.test', 'secret')])
    assert logins(fake).credential(f'https://{SITE}/job/R1') == {'username': 'me@example.test', 'password': 'secret', 'state': 'verified'}
    assert logins(FakeOp()).credential(SITE) == {}


def test_duplicate_logins_need_selection_even_when_one_was_created_by_the_bot():
    fake = FakeOp([hand_made('a', f'https://{SITE}', 'old', 'p1'), hand_made('b', f'https://{SITE}', 'bot', 'p2', ['intern-bot'])])
    with pytest.raises(RuntimeError, match='More than one login'):
        logins(fake).credential(SITE)
    from core.automation.models import account_context
    selected = account_context(SITE)
    selected.item_id = 'b'
    assert logins(fake).credential(selected)['username'] == 'bot'
    selected.item_id = 'deleted'
    with pytest.raises(RuntimeError, match='associated 1Password login is missing'):
        logins(fake).credential(selected)


def test_shared_sap_hosts_match_the_company_and_reuse_the_account_across_jobs():
    from core.automation.models import account_context
    first = 'https://career44.sapsf.com/career?company=first&career_job_req_id=1'
    second = 'https://career44.sapsf.com/career?company=second&career_job_req_id=1'
    fake = FakeOp([hand_made('a', first, 'first-user', 'p1'), hand_made('b', second, 'second-user', 'p2'),
                   hand_made('legacy', 'https://career44.sapsf.com', 'unknown-company', 'p3')])
    context = account_context(first.replace('req_id=1', 'req_id=2') + '&requestParams=expired')
    assert logins(fake).credential(context)['username'] == 'first-user'
    assert context.item_id == 'a'
    assert logins(fake).credential(second)['username'] == 'second-user'
    with pytest.raises(ValueError, match='tenant'):
        logins(fake).credential('https://career44.sapsf.com')


def test_generated_sap_logins_keep_a_stable_tenant_url_and_password_recipe():
    fake = FakeOp()
    site = 'https://career44.sapsf.com/career?company=integrat02P3&requestParams=secret&career_job_req_id=13892'
    logins(fake).save_credential(site, 'u@example.test', state='new', password_recipe='20,letters,digits,symbols')
    args, stdin, _ = next(c for c in fake.calls if c[0][:2] == ['item', 'create'])
    assert '--generate-password=20,letters,digits,symbols' in args
    assert json.loads(stdin)['urls'][0]['href'] == 'https://career44.sapsf.com/career?company=integrat02P3'
    assert 'requestParams' not in stdin and '13892' not in stdin


def test_shared_workday_sites_match_the_employer_path_not_just_the_server():
    first = 'https://wd5.myworkdaysite.com/recruiting/first/Careers/job/Intern_R1'
    second = 'https://wd5.myworkdaysite.com/recruiting/second/Careers/job/Intern_R1'
    fake = FakeOp([hand_made('a', first, 'first-user', 'p1'), hand_made('b', second, 'second-user', 'p2')])
    assert logins(fake).credential(first)['username'] == 'first-user'
    assert logins(fake).credential(second)['username'] == 'second-user'
    with pytest.raises(ValueError, match='tenant'):
        logins(fake).credential('https://wd5.myworkdaysite.com')


@pytest.mark.parametrize('query', ['company=a&company=b', 'company=a&company=', 'company='])
def test_ambiguous_or_empty_sap_company_ids_never_match_a_saved_login(query):
    from core.automation.models import account_context
    assert account_context('https://career44.sapsf.com/career?' + query) is None


def test_the_token_travels_only_in_the_environment():
    fake = FakeOp()
    logins(fake).credential(SITE)
    args, _, env = fake.calls[0]
    assert env['OP_SERVICE_ACCOUNT_TOKEN'] == TOKEN and TOKEN not in ' '.join(args)


def test_no_token_stops_before_op_runs():
    fake = FakeOp()
    with pytest.raises(RuntimeError, match='service account token'):
        logins(fake, '').credential(SITE)
    assert not fake.calls


def test_a_generated_login_never_puts_a_password_in_argv_and_tracks_account_state():
    fake = FakeOp()
    vault = logins(fake)
    vault.save_credential(SITE, 'acme_intern@apps.example.test', None, 'new')
    create = next(args for args, _, _ in fake.calls if args[:2] == ['item', 'create'])
    assert '--generate-password=24,letters,digits,symbols' in create
    assert vault.credential(SITE) == {'username': 'acme_intern@apps.example.test', 'password': 'op-generated-secret', 'state': 'new'}
    vault.set_account_state(SITE, 'pending_verification')
    assert vault.credential(SITE)['state'] == 'pending_verification'
    assert all('op-generated-secret' not in ' '.join(args) for args, _, _ in fake.calls)


def test_a_known_password_goes_only_through_stdin():
    fake = FakeOp()
    logins(fake).save_credential(SITE, 'u', 'KnownSecret123', 'verified')
    args, stdin, _ = next(c for c in fake.calls if c[0][:2] == ['item', 'create'])
    assert args[2] == '-'
    assert 'KnownSecret123' in stdin and 'KnownSecret123' not in ' '.join(args)
    assert not any(a.startswith('--generate-password') for a in args)
    assert json.loads(stdin)['urls'] == [{'href': f'https://{SITE}', 'primary': True}]


def test_saving_refuses_to_duplicate_and_state_needs_a_login():
    fake = FakeOp([hand_made('a', f'https://{SITE}', 'u', 'p')])
    with pytest.raises(ValueError, match='already in 1Password'):
        logins(fake).save_credential(SITE, 'u2', None, 'new')
    with pytest.raises(ValueError):
        logins(FakeOp()).set_account_state(SITE, 'verified')


def test_a_missing_op_binary_fails_closed(monkeypatch):
    monkeypatch.setattr(onepassword.shutil, 'which', lambda *a, **k: None)
    with pytest.raises(RuntimeError, match='brew install 1password-cli'):
        OnePasswordLogins(lambda: TOKEN).credential(SITE)
