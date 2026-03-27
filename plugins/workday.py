import asyncio
from bs4 import BeautifulSoup
from .base import ATSPluginInterface
from typing import Dict, Any, List
from core.browser.playwright_mgr import AsyncPlaywrightManager
from core.llm.field_mapper import extract_fields

class WorkdayPlugin(ATSPluginInterface):
    """A Workday automation module implementation."""
    
    @property
    def portal_name(self) -> str:
        return "Workday"

    @property
    def domain_matchers(self) -> List[str]:
        return ["myworkdayjobs.com", "myworkday.com"]

    async def _get_clean_html(self, page) -> str:
        """Extracts and strips the DOM to save massive LLM token counts."""
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        # Strip invisible and irrelevant structural tags
        for script in soup(["script", "style", "svg", "nav", "footer", "header", "noscript"]):
            script.extract()
        
        main_form = soup.find('form') or soup.find('main') or soup
        return str(main_form)

    async def detect_account_existence(self, page, profile: Dict[str, Any]) -> bool:
        print("[WorkdayPlugin] Checking for login wall...")
        # Workday typically asks for email first
        email_input = page.locator('input[type="email"], input[data-automation-id="email"]')
        if await email_input.count() > 0:
            await email_input.first.fill(profile.get("email", "dummy@example.com"))
            
            next_btn = page.locator('div[data-automation-id="click_filter"]') # "Next" wrapper
            if await next_btn.count() > 0:
                await next_btn.first.click()
                
            await page.wait_for_timeout(2000)
            
            # If it asks for password, account exists
            if await page.locator('input[type="password"]').count() > 0:
                print("[WorkdayPlugin] Account detected! Entering dummy password...")
                await page.locator('input[type="password"]').first.fill("Testing123!")
                await page.locator('div[data-automation-id="click_filter"]').first.click() # Sign in
                return True
            else:
                return False
        return False

    async def create_account(self, page, profile: Dict[str, Any]) -> bool:
        print("[WorkdayPlugin] Creating new Workday account...")
        create_btn = page.locator('div[data-automation-id="createAccountLink"]')
        if await create_btn.count() > 0:
            await create_btn.first.click()
            await page.wait_for_timeout(2000)
        
        # Use Gemini to map the registration form inputs
        html = await self._get_clean_html(page)
        mapping_result = await extract_fields(html, profile)
        
        for css_selector, value in mapping_result.mappings.items():
            try:
                await page.locator(css_selector).fill(str(value))
                await page.wait_for_timeout(150) # human delay cadence
            except Exception as e:
                print(f"[WorkdayPlugin] Failed to fill {css_selector}: {e}")
                
        # Accept terms
        checkbox = page.locator('input[type="checkbox"]')
        if await checkbox.count() > 0:
            await checkbox.first.check()
            
        submit = page.locator('div[data-automation-id="click_filter"]')
        if await submit.count() > 0:
            await submit.first.click()
            
        return True

    async def apply_to_job(self, job_url: str, profile: Dict[str, Any] = None, context: Any = None) -> bool:
        if profile is None:
            # Fallback mock data if the DB isn't wired to the job iteration
            profile = {
                "first_name": "John",
                "last_name": "Doe",
                "email": "johndoe@example.com",
                "phone": "555-0199"
            }
            
        print(f"[WorkdayPlugin] Intercepting Workday Portal: {job_url}")
        
        # 1. Initialize Browser Visually so the user can verify
        browser_mgr = AsyncPlaywrightManager(headless=False)
        await browser_mgr.start()
        
        # Note: We use browser_mgr.context.new_page() dynamically via persistent contexts
        page = await browser_mgr.context.new_page()
        
        try:
            # 2. Navigate
            print("[WorkdayPlugin] Routing to Network Idle...")
            await page.goto(job_url, wait_until="networkidle")
            
            # 3. Aggressive Workday Apply Button Locators
            apply_btn = page.locator('[data-automation-id="applyNowButton"], a:has-text("Apply")').first
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await page.wait_for_load_state("networkidle")
            
            # 4. Handle Auth (Check for 'Apply Manually' shortcut first)
            manual_apply = page.locator('[data-automation-id="applyManually"]')
            if await manual_apply.count() > 0:
                await manual_apply.first.click()
                await page.wait_for_load_state("networkidle")
                
            exists = await self.detect_account_existence(page, profile)
            if not exists:
                await self.create_account(page, profile)
                
            # 5. Iterative Pydantic AI Form Mapping (Paginated Forms)
            for step in range(5):
                print(f"[WorkdayPlugin] 🧠 Processing Application Screen {step+1} via LLM...")
                await page.wait_for_timeout(3000)
                html = await self._get_clean_html(page)
                
                # Yield to Gemini for form inferences
                mapping_result = await extract_fields(html, profile)
                if not mapping_result.mappings:
                    print("[WorkdayPlugin] LLM identified 0 dynamic fields. Trying to advance...")
                else:
                    for css_selector, value in mapping_result.mappings.items():
                        try:
                            loc = page.locator(css_selector).first
                            if await loc.is_visible():
                                await loc.fill(str(value))
                                await page.wait_for_timeout(250)
                        except Exception:
                            pass
                            
                # 6. Click Next or Save and Continue
                next_btn = page.locator('[data-automation-id="bottom-navigation-next-button"], button:has-text("Save and Continue")')
                if await next_btn.count() > 0:
                    await next_btn.first.click()
                else:
                    submit_btn = page.locator('button:has-text("Submit")')
                    if await submit_btn.count() > 0:
                        print("\n[WorkdayPlugin] 🚀 REASONING HALTED. Reached final Review/Submit Screen.")
                        print("[WorkdayPlugin] Browser paused internally for manual user validation! Close the browser window to end.")
                        await page.pause() # Freezes execution in Playwright Debugger
                        break
                        
        except Exception as e:
            print(f"[WorkdayPlugin] Fatal Frame Exception: {e}")
        finally:
            await browser_mgr.stop()
            
        return True
