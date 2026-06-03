import re
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
    REVIEW_SUBMIT_PAGE,
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
    MANUAL_REVIEW_PHASE = "phase_3_review_submit_manual"

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
        profile["workday_credential_existed"] = bool(profile["workday_credential"])
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
                    if not await self._is_sign_in_page(page):
                        # Session still active — already past sign-in, go straight to phase 2.
                        result = await self._run_phase_2_until_questions(
                            page, profile, "phase_2_autofill_resume", already_signed_in=True
                        )
                    else:
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
            clicked = await self._click_in_flow_sign_in(page)
            if not clicked:
                clicked = await self._click_first_visible(page, SIGN_IN_LINK)
            if clicked:
                sign_in_panel = await self._wait_for_sign_in_panel(page)
            else:
                await page.wait_for_timeout(500)
                sign_in_panel = None
        else:
            clicked = await self._click_first_visible(page, SIGN_IN_NAVIGATION)
            if clicked:
                sign_in_panel = await self._wait_for_sign_in_panel(page)
            else:
                sign_in_panel = None

        await self._fill_account_credentials(page, profile, scope_override=sign_in_panel)
        await page.wait_for_timeout(500)
        signed_in = await self._submit_sign_in(page, scope=sign_in_panel)

        if not signed_in:
            return self._result(
                False,
                "Failed",
                "phase_1_login",
                "Could not find the Workday sign-in button after filling credentials.",
            )

        await self._wait_after_sign_in(page)
        return await self._run_phase_2_until_questions(page, profile, "phase_2_autofill_resume", already_signed_in=True)

    async def _click_in_flow_sign_in(self, page) -> bool:
        """Click the application-flow Sign In control, not the header nav link."""
        containers = ["#mainContent", "main", '[data-automation-id="createAccountPanel"]']
        for container_selector in containers:
            try:
                container = page.locator(container_selector)
                if await container.count() == 0:
                    continue
                button = container.first.get_by_role("button", name="Sign In")
                for index in range(await button.count()):
                    candidate = button.nth(index)
                    if await candidate.is_visible():
                        await candidate.click()
                        return True
            except Exception:
                continue

            try:
                link = container.first.get_by_role("link", name="Sign In")
                for index in range(await link.count()):
                    candidate = link.nth(index)
                    if await candidate.is_visible():
                        await candidate.click()
                        return True
            except Exception:
                continue
        return False

    async def _wait_for_sign_in_panel(self, page):
        """Wait for a visible 'Sign In' heading, then return its nearest
        container that also holds a password field.  This avoids relying on
        ARIA dialog attributes which many Workday tenants omit."""
        sign_in_heading_selectors = [
            'h1:has-text("Sign In")',
            'h2:has-text("Sign In")',
            'h3:has-text("Sign In")',
            '[data-automation-id*="signIn" i]',
        ]
        # Wait until at least one "Sign In" heading becomes visible.
        for selector in sign_in_heading_selectors:
            try:
                await page.wait_for_selector(selector, state="visible", timeout=8000)
                break
            except Exception:
                continue
        else:
            await page.wait_for_timeout(2000)
            return None

        # Walk up from the heading to find the enclosing panel that also
        # contains a password field — that panel is what we scope fills to.
        for selector in sign_in_heading_selectors:
            try:
                headings = page.locator(selector)
                for i in range(await headings.count()):
                    heading = headings.nth(i)
                    if not await heading.is_visible():
                        continue
                    # Check ancestor containers up to 5 levels deep.
                    ancestor = heading.locator("xpath=..")
                    for _ in range(5):
                        pw_field = ancestor.locator('input[type="password"]')
                        if await pw_field.count() > 0 and await pw_field.first.is_visible():
                            return ancestor
                        ancestor = ancestor.locator("xpath=..")
            except Exception:
                continue
        return None

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

    async def _submit_sign_in(self, page, scope=None) -> bool:
        target = scope if scope is not None else page

        try:
            sign_in = target.get_by_label("Sign In")
            if await sign_in.count() > 0:
                await sign_in.first.click()
                return True
        except Exception:
            pass

        try:
            sign_in_button = target.get_by_role("button", name="Sign In")
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

    async def _run_phase_2_until_questions(self, page, profile: Dict[str, Any], phase: str, already_signed_in: bool = False):
        if not already_signed_in:
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

        stop = await self._check_stop_page(page)
        if stop:
            return stop

        if phase == "phase_2_autofill_resume":
            resume_error = await self._upload_resume_if_available(page, profile)
            if resume_error:
                return self._result(
                    False,
                    "Manual Required",
                    "phase_2_autofill_resume",
                    resume_error,
                )
            # Wait for Workday to finish server-side resume parsing before
            # clicking Continue — clicking too fast triggers "Something went wrong".
            await page.wait_for_timeout(3000)
            await self._wait_for_page_settle(page)
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
            stop = await self._check_stop_page(page)
            if stop:
                return stop
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
            llm_error = await self._apply_llm_field_mapping(page, profile)
            if not await self._click_continue(page):
                note = "My Information is open, but Intern-Bot could not find Continue. Review the browser manually."
                if llm_error:
                    note += f" (LLM mapping skipped: {llm_error})"
                return self._result(True, "Manual Required", "phase_2_my_information", note)
            await self._wait_for_page_settle(page)
            if await self._has_validation_error(page):
                return self._result(
                    True,
                    "Manual Required",
                    "phase_2_my_information",
                    "Workday showed validation errors (e.g., missing required fields like Country/Region). Please fix them manually in the browser, then click Continue and press Resume."
                )
            stop = await self._check_stop_page(page)
            if stop:
                return stop
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
            llm_error = await self._apply_llm_field_mapping(page, profile)
            if not await self._click_continue(page):
                note = "My Experience is open, but Intern-Bot could not find Continue. Review the browser manually."
                if llm_error:
                    note += f" (LLM mapping skipped: {llm_error})"
                return self._result(True, "Manual Required", "phase_2_my_experience", note)
            await self._wait_for_page_settle(page)
            if await self._has_validation_error(page):
                return self._result(
                    True,
                    "Manual Required",
                    "phase_2_my_experience",
                    "Workday showed validation errors. Please fix them manually in the browser, then click Continue and press Resume."
                )
            stop = await self._check_stop_page(page)
            if stop:
                return stop

        return self._result(
            True,
            "Manual Required",
            "phase_2_my_experience",
            "Phase 2 completed. Review the browser and continue with any remaining steps manually.",
        )

    def _manual_questions_result(self):
        return self._result(
            True,
            "Manual Questions",
            self.MANUAL_QUESTIONS_PHASE,
            "Application Questions are company-specific. Complete this section manually in the open browser.",
        )

    def _review_submit_result(self):
        return self._result(
            True,
            "Manual Review",
            self.MANUAL_REVIEW_PHASE,
            "Application is at the Review/Submit stage. Check all fields in the browser and submit manually.",
        )

    async def _check_stop_page(self, page):
        if await self._is_application_questions_page(page):
            return self._manual_questions_result()
        if await self._is_review_or_submit_page(page):
            return self._review_submit_result()
        return None

    async def _has_validation_error(self, page) -> bool:
        error_selectors = [
            '[data-automation-id="error-message"]',
            '[data-automation-id="errorBanner"]',
            '[data-automation-id="pageError"]',
            '.workday-error-banner',
            'div[role="alert"]',
        ]
        for scope in await self._preferred_scopes(page):
            for selector in error_selectors:
                locator = scope.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if await candidate.is_visible():
                            return True
                    except Exception:
                        continue
        return False

    def _should_keep_browser_open(self, result: Dict[str, Any]) -> bool:
        return result.get("status") in {"Needs Review", "Manual Required", "Manual Questions", "Manual Review", "Failed"}

    async def _open_application_start(self, page):
        clicked = await self._click_first_visible(page, APPLY_NOW)
        if clicked:
            await page.wait_for_load_state("networkidle")

    async def _choose_autofill_with_resume(self, page):
        await self._click_first_visible(page, AUTOFILL_RESUME)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            await page.wait_for_timeout(1000)

    async def _click_continue(self, page) -> bool:
        await page.wait_for_timeout(500)

        # Primary: use accessible role-based selectors (from Playwright codegen)
        continue_names = ["Continue", "Save and Continue", "Save & Continue", "Next"]
        for name in continue_names:
            try:
                btn = page.get_by_role("button", name=name)
                if await btn.count() > 0 and await btn.first.is_visible():
                    await btn.first.click()
                    return True
            except Exception:
                continue

        # Fallback: CSS selectors
        if await self._click_first_visible(page, CONTINUE):
            return True

        # The button may be in a sticky footer or off-screen — scroll to
        # the bottom of the page and retry once.
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)
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

    async def _fill_account_credentials(self, page, profile: Dict[str, Any], scope_override=None):
        credential = profile.get("workday_credential", {})
        username = credential.get("username", "")
        password = credential.get("password", "")

        if scope_override is not None:
            scopes = [scope_override, page]
        else:
            scopes = await self._preferred_scopes(page)

        if username:
            filled = await self._fill_accessible_textbox(scopes, "Email Address", username)
            if not filled:
                await self._fill_first_matching(page, EMAIL_INPUT, username)

        if password:
            filled = await self._fill_accessible_textbox(scopes, "Password", password)
            if not filled:
                await self._fill_all_matching(page, PASSWORD_INPUT, password)

    async def _fill_accessible_textbox(self, scopes, name: str, value: str) -> bool:
        for scope in scopes:
            try:
                textbox = scope.get_by_role("textbox", name=name)
                count = await textbox.count()
                for index in range(count):
                    candidate = textbox.nth(index)
                    if await candidate.is_visible():
                        await candidate.fill(value)
                        return True
            except Exception:
                continue
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

    async def _apply_llm_field_mapping(self, page, profile: Dict[str, Any]) -> Optional[str]:
        """Returns None on success, or an error string if LLM mapping was skipped."""
        try:
            html = await self._get_clean_html(page)
            mapping = await self._extract_fields(html, profile)
        except Exception as exc:
            return str(exc)

        for selector, value in getattr(mapping, "mappings", {}).items():
            try:
                await self._fill_empty_first_matching(page, [selector], value)
            except Exception:
                continue
        return None

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

    async def _is_review_or_submit_page(self, page) -> bool:
        for selector in REVIEW_SUBMIT_PAGE:
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
        # Require both a visible password field AND a visible sign-in trigger.
        # A nav-bar "Sign In" button that persists after login must not match alone.
        password_selectors = [
            'input[type="password"]',
            'input[data-automation-id*="password" i]',
        ]
        trigger_selectors = [
            'button:has-text("Sign In")',
            '[role="button"]:has-text("Sign In")',
            'button:has-text("Log In")',
            '[data-automation-id*="signIn" i]',
            'input[type="email"]',
            'input[autocomplete="username"]',
        ]

        has_password = False
        for selector in password_selectors:
            try:
                locator = page.locator(selector)
                for index in range(await locator.count()):
                    if await locator.nth(index).is_visible():
                        has_password = True
                        break
            except Exception:
                continue
            if has_password:
                break

        if not has_password:
            return False

        for selector in trigger_selectors:
            try:
                locator = page.locator(selector)
                for index in range(await locator.count()):
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
        dialogs = page.locator(
            '[role="dialog"], [aria-modal="true"], '
            '[data-automation-id*="dialog" i], [data-automation-id*="popup" i], '
            '[data-automation-id*="modal" i], div.workday-dialog'
        )
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

    async def _upload_resume_if_available(self, page, profile: Dict[str, Any]) -> Optional[str]:
        """Returns None on success or when upload is not currently required.
        Returns an error string when Workday is asking for a resume and the
        configured file cannot be uploaded."""
        resume_path = profile.get("resume_path")
        is_upload_page = await self._is_resume_upload_page(page)

        if not resume_path:
            if is_upload_page:
                return (
                    "Resume upload is required, but no resume path is configured. "
                    "Add your resume file path in Profile > Applicant > Resume, then resume this task."
                )
            return None

        path = Path(resume_path)
        if not path.exists():
            return (
                f"Resume file not found: '{resume_path}'. "
                "Update the path in Profile > Applicant > Resume, then resume this task."
            )

        if not is_upload_page:
            is_upload_page = await self._wait_for_resume_upload_page(page)
            if not is_upload_page:
                return None

        # Primary: follow the Workday codegen flow:
        # page.get_by_role("button", name="Select file").set_input_files(...)
        upload_button = await self._find_resume_upload_button(page)
        if upload_button is not None:
            try:
                await upload_button.set_input_files(str(path))
                await page.wait_for_timeout(1500)
                return None
            except Exception:
                pass

            try:
                async with page.expect_file_chooser(timeout=5000) as fc_info:
                    await upload_button.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(str(path))
                await page.wait_for_timeout(1500)
                return None
            except Exception:
                pass

        # Fallback: direct <input type="file"> selectors.
        file_input_selectors = [
            "input[type='file']",
            'input[data-automation-id*="file" i]',
            'input[data-automation-id*="resume" i]',
            'input[data-automation-id*="upload" i]',
            'input[accept]',
        ]
        for sel in file_input_selectors:
            try:
                locator = page.locator(sel)
                count = await locator.count()
                if count > 0:
                    await locator.first.set_input_files(str(path))
                    await page.wait_for_timeout(1500)
                    return None
            except Exception:
                continue

        return (
            "Resume upload is required, but Intern-Bot could not find Workday's file input. "
            "Use Select file in the browser, then press Resume."
        )

    async def _find_resume_upload_button(self, page):
        button_names = [
            "Select file",
            "Browse",
            "Choose File",
            "Choose file",
            "Upload",
        ]
        scopes = await self._preferred_scopes(page)
        for scope in scopes:
            for name in button_names:
                try:
                    button = scope.get_by_role("button", name=name)
                    for index in range(await button.count()):
                        candidate = button.nth(index)
                        if await candidate.is_visible():
                            return candidate
                except Exception:
                    continue

                try:
                    button = scope.get_by_role("button", name=re.compile(name, re.I))
                    for index in range(await button.count()):
                        candidate = button.nth(index)
                        if await candidate.is_visible():
                            return candidate
                except Exception:
                    continue

        selectors = [
            'button:has-text("Select file")',
            '[role="button"]:has-text("Select file")',
            'button:has-text("Browse")',
            '[role="button"]:has-text("Browse")',
            'button:has-text("Choose File")',
            '[role="button"]:has-text("Choose File")',
            'button:has-text("Upload")',
            '[role="button"]:has-text("Upload")',
            'label:has-text("Select file")',
            'label:has-text("Browse")',
        ]
        for scope in scopes:
            for selector in selectors:
                try:
                    locator = scope.locator(selector)
                    for index in range(await locator.count()):
                        candidate = locator.nth(index)
                        if await candidate.is_visible():
                            return candidate
                except Exception:
                    continue
        return None

    async def _wait_for_resume_upload_page(self, page, timeout_ms: int = 12000) -> bool:
        elapsed = 0
        interval = 500
        while elapsed <= timeout_ms:
            if await self._is_resume_upload_page(page):
                return True
            await page.wait_for_timeout(interval)
            elapsed += interval
        return False

    async def _is_resume_upload_page(self, page) -> bool:
        upload_selectors = [
            'text="Please upload your CV"',
            'text="Drop file here"',
            'text="Select file"',
            '[data-automation-id*="resume" i]',
            '[data-automation-id*="file" i]',
            '[data-automation-id*="upload" i]',
            "input[type='file']",
        ]
        for selector in upload_selectors:
            try:
                locator = page.locator(selector)
                for index in range(await locator.count()):
                    if await locator.nth(index).is_visible():
                        return True
            except Exception:
                continue
        return await self._find_resume_upload_button(page) is not None

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
