"""Employer logins kept in 1Password through the op CLI, authenticated with a service account token."""
import json
import os
import shutil
import subprocess

from core.automation.models import AccountContext, account_context

VAULT = "Job Sites"
TAG = "intern-bot"
STATE = "intern_bot_state"
NO_TOKEN = "Paste your 1Password service account token in Profile → Employer accounts."


class AmbiguousLogins(RuntimeError):
    def __init__(self, items):
        super().__init__("More than one login matches this employer in Job Sites. Choose the account to use, then resume.")
        self.options = [f"[{item['id']}] {item.get('title') or 'Employer login'}" for item in items]


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
        raise RuntimeError("1Password could not complete the vault operation. Check the token, vault permissions and connection.")
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
        account = site if isinstance(site, AccountContext) else account_context(site)
        if account is None:
            raise ValueError("Identify the employer tenant before accessing its login.")
        items = [i for i in json.loads(self.op("item", "list", "--vault", VAULT, "--categories", "Login", "--format", "json") or "[]")
                 if any(self._matches(account, u.get("href", "")) for u in i.get("urls") or [])]
        if account.item_id:
            items = [i for i in items if i["id"] == account.item_id]
            if not items:
                raise RuntimeError("The associated 1Password login is missing or belongs to another tenant. Check its website address in Job Sites before resuming.")
        if len(items) > 1:
            raise AmbiguousLogins(items)
        return items[0]["id"] if items else ""

    @staticmethod
    def _matches(account, url):
        try:
            candidate = account_context(url)
            return candidate is not None and candidate.key == account.key
        except ValueError:
            return False

    def credential(self, site: str) -> dict:
        item_id = self._find(site)
        if not item_id:
            return {}
        if isinstance(site, AccountContext):
            site.item_id = item_id
        fields = json.loads(self.op("item", "get", item_id, "--vault", VAULT, "--reveal", "--format", "json")).get("fields") or []
        value = lambda match: next((f.get("value") or "" for f in fields if match(f)), "")
        return {"username": value(lambda f: f.get("purpose") == "USERNAME"),
                "password": value(lambda f: f.get("purpose") == "PASSWORD"),
                # Hand-made logins have no state field; they already work, so they read as verified.
                "state": value(lambda f: f.get("label") == STATE) or "verified"}

    def save_credential(self, site: str, username: str, password: str | None = None, state: str = "verified", *, password_recipe="24,letters,digits,symbols"):
        """Create the login; with no password, 1Password generates one. Passwords go on stdin, never argv."""
        account = site if isinstance(site, AccountContext) else account_context(site)
        if account is None:
            raise ValueError("Identify the employer tenant before saving its login.")
        if self._find(account):
            raise ValueError("A login for this employer is already in 1Password; edit it there.")
        fields = [{"id": "username", "type": "STRING", "purpose": "USERNAME", "label": "username", "value": username},
                  {"id": STATE, "type": "STRING", "label": STATE, "value": state}]
        if password is not None:
            fields.append({"id": "password", "type": "CONCEALED", "purpose": "PASSWORD", "label": "password", "value": password})
        fields.append({"id": "intern_bot_account", "type": "STRING", "label": "intern_bot_account", "value": account.key})
        template = {"title": account.provider + " · " + account.tenant, "category": "LOGIN", "tags": [TAG],
                    "urls": [{"href": account.login_url, "primary": True}], "fields": fields}
        generate = [] if password is not None else ["--generate-password=" + password_recipe]
        self.op("item", "create", "-", "--vault", VAULT, *generate, "--format", "json", stdin=json.dumps(template))

    def set_account_state(self, site: str, state: str):
        item_id = self._find(site)
        if not item_id:
            raise ValueError("No saved login for this employer.")
        self.op("item", "edit", item_id, "--vault", VAULT, f"{STATE}[text]={state}")
