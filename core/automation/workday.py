"""Conservative Workday DOM adapter. Unknown layouts become interventions."""
from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from urllib.parse import urlsplit

from core.automation.models import normalized, site_key

SCAN = Path(__file__).with_name("scan.js").read_text()
GROUP_SELECTORS = {
    "experience": '[data-intern-group="experience"],[data-automation-id="workExperienceSection"],[role="group"][aria-labelledby="Work-Experience-section"]',
    "education": '[data-intern-group="education"],[data-automation-id="educationSection"],[role="group"][aria-labelledby="Education-section"]',
}
ROW_SELECTOR = '[data-intern-row],[data-automation-id="workExperience"],[data-automation-id="education"],[role="group"][aria-labelledby$="-panel"]'
NEXT_NAMES = ("Save and Continue", "Save & Continue", "Continue", "Next")


class WorkdayPageError(RuntimeError):
    """A recognized site failure that needs a manual handoff, not another action."""


@dataclass
class FormField:
    key: str
    label: str
    selector: str
    kind: str
    value: str | bool = ""
    options: list[str] = dataclass_field(default_factory=list)
    option: str = ""
    group: str = ""
    row: int = 0
    required: bool = False
    disabled: bool = False
    invalid: bool = False
    readonly: bool = False
    file_digest: str = ""
    uploaded: bool = False
    split_phone: bool = False


