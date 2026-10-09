# Intern-Bot

A local Python/PySide6 desktop app for application profiles, autofill, exact approved answers, tracking, queues and optional Gemini text assistance. Its autofill engine runs all **28 site-specific SpeedyApply 2.28.0 adapters** inside a local Chromium extension, controlled directly through Playwright.

This is a private personal integration of proprietary user-supplied code. It is not an open-source release of SpeedyApply. Normal autofill requires no SpeedyApply account or server. See the [acceptance record](docs/speedyapply-acceptance.md) for fixture coverage, benchmarks and live-site limitations.

## Install and run (macOS)

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

The desktop loads the checked-in extension automatically into bundled Chromium. You do not install it in your regular browser. Playwright is pinned to 1.59.0 for MV3 worker-restart support. Node is needed only to rebuild the adapter package:

```sh
npm ci --prefix extension --ignore-scripts
npm run build --prefix extension
npm test --prefix extension
```

Existing Chrome/Firefox records and browser directories remain intact. Resuming opens a separate Chromium session and may require employer sign-in again. On first use, pending drafts lose old field-verification checkpoints and must be checked by the replacement engine. Historical applications and submission-attempt flags are preserved.

## Workflow

1. Open **Profile → Applicant details** and enter explicit contact facts, education, experience, language proficiency and optional employment eligibility. Unknown Boolean answers stay unknown. Choose a resume and optional cover letter. Documents retain their original bytes and file types.
2. Use named profiles for different applications. Existing profile JSON, education and experience rows, saved answers and tracker records remain available. Saving a main profile affects new applications; **Edit application profile** updates an existing application's snapshot.
3. Under **Workday credentials**, save/load employer credentials through the operating-system keychain. Recognized Workday authentication uses credentials only for that employer. CAPTCHA, activation and unfamiliar sign-in flows require manual completion.
4. In **Tasks → New application**, choose a profile and enter an HTTPS job URL. All 28 routing rules and the DOM-detected Phenom adapter are available. Other HTTPS pages can open for detection; unmatched pages remain manual. Ambiguous application frames require a handoff.
5. Use **Start / Resume** or **Start queue**. Queues run sequentially and skip submitted applications and jobs awaiting input/review. Pause/cancel stops subsequent adapter writes and pending timers/observers.
6. Resolve missing facts or conflicts in **Details / Answers**. Approvals match the exact normalized question, profile, application/employer/global scope and country. Existing conflicting values are preserved until resolved. Broad vendor guesses and hard-coded personal answers are blocked.
7. Review before submission. Automatic submission is off by default and requires per-job authorization plus verified fields and review. The attempt is saved before clicking and never retried automatically. A click or vendor “saved application” event is not success; only a recognized employer receipt or **Mark submitted by me** confirms it.
8. Use **Tracker / Notes / CSV** for pipeline status, descriptions, notes, imports and exports. Imports do not start applications.
9. Optional Gemini assistance remains in the desktop. **Compare profiles with Gemini…** and **Draft answer with Gemini…** preview their outgoing context and request consent. Drafts require explicit approval before becoming reusable answers.

The browser stays open for manual handoffs. **Settings** controls automatic continuation and approved-answer reuse. Closing the app closes app-owned sessions; reopening retains local records.

## Data and privacy

- `data/intern-bot.sqlite3` is authoritative for profiles, answers, application snapshots, assessments and history. It has owner-only permissions; personal data is not encrypted.
- The operating-system keychain stores employer credentials and Gemini API keys. There is no plaintext credential fallback.
- `data/browser/<run-hash>/` contains isolated app-owned sessions with exclusive locks. The replacement uses a new directory namespace and preserves old directories.
- The extension stores run/tab/document bindings in memory-only `storage.session`. It does not persist profile facts, documents, credentials or approvals.
- Normal autofill has no SpeedyApply, Supabase, AI, telemetry or local HTTP-server dependency. Optional Gemini requests contain only the editable context shown in the consent dialog.

The original XPI, exact source and notices are preserved under `third_party/speedyapply/2.28.0/`. The loaded extension contains only the adapted dependency graph and local controls. See [extension internals](extension/README.md).

## Tests and limitations

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
npm test --prefix extension
PYTHONPATH=. .venv/bin/python tools/benchmark_adapters.py --output /tmp/intern-bot-benchmark.json
```

Tests use fictional forms and intercept their network requests. They exercise the actual adapter functions, not just routing names. Unknown widgets, unrecognized upload receipts, extra/unmatched rows and unrecognized review summaries produce manual handoffs. Only explicitly recognized native/accessible controls can be verified. Final multi-step review requires independently labeled saved values; unsupported summaries cannot be automatically submitted.

Fixture success establishes implementation coverage, not reliability on every employer's current application form. Live employer acceptance and live submissions have not been performed. Browser ownership currently uses POSIX locking; other operating systems are unverified.
