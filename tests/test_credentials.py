import json
import string

import keyring
import pytest

from core.automation.accounts import SYMBOLS, generate_login, generate_password
from core.storage.vault import CredentialVault

SITE = 'acme-corp.wd5.myworkdayjobs.com'


def test_logins_saved_before_account_creation_read_as_verified(vault):
    vault.backend.set_password('intern-bot', 'workday:a.wd1.myworkdayjobs.com', json.dumps({'username': 'u', 'password': 'p'}))
    assert vault.credential('a.wd1.myworkdayjobs.com')['state'] == 'verified'


def test_account_state_changes_keep_the_login(vault):
    vault.save_credential('b.wd1.myworkdayjobs.com', 'u', 'p', 'new')
    vault.set_account_state('https://b.wd1.myworkdayjobs.com/job/R1', 'pending_verification')
    assert vault.credential('b.wd1.myworkdayjobs.com') == {'username': 'u', 'password': 'p', 'state': 'pending_verification'}


def test_account_state_needs_a_saved_login(vault):
    with pytest.raises(ValueError):
        vault.set_account_state('c.wd1.myworkdayjobs.com', 'verified')


@pytest.mark.parametrize('module, accepted', [('keyring.backends.macOS', True), ('keyrings.alt.file', False)])
def test_vault_refuses_plaintext_keyring_backends(monkeypatch, module, accepted):
    backend = type('Backend', (), {'__module__': module})()
    monkeypatch.setattr(keyring, 'get_keyring', lambda: backend)
    if accepted:
        assert CredentialVault().backend is backend
    else:
        with pytest.raises(RuntimeError, match='no plaintext fallback'):
            CredentialVault()


@pytest.mark.parametrize('catchall, fmt, expected', [
    ('apps.example.test', '', 'acme_corp_intern@apps.example.test'),
    ('@apps.example.test', 'ben-{company}', 'ben-acme_corp@apps.example.test'),
    ('', 'ignored', 'me@example.test'),
])
def test_login_address_uses_the_catchall_format_or_the_profile_email(catchall, fmt, expected):
    assert generate_login(SITE, 'me@example.test', catchall, fmt)[0] == expected


@pytest.mark.parametrize('email, catchall, fmt', [
    ('me@example.test', 'apps.example.test', 'bad name'),
    ('me@example.test', 'apps.example.test', '.{company}'),
    ('me@example.test', 'apps.example.test', 'a..b'),
    ('me@example.test', 'no-dot', ''),
    ('', '', ''),
])
def test_invalid_login_addresses_are_rejected(email, catchall, fmt):
    with pytest.raises(ValueError):
        generate_login(SITE, email, catchall, fmt)


def test_generated_password_mixes_every_character_class():
    password = generate_password()
    assert len(password) == 18
    for pool in (string.ascii_lowercase, string.ascii_uppercase, string.digits, SYMBOLS):
        assert any(c in pool for c in password)
