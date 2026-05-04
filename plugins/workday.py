from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from core.browser.playwright_mgr import AsyncPlaywrightManager
from .base import ATSPluginInterface


class WorkdayPlugin(ATSPluginInterface):
    """Workday automation split into explicit phases."""

    @property
    def portal_name(self) -> str:
        return "Workday"

    @property
    def domain_matchers(self) -> List[str]:
        return ["myworkdayjobs.com", "myworkday.com"]

    async def detect_account_existence(self, page, profile: Dict[str, Any]) -> bool:
        return bool(profile.get("workday_credential_existed"))

    async def create_account(self, page, profile: Dict[str, Any]) -> bool:
        await self._fill_account_credentials(page, profile)
        await self._check_candidate_profile_consent(page)
        return await self._click_first_visible(page, [
            'button:has-text("Create Account")',
            '[data-automation-id="createAccountSubmitButton"]',
            '[data-automation-id="click_filter"]',
        ])

    async def apply_to_job(self, job_url: str, profile: Optional[Dict[str, Any]] = None, context: Any = None):
        profile = self._normalize_profile(profile)
        profile["workday_credential"] = self._credential_for_job(job_url, profile)
        phase = (context or {}).get("phase") or "phase_1_login"

        if phase not in {"phase_1_login", "phase_1_awaiting_activation"}:
            return self._result(
                True,
                "Needs Review",
                phase,
                "Phase 2 is not implemented yet. Browser automation stopped before form filling.",
            )

        browser_mgr = AsyncPlaywrightManager(headless=False)
        await browser_mgr.start()
        page = await browser_mgr.context.new_page()

        try:
            await page.goto(job_url, wait_until="networkidle")
            await self._open_application_start(page)
            await self._choose_autofill_with_resume(page)

            if profile.get("workday_credential_existed"):
                return await self._phase_1_sign_in(page, profile)

            return await self._phase_1_create_account(page, profile)
        except Exception as exc:
            return self._result(False, "Failed", phase, f"Phase 1 failed: {exc}")
        finally:
            await browser_mgr.stop()

    async def _phase_1_sign_in(self, page, profile: Dict[str, Any]):
        clicked = await self._click_first_visible(page, [
            '#mainContent button:has-text("Sign In")',
            'button:has-text("Sign In")',
            'a:has-text("Sign In")',
            '[data-automation-id*="signIn" i]',
        ])
        if clicked:
            await page.wait_for_timeout(1000)

        await self._fill_account_credentials(page, profile)
        await page.wait_for_timeout(500)
        signed_in = await self._submit_sign_in(page)

        if not signed_in:
            return self._result(
                False,
                "Failed",
                "phase_1_login",
                "Could not find the Workday sign-in button after filling credentials.",
            )

        await page.wait_for_timeout(1000)
        return self._result(
            True,
            "Needs Review",
            "phase_2_autofill_resume",
            "Phase 1 complete. Signed in with saved Workday credentials.",
        )

    async def _submit_sign_in(self, page) -> bool:
        try:
            sign_in = page.get_by_label("Sign In")
            if await sign_in.count() > 0:
                await sign_in.first.click()
                return True
        except Exception:
            pass

        try:
            sign_in_button = page.get_by_role("button", name="Sign In")
            if await sign_in_button.count() > 0:
                await sign_in_button.first.click()
                return True
        except Exception:
            pass

        clicked = await self._click_first_visible(page, [
            'button:has-text("Sign In")',
            '[role="button"]:has-text("Sign In")',
            'button:has-text("Log In")',
            '[role="button"]:has-text("Log In")',
            'button:has-text("Login")',
            '[role="button"]:has-text("Login")',
            'button[type="submit"]',
            '[data-automation-id*="signIn" i]',
            '[data-automation-id="click_filter"]',
        ])
        if clicked:
            return True

        password_fields = page.locator('input[type="password"]')
        count = await password_fields.count()
        for index in range(count):
            candidate = password_fields.nth(index)
            try:
                if await candidate.is_visible():
                    await candidate.press("Enter")
                    return True
            except Exception:
                continue
        return False

    async def _phase_1_create_account(self, page, profile: Dict[str, Any]):
        credential = profile.get("workday_credential", {})
        if not credential.get("username") or not credential.get("password"):
            return self._result(
                False,
                "Failed",
                "phase_1_login",
                "No generated Workday credential was available for account creation.",
            )

        created = await self.create_account(page, profile)
        if not created:
            return self._result(
                False,
                "Failed",
                "phase_1_login",
                "Could not submit the Workday create-account form.",
            )

        return self._result(
            False,
            "Awaiting Activation",
            "phase_1_awaiting_activation",
            "Account created. Confirm the email activation link, then press Resume.",
        )

    async def _open_application_start(self, page):
        clicked = await self._click_first_visible(page, [
            '[data-automation-id="applyNowButton"]',
            'button:has-text("Apply")',
            'a:has-text("Apply")',
        ])
        if clicked:
            await page.wait_for_load_state("networkidle")

    async def _choose_autofill_with_resume(self, page):
        await self._click_first_visible(page, [
            'button:has-text("Autofill with Resume")',
            'a:has-text("Autofill with Resume")',
            '[data-automation-id="autofillWithResume"]',
            '[data-automation-id="autofillWithResumeButton"]',
        ])
        await page.wait_for_load_state("networkidle")

    async def _fill_account_credentials(self, page, profile: Dict[str, Any]):
        credential = profile.get("workday_credential", {})
        username = credential.get("username", "")
        password = credential.get("password", "")

        if username:
            filled = await self._fill_accessible_textbox(page, "Email Address", username)
            if not filled:
                await self._fill_first_matching(page, [
                'input[type="email"]',
                'input[autocomplete="username"]',
                'input[data-automation-id="email"]',
                'input[data-automation-id*="email" i]',
                'input[data-automation-id*="user" i]',
                'input[name*="email" i]',
                'input[name*="user" i]',
                'input[id*="email" i]',
                'input[id*="user" i]',
                ], username)

        if password:
            filled = await self._fill_accessible_textbox(page, "Password", password)
            if not filled:
                await self._fill_all_matching(page, [
                    'input[type="password"]',
                    'input[data-automation-id*="password" i]',
                    'input[name*="password" i]',
                    'input[id*="password" i]',
                ], password)

    async def _fill_accessible_textbox(self, page, name: str, value: str) -> bool:
        try:
            textbox = page.get_by_role("textbox", name=name)
            count = await textbox.count()
            for index in range(count):
                candidate = textbox.nth(index)
                if await candidate.is_visible():
                    await candidate.fill(value)
                    return True
        except Exception:
            return False
        return False

    async def _check_candidate_profile_consent(self, page):
        checkbox = page.locator(
            'label:has-text("candidate profile") input[type="checkbox"], '
            'label:has-text("explicit consent") input[type="checkbox"], '
            'input[type="checkbox"]'
        )
        if await checkbox.count() > 0:
            await checkbox.first.check()
            return True
        return False

    async def _fill_first_matching(self, page, selectors: List[str], value: str) -> bool:
        for scope in await self._preferred_scopes(page):
            for selector in selectors:
                locator = scope.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if await candidate.is_visible():
                            await candidate.fill(value)
                            return True
                    except Exception:
                        continue
        return False

    async def _fill_all_matching(self, page, selectors: List[str], value: str) -> bool:
        filled = False
        for scope in await self._preferred_scopes(page):
            for selector in selectors:
                locator = scope.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if await candidate.is_visible():
                            await candidate.fill(value)
                            filled = True
                    except Exception:
                        continue
            if filled:
                return True
        return False

    async def _click_first_visible(self, page, selectors: List[str]) -> bool:
        for scope in await self._preferred_scopes(page):
            for selector in selectors:
                locator = scope.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if await candidate.is_visible():
                            await candidate.scroll_into_view_if_needed()
                            await candidate.click()
                            return True
                    except Exception:
                        continue
        return False

    async def _preferred_scopes(self, page):
        scopes = []
        dialogs = page.locator('[role="dialog"], [aria-modal="true"]')
        count = await dialogs.count()
        for index in range(count):
            dialog = dialogs.nth(index)
            try:
                if await dialog.is_visible():
                    scopes.append(dialog)
            except Exception:
                continue
        scopes.append(page)
        return scopes

    async def _get_clean_html(self, page) -> str:
        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "svg", "nav", "footer", "header", "noscript"]):
            tag.extract()
        return str(soup.find("form") or soup.find("main") or soup)

    async def _extract_fields(self, html: str, profile: Dict[str, Any]):
        from core.llm.field_mapper import extract_fields

        return await extract_fields(html, profile)

    async def _upload_resume_if_available(self, page, profile: Dict[str, Any]) -> bool:
        resume_path = profile.get("resume_path")
        if not resume_path:
            return False

        path = Path(resume_path)
        if not path.exists():
            return False

        file_inputs = page.locator("input[type='file']")
        if await file_inputs.count() == 0:
            return False

        await file_inputs.first.set_input_files(str(path))
        return True

    def _normalize_profile(self, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        defaults = {
            "first_name": "",
            "last_name": "",
            "email": "",
            "phone": "",
            "resume_path": "",
            "workday_site": "",
            "workday_credential": {},
            "workday_credentials": {},
            "workday_credential_existed": False,
        }
        if not profile:
            return defaults
        return {**defaults, **{key: value for key, value in profile.items() if value is not None}}

    def _credential_for_job(self, job_url: str, profile: Dict[str, Any]) -> Dict[str, str]:
        site = self._workday_site_key(job_url)
        credentials = profile.get("workday_credentials", {})
        normalized_credentials = {
            self._workday_site_key(key): value
            for key, value in credentials.items()
        }
        credential = normalized_credentials.get(site, {}) or profile.get("workday_credential", {})
        if credential:
            profile["workday_site"] = site
        return credential

    def _workday_site_key(self, job_url: str) -> str:
        if not job_url:
            return ""

        value = job_url.strip()
        if "://" not in value:
            value = f"https://{value}"

        parsed = urlparse(value)
        host = parsed.netloc.lower()
        if not host:
            host = value.lower().split("/")[0]
        return host.replace("www.", "")

    def _result(self, success: bool, status: str, phase: str, note: str):
        return {
            "success": success,
            "status": status,
            "phase": phase,
            "note": note,
        }
