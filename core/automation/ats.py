"""Shared conventional-form adapter for Greenhouse, Lever and Ashby hosted jobs.

Custom widgets and unrecognized layouts produce handoffs through the same engine.
"""
import hashlib

from core.automation.answers import resolve
from core.automation.models import ats_name, employer_key
from core.automation.workday import WorkdayAdapter


class HostedATSAdapter(WorkdayAdapter):
    inline_review = True

    def __init__(self, page, job_url, test_mode=False):
        super().__init__(page, job_url, test_mode)
        self.employer = employer_key(job_url)

    def assert_origin(self):
        super().assert_origin()
        if not self.test_mode and employer_key(self.page.url) != self.employer:
            raise RuntimeError("The page left the selected employer's application path. Inspect the redirect manually.")

    async def scan(self):
        self.assert_origin()
        # Scope writes to one identifiable application form, excluding newsletter/search forms.
        count = await self.page.evaluate('''() => {
          document.querySelectorAll('[data-intern-application-form]').forEach(e => e.removeAttribute('data-intern-application-form'));
          const roots = [...document.querySelectorAll('form,[role="form"],.ashby-application-form-container')]
            .filter(e => e.getClientRects().length)
            .filter(e => !e.parentElement.closest('form,[role="form"],.ashby-application-form-container'));
          const applications = roots.filter(e => e.querySelector('input[type="file"]') ||
            [...e.querySelectorAll('button,input[type="submit"]')].some(b => /^(submit application|apply|apply now)$/i.test((b.innerText || b.value || '').trim())));
          const candidates = applications.length ? applications : roots.length === 1 ? roots : [];
          if (candidates.length === 1) candidates[0].setAttribute('data-intern-application-form', '');
          return candidates.length;
        }''')
        if count != 1:
            return []
        self.scan_root = '[data-intern-application-form]'
        return await super().scan()

    async def coverage_problem(self):
        problem = await super().coverage_problem()
        if problem:
            return problem
        if await self.page.locator('[data-intern-application-form]').count() != 1:
            return "A unique application form could not be identified. Open the application form and resume."
        return ""

    async def stage(self):
        stage = await super().stage()
        if stage in {"verification", "sign_in", "create_account", "authentication"}:
            return stage
        fields = await self.scan()
        if not fields:
            if await self.at_submit():
                return "review"
            if await self.page.locator('input:not([type="hidden"]):visible,textarea:visible,select:visible').count():
                return "unrecognized_form"
            return "start"
        headings = await self.page.locator('h1:visible,h2:visible,[aria-current="step"]:visible').all_text_contents()
        signature = self.page.url + "|".join(headings) + "|".join(f.key for f in fields)
        return "form_" + hashlib.sha256(signature.encode()).hexdigest()[:12]

    async def audit_review(self, run, profile, answers):
        fields = await self.scan()
        if not fields:
            return await super().audit_review(run, profile, answers)
        # On single-page applications the editable form itself is the final review.
        if not await self.at_submit():
            return "No unique final submission button is visible. Review the form manually."
        for field in fields:
            assessment = run.fields.get(run.stage + ":" + field.key)
            answer = resolve(field, profile, run, answers)
            if not assessment or assessment.disposition not in {"verified", "intentionally_omitted"}:
                return f"Review contains an unverified field: {field.label}."
            if field.invalid or (answer.omit and field.value not in ("", False)) or (not answer.omit and (answer.value is None or not self.matches(field, answer.value))):
                return f"The review value changed for {field.label}; resume to verify it again."
        return ""


def adapter_for(page, job_url, test_mode=False):
    name = ats_name(job_url)
    if not name:
        raise ValueError("This site is tracking-only.")
    cls = WorkdayAdapter if name == "Workday" else HostedATSAdapter
    return cls(page, job_url, test_mode)
