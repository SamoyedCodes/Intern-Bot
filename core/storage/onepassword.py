"""Employer logins kept in 1Password through the op CLI, authenticated with a service account token."""
import json
import os
import shutil
import subprocess

from core.automation.models import site_key

VAULT = "Job Sites"
TAG = "intern-bot"
STATE = "intern_bot_state"
NO_TOKEN = "Paste your 1Password service account token in Profile → Workday logins."


def run_op(args, stdin, env):
    # Finder-launched apps don't inherit the shell PATH, so also look where Homebrew installs op.
    path = shutil.which("op", path=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin")
    if not path:
        raise RuntimeError("Install the 1Password CLI: brew install 1password-cli")
    result = subprocess.run([path, *args], input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
                            capture_output=True, text=True, env=env, timeout=60)
    if result.returncode:
        if "(101)" in result.stderr:
            raise RuntimeError(f"1Password: the service account can't change the “{VAULT}” vault. Give it read and write access.")
        raise RuntimeError("1Password: " + (result.stderr.strip() or "op failed"))
    return result.stdout


class OnePasswordLogins:
    def __init__(self, token_source, runner=run_op):
        self.token_source, self.runner = token_source, runner

    def op(self, *args, stdin=None) -> str:
        token = self.token_source()
        if not token:
            raise RuntimeError(NO_TOKEN)
        # The token travels only in the child's environment, never in argv.
        return self.runner(list(args), stdin, {**os.environ, "OP_SERVICE_ACCOUNT_TOKEN": token})

    def check(self):
        """Fails with op's message when the token is wrong or can't reach the vault."""
        self.op("vault", "get", VAULT, "--format", "json")

    def _find(self, site: str) -> str:
        host = site_key(site)
        items = [i for i in json.loads(self.op("item", "list", "--vault", VAULT, "--categories", "Login", "--format", "json") or "[]")
                 if any(site_key(u.get("href", "")) == host for u in i.get("urls") or [])]
        items.sort(key=lambda i: TAG not in (i.get("tags") or []))  # A login the bot created wins over a hand-made duplicate.
        return items[0]["id"] if items else ""

    def credential(self, site: str) -> dict:
        item_id = self._find(site)
        if not item_id:
            return {}
        fields = json.loads(self.op("item", "get", item_id, "--vault", VAULT, "--reveal", "--format", "json")).get("fields") or []
        value = lambda match: next((f.get("value") or "" for f in fields if match(f)), "")
        return {"username": value(lambda f: f.get("purpose") == "USERNAME"),
                "password": value(lambda f: f.get("purpose") == "PASSWORD"),
                # Hand-made logins have no state field; they already work, so they read as verified.
                "state": value(lambda f: f.get("label") == STATE) or "verified"}

    def save_credential(self, site: str, username: str, password: str | None = None, state: str = "verified"):
        """Create the login; with no password, 1Password generates one. Passwords go on stdin, never argv."""
        host = site_key(site)
        if self._find(host):
            raise ValueError("A login for this employer is already in 1Password; edit it there.")
        fields = [{"id": "username", "type": "STRING", "purpose": "USERNAME", "label": "username", "value": username},
                  {"id": STATE, "type": "STRING", "label": STATE, "value": state}]
        if password is not None:
            fields.append({"id": "password", "type": "CONCEALED", "purpose": "PASSWORD", "label": "password", "value": password})
        template = {"title": "Workday · " + host, "category": "LOGIN", "tags": [TAG],
                    "urls": [{"href": "https://" + host, "primary": True}], "fields": fields}
        generate = [] if password is not None else ["--generate-password=24,letters,digits,symbols"]
        self.op("item", "create", "--vault", VAULT, *generate, "--format", "json", stdin=json.dumps(template))

    def set_account_state(self, site: str, state: str):
        item_id = self._find(site)
        if not item_id:
            raise ValueError("No saved login for this employer.")
        self.op("item", "edit", item_id, "--vault", VAULT, f"{STATE}[text]={state}")
