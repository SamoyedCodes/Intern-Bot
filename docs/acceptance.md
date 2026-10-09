> Historical record for the superseded engine. Current implementation and evidence: [local adapter acceptance](speedyapply-acceptance.md).

# Workday implementation and acceptance record

There is one application engine and one structured profile editor with named profiles. The app remains a preview: fictional fixtures do not establish reliability on live employers. The [SpeedyApply capability comparison](speedyapply-parity.md) describes the desktop additions and their boundaries.

| Plan milestone | Implemented software | Acceptance status |
| --- | --- | --- |
| One application | Versioned profile/run/field/intervention models; SQLite/keychain; deterministic completion loop; authentication handoffs; review reconciliation | Fictional complete flow tested. **One intended real application still required.** |
| Recovery | Bounded retries, value conflicts, explicit omissions, actual-page resume, persistent checkpoints, repeated-row reconciliation, profile locks, pause/cancel | Automated scenarios tested. Live session expiry and upload behavior remain to validate. |
| Employer coverage | Shared DOM adapter, scoped approved answers, conservative unknown-layout handoffs | **Five intended applications across three employer tenants pending.** No coverage claim. |
| Daily-use desktop | Single structured profile editor and application snapshots, resume picker, report, answer approval and answer-bank management | Offscreen desktop smoke tests. Live workflow usability pending. |
| Sequential queue | Queued/failed tasks run one at a time; duplicate identity checks; paused tasks remain; submission is a separate user-confirmed flag | Local queue and restart tests. Live multi-application queue pending. |

## Completed validation

Automated tests use fictional data and never submit real applications. Browser fixtures block all page network requests. The full fictional flow checks every exposed field and its final summary, multiple education and employment rows, and a conditional date question. Negative scenarios cover reverting values, unavailable uploads, unknown optional questions, conflicting parsed values, mismatching review summaries, validation errors, unrecognized embedded forms and repeated account attempts.

Storage tests check keychain-only credentials, ignored old JSON input, credential absence from SQLite, country/scope isolation and missing date components. GUI checks cover structured editing, answer approval/removal, duplicate task detection, restored interrupted states and sequential scheduling.

The AI recovery boundary was disabled then and has since been removed entirely; no AI recovery path exists, and nothing certifies a cloud/Browser Use integration.

## Live acceptance procedure

1. Use one job the user genuinely intends to apply to, with their locally entered approved profile and resume. Do not create dummy accounts or applications.
2. Record the employer/tenant and job identity locally. Add the job through **New application**.
3. Resolve unknown facts through explicit approvals. Record each intervention and whether it was missing information, verification, an interaction failure, or unsupported layout.
4. Compare every final answer, uploaded resume, repeated entry and intentional omission with the selected profile and approved answers. Stop before submission.
5. Exercise a recoverable interruption without duplicating entries. Confirm the saved draft is resumed, not a new application.
6. Record field coverage, answer correctness, intervention causes/count, elapsed active time and AI usage (currently zero). Do not call a run successful if a field or final summary remains unverified.
7. Repeat for five intended applications across at least three tenants. Add only adapters supported by those observations; convert each discovered failure into a fictional regression fixture.

No employer URLs or approved personal profile were supplied during implementation. No live acceptance gate has been marked complete and no real application has been submitted.

## Desktop capability additions — 2026-10-08

- Hosted Greenhouse, Lever and Ashby conventional forms reuse field resolution, browser read-back, bounded retries and explicit handoffs. Tests cover fictional forms only, not captured production DOMs.
- Final submit defaults to manual. An opt-in application can submit after verified review; a persisted attempt prevents a second automatic click, including after restart. Recognized receipt headings are required for automatic tracking.
- Named profiles preserve existing Default data and per-application snapshots. Approved answers are isolated by profile, country and employer tenant.
- Local pipeline/notes/activity, CSV import/export and optional context-previewed Gemini text assistance are covered by storage and desktop tests. Gemini responses are mocked; no provider request was made.
- Chromium: full suite passes. Installed Chrome: hosted autofill/upload, automatic receipt handling and persistent-profile locking pass in five targeted tests.
- Firefox: browser-selection code is implemented, but this host's downloaded Playwright Firefox fails to launch with macOS sandbox-extension errors. Firefox runtime acceptance remains pending; Chromium/Chrome are the validated choices here.