class WorkdayAdapter:
    inline_review = False
    def __init__(self, page, job_url, test_mode=False):
        self.page = page
        self.host = site_key(job_url)
        self.test_mode = test_mode
        self.auth_attempted = False
        self.pending = set()
        self.uploads = {}
        page.on("request", self._request_started)
        page.on("requestfinished", lambda request: self.pending.discard(request))
        page.on("requestfailed", lambda request: self.pending.discard(request))

    def _request_started(self, request):
        if request.resource_type in {"xhr", "fetch", "script"}:
            self.pending.add(request)

    async def raise_for_site_error(self):
        # Only the bounded error code enters diagnostics; surrounding text can contain personal data.
        text = await self.page.locator("body").inner_text()
        code = re.search(r"\bVPS\|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", text, re.I)
        refresh_error = "something went wrong" in text.casefold() and "please refresh the page and then try again" in text.casefold()
        if code or refresh_error:
            label = f" ({code.group(0)})" if code else ""
            raise WorkdayPageError(f"The site reported a page error{label}. Automation is paused. Inspect the browser and preserve any unsaved answers before refreshing, then resume. If it persists, try again later or contact the employer with the error code.")

    async def wait_ready(self):
        stable = 0
        for _ in range(100):
            await self.raise_for_site_error()
            busy = await self.page.locator('[aria-busy="true"]:visible,[role="progressbar"]:visible').count()
            if not self.pending and not busy:
                stable += 1
                if stable >= 2:
                    return
            else:
                stable = 0
            await asyncio.sleep(.1)
        raise TimeoutError("The form did not finish its pending update.")

    def assert_origin(self):
        current = urlsplit(self.page.url)
        if not self.test_mode and (current.scheme != "https" or current.hostname != self.host or current.port not in (None, 443)):
            raise RuntimeError("The browser left the employer HTTPS origin. Review the redirect manually.")

    async def coverage_problem(self):
        # Never claim coverage of controls hidden inside an unsupported frame/shadow root.
        if await self.page.locator('iframe:visible').count():
            return "This page contains an embedded frame. Complete its fields manually; automatic coverage is not supported yet."
        shadow = await self.page.evaluate("() => [...document.querySelectorAll('*')].some(e => e.shadowRoot && e.getClientRects().length)")
        if shadow:
            return "This page contains shadow-root controls. Automatic coverage is not supported for this layout."
        return ""

    async def scan(self):
        self.assert_origin()
        await self.wait_ready()
        fields = [FormField(**row) for row in await self.page.evaluate(SCAN, getattr(self, "scan_root", None))]
        for field in fields:
            if field.kind == "file" and field.value:
                if field.uploaded:
                    name, digest = self.uploads.get(field.key, ("", ""))
                    if name == field.value and not field.invalid:
                        field.file_digest = digest
                else:
                    content = await self.page.locator(field.selector).evaluate("async e => Array.from(new Uint8Array(await e.files[0].arrayBuffer()))")
                    field.file_digest = hashlib.sha256(bytes(content)).hexdigest()
        return fields

    async def stage(self):
        self.assert_origin()
        await self.wait_ready()
        if await self.page.locator('iframe[src*="captcha" i]:visible,[data-automation-id="captcha"]:visible').count():
            return "verification"
        headings = await self.page.locator('h1:visible,h2:visible,[aria-current="step"]:visible,[data-automation-id="progressBarActiveStep"]:visible').all_text_contents()
        heading = " ".join(headings).casefold()
        if any(x in heading for x in ("verify your", "check your email", "activate your", "verification code")):
            return "verification"
        if await self.page.locator('input[type="password"]:visible').count():
            if await self.page.locator('[data-automation-id="signInSubmitButton"]:visible').count() == 1:
                return "sign_in"
            if await self.page.locator('[data-automation-id="createAccountSubmitButton"]:visible').count() == 1:
                return "create_account"
            if "sign in" in heading or "log in" in heading:
                return "sign_in"
            if "create account" in heading:
                return "create_account"
            return "authentication"
        # Disclosure pages are not review pages even when the final submit control exists.
        for fragment, stage in (("self identify", "disclosures"), ("voluntary", "disclosures"),
                                ("disclosure", "disclosures"), ("application questions", "questions"),
                                ("my experience", "experience"), ("my information", "information"),
                                ("autofill with resume", "resume")):
            if fragment in heading:
                return stage
        if "review" in heading and await self.page.get_by_role("button", name=re.compile(r"^Submit( Application)?$", re.I)).count():
            return "review"
        if await self.page.locator('input[type="file"]').count():
            return "resume"
        return "start"

    async def errors(self):
        # Do not return raw messages (which may echo passwords) to diagnostics.
        invalid = await self.page.locator('[aria-invalid="true"]:visible,[data-automation-id="errorMessage"]:visible').count()
        alerts = await self.page.locator('[role="alert"]:visible').evaluate_all('''els => els.filter(e => {
          const item = e.closest('[data-automation-id="resumeUpload"] [data-automation-id="file-upload-item"]');
          const name = item?.querySelector('[data-automation-id="file-upload-item-name"]')?.textContent.trim();
          return !(name && item.querySelector('[data-automation-id="file-upload-successful"]') &&
            e.textContent.trim() === name + ' successfully uploaded');
        }).length''')
        return invalid + alerts

    async def row_counts(self):
        counts = {}
        for name, selector in GROUP_SELECTORS.items():
            container = self.page.locator(selector)
            if await container.count() == 1:
                counts[name] = await container.locator(ROW_SELECTOR).count()
        return counts

    async def ensure_rows(self, profile):
        for group, selector in GROUP_SELECTORS.items():
            expected = len(getattr(profile, group))
            container = self.page.locator(selector)
            if await container.count() != 1:
                if expected and await self.stage() == "experience":
                    return f"Cannot identify the {group} section. Open it manually before resuming."
                continue
            count = await container.locator(ROW_SELECTOR).count()
            if count > expected:
                return f"The form has {count} {group} rows but the profile has {expected}. Reconcile them before resuming."
            while count < expected:
                button = container.get_by_role("button", name=re.compile(r"^Add( Another| Education| Work Experience)?$", re.I))
                if await button.count() != 1:
                    return f"Add the missing {group} row manually; the Add control is ambiguous."
                await button.click()
                try:
                    await container.locator(ROW_SELECTOR).nth(count).wait_for(state="visible", timeout=3000)
                except Exception:
                    return f"Adding a {group} row did not produce a visible row."
                new_count = await container.locator(ROW_SELECTOR).count()
                if new_count != count + 1:
                    return f"Unexpected {group} row count; inspect the browser."
                count = new_count
        return ""

    @staticmethod
    def matches(field, value):
        if field.kind == "radio":
            return field.value == (normalized(field.option) == normalized(str(value)))
        if field.kind == "checkbox":
            return isinstance(value, bool) and field.value == value
        if field.kind == "file":
            path = Path(str(value)).expanduser()
            return path.is_file() and field.value == path.name and field.file_digest == hashlib.sha256(path.read_bytes()).hexdigest()
        return normalized(str(field.value)) == normalized(str(value))

    async def fill(self, field, value):
        self.assert_origin()
        await self.raise_for_site_error()
        control = self.page.locator(field.selector)
        if await control.count() != 1 or field.disabled or field.readonly:
            return False
        if field.kind == "password":
            return False
        if field.kind == "checkbox":
            if not isinstance(value, bool):
                return False
            if await control.get_attribute("role") == "checkbox":
                if (await control.get_attribute("aria-checked") == "true") != value:
                    await control.click()
            else:
                await control.set_checked(value)
        elif field.kind == "radio":
            if normalized(field.option) == normalized(str(value)):
                await control.click()
        elif field.kind == "file":
            path = Path(str(value)).expanduser().resolve()
            if not path.is_file() or field.uploaded:
                return False
            content = path.read_bytes()
            await control.set_input_files({"name": path.name, "mimeType": mimetypes.guess_type(path.name)[0] or "application/octet-stream", "buffer": content})
            self.uploads[field.key] = (path.name, hashlib.sha256(content).hexdigest())
        elif field.kind == "select-one":
            options = [o for o in field.options if normalized(o) == normalized(str(value))]
            if len(options) != 1:
                return False
            await control.select_option(label=options[0])
        elif field.kind == "combobox":
            await control.click()
            if await control.evaluate("e => e.tagName === 'INPUT'"):
                await control.fill(str(value))
                if await control.get_attribute("data-uxi-widget-type") == "selectinput":
                    await control.press("Enter")
            option = self.page.get_by_role("option", name=str(value), exact=True)
            option = option.or_(self.page.locator('[data-automation-id="promptLeafNode"]:visible').filter(has=self.page.get_by_text(str(value), exact=True)))
            await option.wait_for(state="visible", timeout=3000)
            if await option.count() != 1:
                return False
            await option.click()
        elif field.kind in {"text", "email", "tel", "url", "number", "date", "month", "textarea", "search", "div", "spinbutton"}:
            await control.fill(str(value))
        else:
            return False
        if field.kind not in {"file", "radio"}:
            await control.evaluate("e => e.blur()")
        # Give framework validation and dependent controls a chance to settle.
        await self.page.wait_for_timeout(150)
        return True

    async def exact_action(self, names, scope=None):
        """Only explicit non-submission actions; no generic submit selector or Enter."""
        self.assert_origin()
        await self.raise_for_site_error()
        allowed = set(NEXT_NAMES) | {"Apply", "Apply Now", "Autofill with Resume", "Apply Manually", "Sign In", "Create Account"}
        root = scope or (self.page.locator(self.scan_root) if getattr(self, "scan_root", None) else self.page)
        for name in names:
            if name not in allowed:
                raise ValueError("Action is outside the preparation allowlist.")
            matches = root.get_by_role("button", name=name, exact=True).or_(root.get_by_role("link", name=name, exact=True))
            visible = [matches.nth(i) for i in range(await matches.count()) if await matches.nth(i).is_visible()]
            if len(visible) == 1:
                await visible[0].click()
                return True
        return False

    async def open_sign_in(self):
        self.assert_origin()
        link = self.page.locator('[data-automation-id="signInLink"]:visible')
        if await link.count() != 1:
            return False
        await link.click()
        await self.page.locator('[data-automation-id="signInSubmitButton"]').wait_for(state="visible")
        return True

    async def authenticate(self, credential, stage):
        self.assert_origin()
        await self.raise_for_site_error()
        if self.auth_attempted:
            return "Authentication has already been attempted. Complete sign-in or activation manually, then resume."
        if not credential.get("username") or not credential.get("password"):
            return "Add credentials for this employer in Profile, or sign in manually, then resume."
        email = self.page.locator('input[type="email"]:visible,input[autocomplete="username"]:visible,input[autocomplete="email"]:visible')
        if await email.count() != 1:
            return "Cannot identify a unique account email field; complete authentication manually."
        await email.fill(credential["username"])
        for control in await self.page.locator('input[type="password"]:visible').all():
            await control.fill(credential["password"])
        self.auth_attempted = True
        submit = self.page.locator('[data-automation-id="signInSubmitButton"]:visible') if stage == "sign_in" else self.page.locator('[data-automation-id="createAccountSubmitButton"]:visible')
        if await submit.count() == 1:
            if await submit.get_attribute("aria-hidden") == "true":
                submit = submit.locator("..").get_by_role("button", name="Sign In" if stage == "sign_in" else "Create Account", exact=True)
                if await submit.count() != 1:
                    return "Complete authentication manually; the authentication button is ambiguous."
            await submit.click()
        elif not await self.exact_action(("Create Account",) if stage == "create_account" else ("Sign In",)):
            return "Complete authentication manually; the authentication button is ambiguous."
        await self.page.wait_for_timeout(500)
        return ""

    async def advance(self):
        await self.wait_ready()
        before = await self.stage()
        if before == "review":
            return False
        if not await self.exact_action(NEXT_NAMES):
            return False
        for _ in range(30):
            await self.wait_ready()
            if await self.stage() != before:
                return True
            if await self.errors():
                return False
            await asyncio.sleep(.1)
        return False

    async def at_submit(self):
        self.assert_origin()
        return await self.submit_button().count() == 1

    def submit_button(self):
        root = self.page.locator(self.scan_root) if getattr(self, "scan_root", None) else self.page
        return root.get_by_role("button", name=re.compile(r"^Submit( Application)?$", re.I)).filter(visible=True)

    async def submit(self):
        self.assert_origin()
        await self.raise_for_site_error()
        button = self.submit_button()
        if await button.count() != 1 or not await button.is_enabled():
            raise RuntimeError("The final submission control is ambiguous or unavailable.")
        await button.click()

    async def submission_received(self):
        self.assert_origin()
        await self.raise_for_site_error()
        headings = await self.page.locator('h1:visible,h2:visible,[role="status"]:visible').all_text_contents()
        return any(re.fullmatch(r"(?:application (?:successfully )?submitted|thank you for applying[.!]?|your application has been (?:submitted|received)[.!]?)", text.strip(), re.I) for text in headings)

    async def audit_review(self, run, profile, answers):
        """Compare labeled summary values; unsupported summaries cannot claim verification."""
        from core.automation.answers import resolve
        summary = await self.page.evaluate('''() => {
          const result = [];
          for (const e of document.querySelectorAll('[data-intern-review], [data-automation-id="reviewField"], dl > dt')) {
            const label = e.getAttribute('data-label') || e.querySelector('label,dt')?.textContent || (e.tagName === 'DT' ? e.textContent : '');
            const value = e.getAttribute('data-value') ?? e.querySelector('[data-value],dd')?.textContent ?? (e.tagName === 'DT' ? e.nextElementSibling?.textContent : '');
            result.push({label: (label || '').trim(), value: (value || '').trim(),
              group: e.getAttribute('data-group') || '', row: Number(e.getAttribute('data-row') || 0)});
          }
          return result;
        }''')
        expected = [a for a in run.fields.values() if a.disposition == "verified" and a.section not in {"review", "sign_in", "create_account"}]
        if not expected:
            return "No verified application fields are available for final reconciliation."
        accounted = set()
        for assessment in expected:
            # Durable key: stage:group:row:label:radio-name:ordinal.
            parts = assessment.key.split(":", 3)
            group, row = parts[1], int(parts[2])
            f = FormField(key=assessment.key, label=assessment.label, selector="", kind="text", group=group, row=row, required=assessment.required)
            if assessment.answer_ref in {"profile:resume_path", "profile:cover_letter_path"}:
                f.kind = "file"
            answer = resolve(f, profile, run, answers)
            value = answer.value
            if assessment.answer_ref in {"profile:resume_path", "profile:cover_letter_path"}:
                value = Path(str(value)).name
            if isinstance(value, bool):
                accepted = {"yes", "true", "checked"} if value else {"no", "false", "unchecked"}
            else:
                accepted = {normalized(str(value))}
            candidates = [s for s in summary if normalized(s['label']) == normalized(assessment.label) and s['group'] == group and s['row'] == row]
            if len(candidates) != 1 or normalized(candidates[0]['value']) not in accepted:
                return f"Cannot independently reconcile '{assessment.label}' on this review layout. Return to its section to inspect the saved value. This tenant needs a review adapter before automatic verification can pass."
            accounted.add((normalized(assessment.label), group, row))
        for item in summary:
            identity = (normalized(item['label']), item['group'], item['row'])
            if identity not in accounted and item['value']:
                return f"The review contains an unverified field: '{item['label']}'. Return to its application section and resume verification."
        return ""
