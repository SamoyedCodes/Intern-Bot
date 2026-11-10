"""Fail closed when an OS credential vault is unavailable."""
import json

from core.storage.onepassword import OnePasswordLogins

TOKEN_KEY = "op-service-account-token"


class CredentialVault:
    service = "intern-bot"

    def __init__(self, backend=None, logins=None):
        if backend is None:
            import keyring
            backend = keyring.get_keyring()
            # Do not silently use a plaintext third-party fallback backend.
            if not backend.__class__.__module__.startswith(("keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService")):
                raise RuntimeError("A supported operating-system keychain is required; no plaintext fallback is allowed.")
        self.backend = backend
        # Employer logins live in 1Password; the keychain keeps only its token and the AI API keys.
        self.logins = logins or OnePasswordLogins(lambda: self.get(TOKEN_KEY))

    def set(self, key: str, value: str):
        self.backend.set_password(self.service, key, value)

    def get(self, key: str) -> str:
        return self.backend.get_password(self.service, key) or ""

    # creation_attempted is deliberately distinct from confirmed email verification.
    def save_credential(self, site: str, username: str, password: str | None = None, state: str = "verified", **options):
        self.logins.save_credential(site, username, password, state, **options)

    def credential(self, site: str) -> dict:
        return self.logins.credential(site)

    def set_account_state(self, site: str, state: str):
        self.logins.set_account_state(site, state)

    def keychain_login(self, site: str) -> dict:
        """A login saved by the keychain-only versions, for the one-time import into 1Password."""
        value = self.get("workday:" + site)
        return {"state": "verified", **json.loads(value)} if value else {}
