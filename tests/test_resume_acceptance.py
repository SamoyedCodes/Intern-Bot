"""Opt-in upload acceptance for an explicitly supplied local profile; all requests are intercepted."""
import hashlib
import os
from pathlib import Path

import pytest

from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer
from tests.support import greenhouse, open_fixture, resume_upload


@pytest.mark.skipif(not os.environ.get('INTERN_BOT_ACCEPTANCE_PROFILE'), reason='An explicit local acceptance profile is required')
async def test_supplied_resume_upload_pause_resume_and_final_review(context, store):
    profile = ApplicantProfile.model_validate_json(Path(os.environ['INTERN_BOT_ACCEPTANCE_PROFILE']).read_text())
    resume = Path(profile.resume_path)
    assert resume.is_file() and profile.first_name and profile.last_name and profile.email
    page = await open_fixture(context, 'greenhouse', greenhouse(extra=resume_upload() + '<label>Fictional availability<input type=checkbox required></label>'))
    run = ApplicationRun(job_url=page.url)
    bridge = ExtensionBridge(page, run.id)
    engine = ApplicationEngine(store)
    def pause_after_upload(updated):
        if any(f.answer_ref == 'profile:resume_path' and f.disposition == 'verified' for f in updated.fields.values()):
            engine.pause()
    engine.emit = pause_after_upload
    await engine.start(run, profile, bridge)
    assert run.status == 'needs_input' and not run.submission_attempted
    uploaded = next(f for f in (await bridge.command('scan'))['fields'] if f['kind'] == 'file')
    assert uploaded['file_digest'] == hashlib.sha256(resume.read_bytes()).hexdigest()
    assert uploaded['value'] == resume.name
    store.save_answer(ApprovedAnswer(question='Fictional availability', value=True, scope_key=run.id))
    restored = store.get_run(run.id)
    await ApplicationEngine(store).resume(restored, profile, bridge)
    assert restored.status == 'ready_for_review', restored.interventions
    assert all(f.disposition == 'verified' for f in restored.fields.values())
    assert not restored.submission_attempted and not restored.is_submitted
    assert not await page.evaluate('Boolean(window.submissions)')