Every application fixture blocks network requests. A failed browser launch is not counted as an application compatibility result. The `INTERN_BOT_TEST_ENGINE` switch used for these runs was later removed when the app became Chromium-only.

## Supplied-resume check and live Workday discovery — 2026-10-08

**Result: local preparation passed; live end-to-end acceptance remains incomplete.**

The supplied `docs/resume.pdf` is a one-page document explicitly marked as fictional. Its facts were transcribed into an isolated acceptance profile under ignored `data/acceptance-2026-10-08/`; the normal applicant profile was not changed. Placeholder GitHub/LinkedIn URLs were omitted, projects were not presented as employment, and eligibility/availability were not inferred.

### Live portal

Opened [Keppel Data/AI Engineering internship, requisition 10016294](https://keppel.wd3.myworkdayjobs.com/en-US/KeppelCareers/job/Singapore/XMLNAME--Keppel-Internship-Programme-2027--Intern--Data-AI-Engineering--Jan---May-2027-_10016294) in an isolated installed-Chrome session. The actual engine traversed **Apply → Autofill with Resume → Create Account/Sign In**. The employer requires authentication and a terms acknowledgement before resume upload. No account was created, no fictional contact details were entered, and no resume or application was sent to Keppel.

Three issues observed on those public screens were fixed and given regression checks:

1. Workday's utility-bar language listbox was mistaken for an applicant field, preventing the initial Apply action. The scanner now excludes that utility bar while retaining application comboboxes.
2. A navigation could finish while `scan()` waited for requests, leaving the engine with a stale `start` stage. The engine now rechecks the stage before declaring that layout unsupported.
3. The live Create Account title is not an HTML heading recognized by the adapter. This unrecognized authentication state now requests manual authentication directly, rather than offering password questions in the approved-answer workflow.

The corrected live run, including a resume attempt, stopped at `needs_input / authentication` with one verification handoff and no credential answers. This establishes public navigation and handoff behavior only; employer parsing, persisted drafts and review reconciliation have **not** been validated live. A usable account and explicit answers are needed for those steps.

### Local supplied-PDF acceptance

The opt-in test `tests/test_resume_acceptance.py` uses the supplied PDF and structured sample profile with the actual persistent-browser manager, Workday adapter, application engine and SQLite checkpoints. Every browser request is intercepted locally; the fictional form is not a captured employer form. The test now runs against the Greenhouse fixture; the results below describe the original Workday run.

Verified: byte-for-byte SHA-256 upload read-back, pause after upload, restart of the engine from SQLite checkpoints, contact/education/employment field filling, a missing-answer handoff, local-only answer approval, final summary reconciliation, no duplicate rows, and zero submission attempts. The fictional availability answer is explicitly fixture-only and does not assert the sample applicant's real availability. The local final review contains 18 verified fields.

Reproduce from the project root after creating an explicit acceptance profile:

```sh
INTERN_BOT_ACCEPTANCE_PROFILE="$PWD/data/acceptance-2026-10-08/sample-profile.json" \
.venv/bin/python -m pytest -q tests/test_resume_acceptance.py
```

Without `INTERN_BOT_ACCEPTANCE_PROFILE`, the supplied-resume test skips rather than using personal documents implicitly. Local screenshots and the public-run result are under ignored `data/acceptance-2026-10-08/`. This test verifies a supplied upload plus pre-transcribed profile; it does not implement or validate automatic PDF-to-profile extraction.

Validation after these fixes: **43 tests passed** with the supplied-profile acceptance enabled in Chromium; the targeted supplied-PDF and utility-bar checks also passed in installed Chrome (**2 passed**). Source compilation and whitespace checks passed.

## Authenticated Keppel test — 2026-10-09

**Result: live upload, contact information, experience and application questions reached; final review remains unverified. No final submission or declaration acceptance.**

The user signed in directly and authorized local session retention and reuse. A saved browser state was restored into the same isolated Chrome profile and successfully reopened the application without another sign-in. The local harness, cookies and state are under ignored `data/acceptance-2026-10-08/`; the storage-state export is restricted to owner read/write (0600). Tokens are not stored in application answers or committed. The state is a credential-bearing file; it can expire or be revoked by Workday. The harness saves refreshed state on completion and shutdown. Session reuse was tested in Chrome only.

The engine uploaded the supplied PDF and observed Workday's successful-upload receipt. Live testing exposed and fixed these compatibility gaps:

- Unlabelled resume inputs now use the explicit resume container. When Workday replaces an input with an upload receipt, the adapter retains the digest of the exact bytes it sent and checks the receipt filename and success marker. Existing files in a fresh adapter have no such byte evidence and are not trusted merely by filename. Multiple uploaded items block verification.
- The active Workday progress step identifies the page after its file input disappears. A matching upload-success announcement is not treated as a validation error; genuine alerts still block progress.
- Listbox labels remain stable when selected text appears in their accessible names. Selected values in buttons and searchable prompt widgets are read back. Workday search prompts support their Enter-to-search action and exact leaf selection.
- The live page's accessible employment/education groups and required date legends are recognized. Western-script name labels and separately selected phone calling codes are handled.
- Questionnaire legends distinguish dropdown questions, and checkbox options retain their parent question instead of becoming generic “Yes”/“No” answers.

This was an assisted acceptance run, **not unattended completion**. The parser produced seven employment rows including projects and duplicates, and an incorrect education year. These were reconciled manually against the supplied structured sample. Parser conflicts, a placeholder social link and unsupported skill suggestions were corrected explicitly; the engine did not silently accept them. The portal's degree and major taxonomy equivalents were recorded for this run. The user explicitly supplied sample employment, phone type, language/proficiency, expected-class and vaccination answers. Optional omissions and all test answers are scoped to this isolated run. Career-aspiration text is a sample draft. The portal associates the draft with the signed-in account email, which differs from the fictional resume; it must not be treated as a fully reconciled real application.

After saving Application Questions, the browser displayed **Voluntary Disclosures (step 5 of 6)**. Its mandatory Confirm statement certifies the truth of the supplied information and authorizes background checks. Because the resume explicitly identifies its contents as fictional, Confirm was left unchecked and the test stopped before that declaration. Workday may retain the uploaded sample and saved draft on the signed-in account even though no application was submitted.

A pending-request timeout occurred while transitioning to Disclosures; the engine recorded `failed / questions` although the browser had reached the next screen. That live wait behavior remains unresolved. The diagnostic browser closed after the timeout, with session state saved. Production review reconciliation, declaration handling, submission/receipt behavior, and Firefox remain unverified in this live run. Use genuine applicant information before attempting the truthfulness declaration.

Validation: **50 tests passed** in the full suite with the supplied-PDF acceptance enabled. Source compilation passed. Final targeted Chrome checks passed **9 tests**, covering the new Workday controls and upload evidence. All automated fixtures use fictional data and block external requests.

To reopen the isolated test using its saved session, from the project root run:

```sh
.venv/bin/python data/acceptance-2026-10-08/live_session.py
```

The local harness exposes `status`, `inspect`, `save`, `resume` and `close`. Reopening does not itself resume autofill or accept any declaration. `resume` re-verifies the current page and retains the existing manual-handoff rules; unknown remote uploads may need explicit re-verification after restart. Do not use the sample profile for a final submission.
