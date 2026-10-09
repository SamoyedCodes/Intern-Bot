"""Fail closed when an OS credential vault is unavailable."""
import json

from core.automation.models import site_key


class CredentialVault:
    service = "intern-bot"

    def __init__(self, backend=None):
        if backend is None:
            import keyring
            backend = keyring.get_keyring()
            # Do not silently use a plaintext third-party fallback backend.
            if not backend.__class__.__module__.startswith(("keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService")):
                raise RuntimeError("A supported operating-system keychain is required; no plaintext fallback is allowed.")
        self.backend = backend

    def set(self, key: str, value: str):
        self.backend.set_password(self.service, key, value)

    def get(self, key: str) -> str:
        return self.backend.get_password(self.service, key) or ""

    def save_credential(self, site: str, username: str, password: str):
        self.set("workday:" + site_key(site), json.dumps({"username": username, "password": password}))

    def credential(self, site: str) -> dict:
        value = self.get("workday:" + site_key(site))
        return json.loads(value) if value else {}
