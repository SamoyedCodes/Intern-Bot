"""Opt-in acceptance check for an explicitly supplied local profile and resume.

INTERN_BOT_ACCEPTANCE_PROFILE=/path/profile.json python -m pytest -q tests/test_resume_acceptance.py
All browser requests are intercepted; the PDF never reaches an employer.
"""
import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from core.automation.engine import ApplicationEngine
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer
from core.automation.workday import WorkdayAdapter
from core.browser.playwright_mgr import AsyncPlaywrightManager
from core.storage.local_store import LocalStore


@pytest.mark.skipif(not os.environ.get('INTERN_BOT_ACCEPTANCE_PROFILE'), reason='An explicit local acceptance profile is required')
def test_supplied_resume_upload_pause_resume_and_final_review(tmp_path):
    profile = ApplicantProfile.model_validate_json(Path(os.environ['INTERN_BOT_ACCEPTANCE_PROFILE']).read_text())
    resume = Path(profile.resume_path)
    assert resume.is_file() and resume.read_bytes().startswith(b'%PDF-')
    assert profile.first_name and profile.last_name and profile.education and profile.experience
    url = 'https://fixture.wd1.myworkdayjobs.com/job/Intern_R1'
    fixture = (Path(__file__).parent / 'fixtures/workday.html').read_text()
    fixture = fixture.replace("input('Last Name','required')", "input('Last Name','required')+input('Email','type=\"email\" required')+input('Phone','type=\"tel\" required')")
    fixture = fixture.replace("input('Degree','required')", "input('Degree','required')+input('Major','required')+input('Start Date','required')+input('End Date','required')")
    fixture = fixture.replace("input('Job Title','required')", "input('Job Title','required')+input('Location','required')+input('Start Date','required')+input('End Date','required')+input('Description','required')")

    async def scenario():
        manager = AsyncPlaywrightManager(headless=True, browser=os.environ.get('INTERN_BOT_TEST_ENGINE', 'chromium'), user_data_dir=str(tmp_path / 'browser'))
        requests = []
        try:
            context = await manager.start()
            async def local_only(route):
                requests.append(route.request.url)
                if route.request.url == url and route.request.method == 'GET':
                    await route.fulfill(status=200, content_type='text/html', body=fixture)
                else:
                    await route.abort()
            await context.route('**/*', local_only)
            page = context.pages[0]
            await page.goto(url)
            store = LocalStore(tmp_path / 'acceptance.sqlite3')
            run = ApplicationRun(job_url=url, profile_snapshot=profile, auto_submit=False)
            adapter = WorkdayAdapter(page, url)
            engine = ApplicationEngine(store)
            def pause_after_upload(updated):
                if any(f.answer_ref == 'profile:resume_path' and f.disposition == 'verified' for f in updated.fields.values()):
                    engine.pause()
            engine.emit = pause_after_upload
            await engine.start(run, profile, adapter)
            assert run.status == 'needs_input' and run.stage == 'resume'
            files = await adapter.scan()
            uploaded = next(f for f in files if f.kind == 'file')
            assert uploaded.file_digest == hashlib.sha256(resume.read_bytes()).hexdigest()
            assert uploaded.value == resume.name
            assert run.resume_digest == uploaded.file_digest

            await ApplicationEngine(store).resume(store.get_run(run.id), profile, adapter)
            restored = store.get_run(run.id)
            assert restored.stage == 'questions' and restored.status == 'needs_input'
            assert any(i.question == 'Available for this internship?' for i in restored.interventions)
            # Fictional fixture answer only; the sample resume does not establish availability.
            store.save_answer(ApprovedAnswer(question='Available for this internship?', value=False, scope_key=run.id))
            await ApplicationEngine(store).resume(restored, profile, adapter)
            final = LocalStore(store.path).get_run(run.id)
            assert final.status == 'ready_for_review', final.interventions
            assert all(f.disposition == 'verified' for f in final.fields.values())
            summary = await page.locator('[data-intern-review]').evaluate_all("els => els.map(e => ({label:e.dataset.label,value:e.dataset.value,group:e.dataset.group,row:Number(e.dataset.row)}))")
            def value(label, group='', row=0):
                matches = [item['value'] for item in summary if item['label'] == label and item['group'] == group and item['row'] == row]
                assert len(matches) == 1
                return matches[0]
            assert value('Resume') == resume.name
            assert value('First Name') == profile.first_name
            assert value('Last Name') == profile.last_name
            assert value('Email') == profile.email
            assert value('Phone') == profile.phone
            assert value('Country') == profile.country
            for row, entry in enumerate(profile.education):
                for label, key in [('School','school'), ('Degree','degree'), ('Major','major'), ('Start Date','start_date'), ('End Date','end_date')]:
                    assert value(label, 'education', row) == getattr(entry, key)
            for row, entry in enumerate(profile.experience):
                for label, key in [('Company','employer'), ('Job Title','job_title'), ('Location','location'), ('Start Date','start_date'), ('End Date','end_date'), ('Description','description')]:
                    assert value(label, 'experience', row) == getattr(entry, key)
            assert not final.submission_attempted and not final.is_submitted
            assert await page.evaluate('window.submissions') == 0
            assert requests == [url], 'Unexpected browser request attempted'
            await page.screenshot(path=str(tmp_path / 'resume-final-review.png'), full_page=True)
        finally:
            await manager.stop()
    asyncio.run(scenario())
