from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path

from core.automation.answers import resolve
from core.automation.models import FieldAssessment, InterventionRequest, normalized, now
from core.automation.privacy import BoundedRecovery, configure_privacy
from core.automation.workday import WorkdayPageError


class ApplicationEngine:
    def __init__(self, store, emit=None):
        configure_privacy()
        self.store = store
        self.emit = emit or (lambda run: None)
        self.recovery = BoundedRecovery()
        self._pause = False
        self._cancel = False

    def pause(self):
        self._pause = True

    def cancel(self):
        self._cancel = True

    def checkpoint(self, run):
        self.store.save_run(run)
        self.emit(run.model_copy(deep=True))

    def intervene(self, run, message, kind="browser", field=None):
        run.status = "needs_input"
        run.intervention_count += 1
        request = InterventionRequest(kind=kind, message=message)
        if field:
            request.field_key = field.key
            request.question = field.label
            request.required = field.required
            request.options = field.options
        run.interventions.append(request)
        self.store.record_event(run.id, kind, run.stage, message)
        self.checkpoint(run)

    async def start(self, run, profile, adapter, credential=None):
        return await self.resume(run, profile, adapter, credential)

    async def resume(self, run, profile, adapter, credential=None):
        if run.is_submitted:
            return run
        self._pause = self._cancel = False
        started = time.monotonic()
        run.interventions = []
        run.status = "running"
        # A changed profile invalidates earlier evidence, but does not erase browser values.
        digest = ""
        if profile.resume_path:
            path = Path(profile.resume_path).expanduser()
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if run.profile_revision != profile.revision or run.resume_digest != digest:
            run.fields = {}
            run.completed_sections = []
        run.profile_revision = profile.revision
        run.profile_snapshot = profile.model_copy(deep=True)
        run.resume_digest = digest
        self.checkpoint(run)
        try:
            if run.submission_attempted:
                await self.confirm_submission(run, adapter)
                return run
            for _ in range(60):
                if self._cancel:
                    run.status = "cancelled"
                    return run
                if self._pause:
                    self.intervene(run, "Paused by you. Resume when ready.")
                    return run
                stage = await adapter.stage()
                run.stage = stage
                if stage in {"resume", "information", "experience", "questions", "disclosures", "review"} and run.authentication_attempted:
                    # A successful login ends the attempt guard; a later expired session can sign in once again.
                    run.authentication_attempted = False
                    adapter.auth_attempted = False
                if stage == "verification":
                    self.intervene(run, "Complete email verification, account activation or CAPTCHA in the browser, then resume.", "verification")
                    return run
                if stage == "authentication":
                    self.intervene(run, "Complete sign-in or account creation in the browser, then resume. This authentication layout is not recognized; credentials must not be added to the answer bank.", "verification")
                    return run
                if stage == "start":
                    if await adapter.scan():
                        # scan() waits for pending requests; navigation may have finished since stage().
                        if await adapter.stage() != stage:
                            continue
                        self.intervene(run, "This form layout is not recognized. No fields were skipped; inspect the browser.")
                        return run
                    if not await adapter.exact_action(("Autofill with Resume", "Apply Manually", "Apply", "Apply Now")):
                        self.intervene(run, "Open the application form in the browser, then resume.")
                        return run
                    await asyncio.sleep(.3)
                    continue
                if stage in {"sign_in", "create_account"}:
                    if stage == "create_account" and credential and await adapter.open_sign_in():
                        continue
                    # Consent and other noncredential questions still require explicit answers.
                    if not await self.complete_section(run, profile, adapter, authentication=True):
                        return run
                    if run.authentication_attempted:
                        self.intervene(run, "Authentication was already attempted for this application. Complete sign-in or activation manually, then resume.", "verification")
                        return run
                    if not credential or not credential.get("username") or not credential.get("password"):
                        self.intervene(run, "Add employer credentials in Profile or sign in manually, then resume.", "verification")
                        return run
                    run.authentication_attempted = True
                    self.checkpoint(run)
                    problem = await adapter.authenticate(credential or {}, stage)
                    if problem:
                        self.intervene(run, problem, "verification")
                        return run
                    continue
                if stage == "experience":
                    problem = await adapter.ensure_rows(profile)
                    if problem:
                        self.intervene(run, problem, "profile")
                        return run
                if not await self.complete_section(run, profile, adapter):
                    return run
                inline_review = adapter.inline_review and await adapter.at_submit()
                if stage == "review" or inline_review:
                    if not run.completed_sections and not inline_review:
                        self.intervene(run, "This application opened at review without verified checkpoints. Return to the first application section and resume.")
                        return run
                    problem = await adapter.audit_review(run, profile, self.store.answers())
                    if problem:
                        self.intervene(run, problem, "validation")
                        return run
                    run.status = "ready_for_review"
                    self.checkpoint(run)
                    if run.auto_submit and not self._pause and not self._cancel:
                        # Persist before clicking: a crash or ambiguous response must never cause a second submission.
                        run.submission_attempted = True
                        self.checkpoint(run)
                        if self._pause or self._cancel:
                            return run
                        await adapter.submit()
                        await self.confirm_submission(run, adapter)
                    return run
                if not run.auto_advance:
                    if stage not in run.completed_sections:
                        run.completed_sections.append(stage)
                    self.intervene(run, "Section verified. Continue in the browser, then resume to fill the next section.")
                    return run
                if not await adapter.advance():
                    self.intervene(run, "The section did not advance or shows validation errors. Correct the browser fields or profile and resume.", "validation")
                    return run
                if stage not in run.completed_sections:
                    run.completed_sections.append(stage)
                    self.store.record_event(run.id, "section_verified", stage)
                self.checkpoint(run)
            self.intervene(run, "The workflow exceeded its bounded step budget. Inspect the current page before resuming.")
        except asyncio.CancelledError:
            run.status = "needs_input" if self._pause else "cancelled"
            if self._pause:
                run.interventions = [InterventionRequest(kind="browser", message="Application interrupted. Reopen the saved draft and resume.")]
            raise
        except WorkdayPageError as exc:
            message = str(exc)
            if run.submission_attempted:
                message = "The site reported a page error after a submission attempt. Check the employer receipt before refreshing or taking further action; automatic resubmission is disabled."
            self.intervene(run, message)
        except Exception as exc:
            # Exception text can contain request data, HTML or credentials.
            run.status = "failed"
            suffix = "Check the employer receipt before any further action; submission was attempted." if run.submission_attempted else "Reopen or resume the application; no submission was attempted."
            run.interventions = [InterventionRequest(kind="browser", message=f"Browser operation failed ({type(exc).__name__}). {suffix}")]
        finally:
            if self._cancel:
                run.status = "cancelled"
            elif self._pause and run.status == "running":
                run.status = "needs_input"
                run.interventions = [InterventionRequest(kind="browser", message="Paused by you. Resume when ready.")]
            run.elapsed_seconds += time.monotonic() - started
            self.store.record_event(run.id, run.status, run.stage)
            self.checkpoint(run)
        return run

    async def confirm_submission(self, run, adapter):
        for _ in range(20):
            if await adapter.submission_received():
                run.submission_confirmed = True
                run.submitted_at = run.submitted_at or now()
                run.pipeline = "applied"
                run.status = "ready_for_review"
                self.store.record_event(run.id, "submission_confirmed", run.stage)
                return
            if await adapter.errors() or self._pause or self._cancel:
                break
            await asyncio.sleep(.25)
        self.intervene(run, "Submission was attempted once, but an employer receipt could not be verified. Inspect the browser; automatic resubmission is disabled.", "verification")

    async def complete_section(self, run, profile, adapter, authentication=False):
        answers = self.store.answers()
        attempts = {}
        # Rescan after every write and require two stable passes before navigation.
        stable = 0
        prior_keys = None
        visit_keys = set()
        for _ in range(200):
            if self._pause or self._cancel:
                return False
            coverage_problem = await adapter.coverage_problem()
            if coverage_problem:
                self.intervene(run, coverage_problem)
                return False
            fields = await adapter.scan()
            if authentication:
                fields = [f for f in fields if f.kind not in {"password", "email"} and normalized(f.label) not in {"email", "email address", "username"}]
            current_keys = {run.stage + ":" + f.key for f in fields}
            # Conditional fields removed by an answer are no longer applicable.
            for key in list(run.fields):
                if key in visit_keys and key not in current_keys:
                    del run.fields[key]
            visit_keys.update(current_keys)
            unresolved = []
            wrote = False
            for field in fields:
                key = run.stage + ":" + field.key
                resolution = resolve(field, profile, run, answers)
                assessment = FieldAssessment(key=key, label=field.label, section=run.stage,
                    required=field.required, answer_ref=resolution.ref, disposition="needs_input")
                if resolution.omit:
                    # Do not silently leave an existing unapproved value in an omitted field.
                    if field.value not in ("", False):
                        assessment.reason = "Clear this optional field before omitting it."
                    else:
                        assessment.disposition = "intentionally_omitted"
                        assessment.evidence = "Explicit approved omission"
                elif resolution.value is None:
                    assessment.reason = resolution.reason
                elif adapter.matches(field, resolution.value) and not field.invalid:
                    # For radios, at least one actual option must match the approved answer.
                    radio_options = [f for f in fields if f.label == field.label and f.group == field.group and f.row == field.row and f.kind == "radio"]
                    if field.kind == "radio" and not any(normalized(f.option) == normalized(str(resolution.value)) for f in radio_options):
                        assessment.reason = "The approved radio answer is not offered by this form."
                    else:
                        assessment.disposition = "verified"
                        assessment.evidence = "Exact upload payload digest and matching success receipt" if field.uploaded else "DOM read-back after blur; no field validation error"
                elif field.value not in ("", False) and field.kind != "radio" and not resolution.ref.startswith("answer:"):
                    assessment.reason = "Existing browser value conflicts with the profile. Correct the profile or explicitly approve the intended answer."
                else:
                    count = attempts.get(key, 0)
                    if count >= 3:
                        assessment.disposition = "blocked"
                        assessment.reason = "The value could not be verified after the initial attempt and two retries."
                    else:
                        attempts[key] = count + 1
                        assessment.attempts = count + 1
                        try:
                            await adapter.fill(field, resolution.value)
                        except WorkdayPageError:
                            raise
                        except Exception:
                            pass
                        wrote = True
                run.fields[key] = assessment
                if wrote:
                    break  # Handles and conditional structure can change after any write.
                if assessment.disposition in {"needs_input", "blocked"}:
                    unresolved.append((field, assessment))
            self.checkpoint(run)
            if wrote:
                stable = 0
                continue
            if unresolved:
                for field, assessment in unresolved:
                    self.intervene(run, assessment.reason, "conflict" if "conflict" in assessment.reason else "answer", field)
                return False
            if await adapter.errors():
                self.intervene(run, "The page still reports validation errors. Resolve them in the browser and resume.", "validation")
                return False
            stable = stable + 1 if prior_keys == current_keys else 0
            prior_keys = current_keys
            if stable >= 1:
                return True
            await asyncio.sleep(.25)
        self.intervene(run, "The form keeps changing or exceeds the section step budget; inspect it before resuming.")
        return False
