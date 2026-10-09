> Historical record for the superseded engine. Current implementation and evidence: [local adapter acceptance](speedyapply-acceptance.md).

# SpeedyApply-style capabilities in Intern-Bot

Implemented on 2026-10-08 using the existing desktop app, local store and Playwright engine. No SpeedyApply code, branding, extension package, account or service is used.

Reference: [SpeedyApply overview](https://www.speedyapply.com/), [profiles](https://docs.speedyapply.com/profile), [autofill](https://docs.speedyapply.com/autofill), [tracker](https://docs.speedyapply.com/application-tracker), [premium](https://docs.speedyapply.com/premium).

| Capability | Intern-Bot implementation | Boundary |
| --- | --- | --- |
| Profile and resume | Named profiles; explicit contact, skills, languages, EEO, education, experience, cover letter and resume fields; JSON import/export | Files remain local paths; JSON export does not embed attachments or credentials. |
| Multiple profiles | Active profile selector, save-as, profile selection on each new job | Existing application snapshots remain independent. Legacy profile and approvals belong to Default. |
| Saved responses | Exact normalized question match, per-profile application/employer/global scope and country context | Unknown facts and ambiguous answers require approval. Hosted ATS employers are scoped by tenant path, not shared hostname. |
| Application autofill | Existing Workday flow plus conventional hosted Greenhouse, Lever and Ashby forms; files, native selects, radio/checkbox, supported comboboxes and conditional fields | Preview, tested on fictional forms. Custom domains, iframe/shadow-root forms, unfamiliar widgets and generic repeated education/employment layouts require manual handoff. This is not 25+ ATS parity. |
| Browser choice | Bundled Chromium, installed Chrome, Playwright Firefox; isolated persistent sessions | Firefox needs Playwright's browser build, not the installed consumer Firefox. Desktop automation only; no installable extension or side panel. |
| Auto pilot | Sequential queue, optional automatic section continuation, per-application opt-in final submission | Submission only follows verified fields and review. The attempt is checkpointed before clicking and is never retried automatically. Only a recognized visible employer receipt marks it applied. CAPTCHA/verification remains manual. |
| Accounts | Existing Workday keychain credentials, catchall generation with a configurable address format, opt-in Workday account creation (once, recorded in the keychain before the click) with an email-verification handoff and one sign-in after you confirm | No mailbox access or automatic activation. Terms checkbox needs an approved answer. Other ATS sign-ins are manual. |
| Tracker and insights | Saved/applied/screen/interviewing/offer/rejected/archived pipeline, notes, job description, daily submission bars, current pipeline counts | Manual submission must be recorded by the user. Interview percentage describes the current interviewing/offer share, not historical interview conversion. |
| CSV | Import/export with common column aliases, duplicate URL checks, ISO dates, atomic import, spreadsheet-formula neutralization | Role and HTTPS job URL required. No arbitrary column-mapping UI. Duplicate identity ignores tracking parameters. |
| AI answers | Explicit Gemini draft action in Answer questions; editable context preview and consent per request | Drafts must be reviewed and saved as approved answers. The browser engine never requests or approves AI output. |
| AI profile scores | Compare saved profiles against a pasted job description via Gemini; scores, strengths and gaps | Advisory text only. Does not switch the application's profile automatically. API key/model access required; no live cloud call was made during validation. |
| Cloud sync / job alerts | Not included | State stays local. No account backend, third-party inbox access, Discord integration, or extension-store release. |

## Try it

1. In **Profile**, save your details, use **Save as new profile** for variations, and choose the active profile.
2. In **Settings**, choose the browser and continuation/answer defaults, then save them.
3. Create a **New application**, select a profile, and paste a supported hosted ATS URL. Other HTTPS jobs are tracking-only. Final submission defaults to manual; automatic submission requires explicit approval for that job.
4. Start/resume. Missing answers appear in **Answer questions**. Saved answers belong to that application's named profile.
5. Use the selected job's detail panel to record pipeline stage, notes and the job description. Totals appear under the Applications title; CSV import/export is in the ⋯ menu.
6. Optional: save your Gemini key and model in Settings. Use **Compare profiles with Gemini…**, or **Draft with Gemini…** from Answer questions. Review the exact outgoing context before consenting.

AI requests send only the context shown in that dialog. The default context includes career facts and job information, and excludes structured identity/contact/EEO fields, file contents, browser observations and credentials. User-entered career text can itself contain personal information; it remains editable before sending. Keys stay in the OS keychain. API requests use a fixed HTTPS endpoint, bounded input/output, no tools and no redirect following. Errors do not expose provider bodies or keys.

## Validation

The test suite uses fictional data and blocks page network requests. It covers hosted forms, uploads, defaults, approved-answer isolation, profile persistence, CSV validation and duplicate handling, explicit AI consent, bounded mocked provider calls, final-submit receipts and prevention of repeated submissions. Existing Workday regression tests remain in place.

Live employer acceptance and a live Gemini request have not been performed. Tests establish implementation behavior on the included fixtures, not universal compatibility with every employer deployment. See [the acceptance procedure](acceptance.md) before treating a tenant as validated.
