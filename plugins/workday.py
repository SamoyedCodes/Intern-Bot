from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from core.browser.playwright_mgr import AsyncPlaywrightManager
from .base import ATSPluginInterface
from .workday_selectors import (
    CREATE_ACCOUNT, SIGN_IN_NAVIGATION, SIGN_IN_SUBMIT,
    APPLY_NOW, AUTOFILL_RESUME, CONTINUE, EMAIL_INPUT, PASSWORD_INPUT,
    APP_QUESTIONS_PAGE, SIGN_IN_PAGE, CONSENT_CHECKBOX,
    PROFILE_FIELDS, EXPERIENCE_FIELDS,
    CREATE_ACCOUNT_PAGE, SIGN_IN_LINK,
)


class WorkdayPlugin(ATSPluginInterface):
    """Workday automation split into explicit phases."""

    PHASE_1 = {"phase_1_login", "phase_1_awaiting_activation"}
    PHASE_2 = {
        "phase_2_autofill_resume",
        "phase_2_my_information",
        "phase_2_my_experience",
    }
    MANUAL_QUESTIONS_PHASE = "phase_3_application_questions_manual"

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
        return await self._click_first_visible(page, CREATE_ACCOUNT)

    async def apply_to_job(self, job_url: str, profile: Optional[Dict[str, Any]] = None, context: Any = None):
        profile = self._normalize_profile(profile)
        profile["workday_credential"] = self._credential_for_job(job_url, profile)
        phase = (context or {}).get("phase") or "phase_1_login"
        keep_browser_open = False

        browser_mgr = AsyncPlaywrightManager(headless=False)
        await browser_mgr.start()
        page = await browser_mgr.context.new_page()

        try:
            await page.goto(job_url, wait_until="networkidle")
            await self._open_application_start(page)
            await self._choose_autofill_with_resume(page)

            if phase in self.PHASE_1:
                if profile.get("workday_credential_existed"):
                    result = await self._phase_1_sign_in(page, profile)
                    keep_browser_open = self._should_keep_browser_open(result)
                    return result

                result = await self._phase_1_create_account(page, profile)
                keep_browser_open = self._should_keep_browser_open(result)
                return result

            if phase in self.PHASE_2 or phase == self.MANUAL_QUESTIONS_PHASE:
                result = await self._run_phase_2_until_questions(page, profile, phase)
                keep_browser_open = self._should_keep_browser_open(result)
                return result

            return self._result(False, "Failed", phase, f"Unknown Workday phase: {phase}")
        except Exception as exc:
            result = self._result(False, "Failed", phase, f"Workday automation failed: {exc}")
            keep_browser_open = self._should_keep_browser_open(result)
            return result
        finally:
            if not keep_browser_open:
                await browser_mgr.stop()

    async def _phase_1_sign_in(self, page, profile: Dict[str, Any]):
        # If we landed on the combined Create Account/Sign In page,
        # explicitly navigate to the Sign In section before filling credentials.
        if await self._is_create_account_page(page):
            clicked = await self._click_first_visible(page, SIGN_IN_LINK)
            if clicked:
                # Wait for the Create Account form to leave the DOM / become hidden
                try:
                    await page.wait_for_function(
                        "!document.querySelector('h2, h1') || "
                        "![...document.querySelectorAll('h2, h1')]"
                        ".some(el => el.textContent.includes('Create Account') && el.offsetParent !== null)",
                        timeout=5000,
                    )
                except Exception:
                    await page.wait_for_timeout(1500)
            else:
                # No dedicated sign-in link found; fall through and fill whatever is visible
                await page.wait_for_timeout(500)
        else:
            # Not a create-account page; try clicking a general Sign In nav item
            clicked = await self._click_first_visible(page, SIGN_IN_NAVIGATION)
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

        await self._wait_after_sign_in(page)
        return await self._run_phase_2_until_questions(page, profile, "phase_2_autofill_resume")

    async def _is_create_account_page(self, page) -> bool:
        for selector in CREATE_ACCOUNT_PAGE:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count):
                    if await locator.nth(index).is_visible():
                        return True
            except Exception:
                continue
        return False

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

        clicked = await self._click_first_visible(page, SIGN_IN_SUBMIT)
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
            True,
            "Needs Review",
            "phase_1_awaiting_activation",
            "Account created. Confirm the email activation link, then press Resume.",
        )

    async def _run_phase_2_until_questions(self, page, profile: Dict[str, Any], phase: str):
        sign_in_was_required = await self._is_sign_in_page(page)
        if not await self._ensure_signed_in_for_phase_2(page, profile):
            return self._result(
                False,
                "Failed",
                "phase_1_login",
                "Workday showed a sign-in page, but Intern-Bot could not sign in with the saved Workday credential.",
            )
        if sign_in_was_required:
            phase = "phase_2_autofill_resume"

        if await self._is_application_questions_page(page):
            return self._manual_questions_result()

        if phase in {"phase_2_autofill_resume", self.MANUAL_QUESTIONS_PHASE}:
            await self._upload_resume_if_available(page, profile)
            if not await self._click_continue(page):
                return self._result(
                    True,
                    "Manual Required",
                    "phase_2_autofill_resume",
                    "Resume step is open, but Intern-Bot could not find Continue. Review the browser manually.",
                )
            await self._wait_for_page_settle(page)
            if not await self._ensure_signed_in_for_phase_2(page, profile):
                return self._result(
                    False,
                    "Failed",
                    "phase_1_login",
                    "Workday returned to sign-in during Phase 2, and saved credential sign-in failed.",
                )
            if await self._is_application_questions_page(page):
                return self._manual_questions_result()
            phase = "phase_2_my_information"

        if phase == "phase_2_my_information":
            if await self._is_sign_in_page(page):
                return self._result(
                    False,
                    "Failed",
                    "phase_1_login",
                    "Workday is still on the sign-in page, so profile fields were not filled.",
                )
            await self._fill_profile_gaps(page, profile)
            await self._apply_llm_field_mapping(page, profile)
            if not await self._click_continue(page):
                return self._result(
                    True,
                    "Manual Required",
                    "phase_2_my_information",
                    "My Information is open, but Intern-Bot could not find Continue. Review the browser manually.",
                )
            await self._wait_for_page_settle(page)
            if await self._is_application_questions_page(page):
                return self._manual_questions_result()
            phase = "phase_2_my_experience"

        if phase == "phase_2_my_experience":
            if await self._is_sign_in_page(page):
                return self._result(
                    False,
                    "Failed",
                    "phase_1_login",
                    "Workday is still on the sign-in page, so experience fields were not filled.",
                )
            await self._fill_experience_gaps(page, profile)
            await self._apply_llm_field_mapping(page, profile)
            if not await self._click_continue(page):
                return self._result(
                    True,
                    "Manual Required",
                    "phase_2_my_experience",
                    "My Experience is open, but Intern-Bot could not find Continue. Review the browser manually.",
                )
            await self._wait_for_page_settle(page)
            if await self._is_application_questions_page(page):
                return self._manual_questions_result()

        return self._result(
            True,
            "Manual Required",
            "phase_2_my_experience",
            "Phase 2 ran. Review the browser before continuing to company-specific questions.",
        )

    def _manual_questions_result(self):
        return self._result(
            True,
            "Manual Questions",
            self.MANUAL_QUESTIONS_PHASE,
            "Application Questions are company-specific. Complete this section manually in the open browser.",
        )

    def _should_keep_browser_open(self, result: Dict[str, Any]) -> bool:
        return result.get("status") in {"Needs Review", "Manual Required", "Manual Questions", "Failed"}

    async def _open_application_start(self, page):
        clicked = await self._click_first_visible(page, APPLY_NOW)
        if clicked:
            await page.wait_for_load_state("networkidle")

    async def _choose_autofill_with_resume(self, page):
        await self._click_first_visible(page, AUTOFILL_RESUME)
        await page.wait_for_load_state("networkidle")

    async def _click_continue(self, page) -> bool:
        return await self._click_first_visible(page, CONTINUE)

    async def _wait_for_page_settle(self, page):
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            await page.wait_for_timeout(1000)

    async def _wait_after_sign_in(self, page):
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            await page.wait_for_timeout(3000)

    async def _ensure_signed_in_for_phase_2(self, page, profile: Dict[str, Any]) -> bool:
        if not await self._is_sign_in_page(page):
            return True

        credential = profile.get("workday_credential", {})
        if not credential.get("username") or not credential.get("password"):
            return False

        await self._fill_account_credentials(page, profile)
        await page.wait_for_timeout(500)
        if not await self._submit_sign_in(page):
            return False

        await self._wait_after_sign_in(page)
        return not await self._is_sign_in_page(page)

    async def _fill_account_credentials(self, page, profile: Dict[str, Any]):
        credential = profile.get("workday_credential", {})
        username = credential.get("username", "")
        password = credential.get("password", "")

        if username:
            filled = await self._fill_accessible_textbox(page, "Email Address", username)
            if not filled:
                await self._fill_first_matching(page, EMAIL_INPUT, username)

        if password:
            filled = await self._fill_accessible_textbox(page, "Password", password)
            if not filled:
                await self._fill_all_matching(page, PASSWORD_INPUT, password)

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
        checkbox = page.locator(", ".join(CONSENT_CHECKBOX))
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

    async def _fill_empty_first_matching(self, page, selectors: List[str], value: str) -> bool:
        if not value:
            return False

        for scope in await self._preferred_scopes(page):
            for selector in selectors:
                locator = scope.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if await candidate.is_visible() and not await self._field_has_value(candidate):
                            await candidate.fill(value)
                            return True
                    except Exception:
                        continue
        return False

    async def _field_has_value(self, locator) -> bool:
        try:
            return bool((await locator.input_value()).strip())
        except Exception:
            pass

        try:
            return bool((await locator.text_content() or "").strip())
        except Exception:
            return False

    async def _fill_profile_gaps(self, page, profile: Dict[str, Any]) -> bool:
        if await self._is_sign_in_page(page):
            return False

        filled = False
        for key, selectors in PROFILE_FIELDS:
            if await self._fill_empty_first_matching(page, selectors, profile.get(key, "")):
                filled = True
        return filled

    async def _fill_experience_gaps(self, page, profile: Dict[str, Any]) -> bool:
        entries = profile.get("experience") or []
        if not entries:
            return False

        entry = entries[0]
        filled = False
        for key, selectors in EXPERIENCE_FIELDS:
            if await self._fill_empty_first_matching(page, selectors, entry.get(key, "")):
                filled = True
        return filled

    async def _apply_llm_field_mapping(self, page, profile: Dict[str, Any]) -> bool:
        try:
            html = await self._get_clean_html(page)
            mapping = await self._extract_fields(html, profile)
        except Exception:
            return False

        filled = False
        for selector, value in getattr(mapping, "mappings", {}).items():
            try:
                if await self._fill_empty_first_matching(page, [selector], value):
                    filled = True
            except Exception:
                continue
        return filled

    async def _is_application_questions_page(self, page) -> bool:
        for selector in APP_QUESTIONS_PAGE:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count):
                    if await locator.nth(index).is_visible():
                        return True
            except Exception:
                continue
        return False

    async def _is_sign_in_page(self, page) -> bool:
        for selector in SIGN_IN_PAGE:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count):
                    if await locator.nth(index).is_visible():
                        return True
            except Exception:
                continue
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
        count = await file_inputs.count()
        if count == 0:
            return False

        for index in range(count):
            candidate = file_inputs.nth(index)
            try:
                if await candidate.is_visible():
                    await candidate.set_input_files(str(path))
                    return True
            except Exception:
                continue

        await file_inputs.first.set_input_files(str(path))
        return True

    def _normalize_profile(self, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        defaults = {
            "first_name": "",
            "last_name": "",
            "email": "",
            "phone": "",
            "address": "",
            "resume_path": "",
            "linkedin_url": "",
            "github_url": "",
            "portfolio_url": "",
            "school": "",
            "degree": "",
            "major": "",
            "graduation": "",
            "experience": [],
            "default_answers": "",
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
