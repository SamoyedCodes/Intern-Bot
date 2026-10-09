# Intern-Bot

A local Python/PySide6 desktop application with SpeedyApply-style profiles, application autofill, saved responses, tracking, and optional AI assistance. One automation engine fills known controls, reads values back, and records incomplete fields. Workday has a dedicated workflow; Greenhouse, Lever and Ashby have a shared conventional-form adapter.

The engine is a **preview**. Fictional browser tests pass; reliability across real employers still needs live acceptance testing. See the [capability comparison and limits](docs/speedyapply-parity.md). This is built into the desktop app; no Chrome/Firefox extension installation is needed.

## Install and run (macOS)

Use Python 3.11 or newer. Create the virtual environment once:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

Choose **Settings → Browser** to use installed Google Chrome or Playwright's Firefox build. For Firefox, also run `python -m playwright install firefox`. These use isolated app-owned profiles, not your normal browser tabs or passwords. Firefox launch is currently unverified on this host; see the acceptance record.

For subsequent launches:

```sh
source .venv/bin/activate
python main.py
```

Credentials require macOS Keychain. There is no plaintext fallback. Browser ownership currently uses POSIX file locking; other platforms have not been validated.

## Workflow

1. Open **Profile → Applicant details**. Enter explicit address components, education and experience rows, skills, languages, optional EEO answers, and select an existing resume/cover letter. Click **Save profile**. Use **Save as new profile** for role-specific variants or import/export profile JSON.
2. Under **Workday credentials**, enter the employer site and load or save its login. **Generate login** uses your email or optional catchall domain and creates a password locally; click **Save login** to store it. Account consent and activation still need explicit approval/manual action.
3. In **Tasks**, choose **New application**, select a profile, and add a job you genuinely intend to apply to. Workday, hosted Greenhouse, Lever and Ashby URLs support autofill. Other HTTPS jobs can be tracked manually. Browser and continuation defaults come from Settings.
4. Use **Start / Resume**, or **Start queue** for sequential queued/failed applications. Applications waiting for input or review are not automatically restarted.
5. When paused, open **Details / Answers**, approve an exact answer or optional omission, and resume. Complete email verification or CAPTCHA in the browser when requested.
6. Use **Edit application profile** to change that application's profile snapshot or resume. Revisit its first section before resuming so changed facts are reverified. Saving the main profile affects new applications only.
7. At **Ready for review**, inspect and submit yourself. **Mark submitted by me** records your confirmation. Alternatively, explicitly authorize automatic submission for that job when creating it. Automatic submission requires verified fields/review, persists its attempt before clicking, and never retries an ambiguous submission. Only a recognized employer receipt marks it applied automatically.
8. Use **Tracker / Notes / CSV** to update pipeline status, save a job description and notes, view activity totals, or import/export applications. Imports never start applications. Submitted, interviewing, rejected, offered and archived jobs stay out of the queue.
9. Optional: save a Gemini key/model in Settings. **Compare profiles with Gemini…** evaluates saved career profiles against your pasted job description. **Details / Answers → Draft answer with Gemini…** produces an editable draft. Each request previews its outgoing context and requires consent. Drafts only become reusable after explicit answer approval.

**Profile → Approved answers** lets you inspect/remove outdated approvals. Matching uses exact normalized question wording, named profile, application/employer/global scope, and country context. On shared ATS hosts, employer scope includes the tenant path. Unknown answers are never guessed. Turning off saved-answer reuse still allows answers approved for that particular application.

The browser stays open for handoffs. Closing the app closes app-owned sessions. Restarting retains checkpoints; resume the employer's saved draft when prompted.

Chrome/Chromium launches omit `--enable-automation` and disable Blink's `AutomationControlled` flag. Visible sessions use the native window size and browser locale, without user-agent or hardware fingerprint overrides. Restart the app to apply launch changes to existing sessions. These measures do not guarantee that automation is undetectable or prevent all Workday errors. A visible `VPS|…` error or the “Something went wrong / Please refresh” page pauses the run for manual recovery without automatic refresh or repeated submission. The error code alone does not establish the cause. CAPTCHA remains a manual handoff.

## Data and privacy

- `data/intern-bot.sqlite3`: structured profiles, application runs, approved answers, field assessments, and local event history. Personal data is not encrypted; the database uses owner-only file permissions.
- Operating-system keychain, service `intern-bot`: employer logins and saved Gemini API keys.
- `data/browser/<run-hash>/`: isolated persistent browser sessions with exclusive ownership locks.

The app does not automatically import old JSON state or read `.env`. The previous plugin engine and extension remain removed. Existing structured profiles, application runs and Chromium browser sessions remain available; existing profile data and approvals belong to **Default**. Explicit JSON profile import/export uses the current profile schema. Old JSON files, exports and installed extension data are left untouched.

Normal automation sends no data to AI. Optional Gemini text assistance sends only the editable, consented context shown in its dialog. The default context contains career facts and job information, excluding structured contact/identity/EEO fields, file contents, browser HTML, screenshots and credentials. Free-text facts can still contain personal information: review them before sending. Diagnostics omit provider bodies, passwords and raw browser exceptions. Browser Use recovery remains disabled; saving an API key does not enable browser observation sharing. `requirements-browser-use.txt` is not needed for normal operation. No new dependencies were added for text assistance or tracking.

## Tests

```sh
source .venv/bin/activate
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Browser tests use fictional forms and block page network requests. Set `INTERN_BOT_TEST_BROWSER=/absolute/path/to/chromium` only if testing against a different browser executable.

For targeted cross-browser checks, set `INTERN_BOT_TEST_ENGINE=chrome` or `INTERN_BOT_TEST_ENGINE=firefox`. Install the matching browser first. Gemini tests use mocked responses and never call a paid API.

## Acceptance and limitations

See [acceptance record](docs/acceptance.md). Unsupported controls, ambiguous authentication, embedded frames/shadow roots, generic repeated-section layouts and unrecognized review summaries cause handoffs. Workday pages with the same section heading may need manual navigation. There is no cloud sync, installable browser extension, mailbox integration, job discovery, resume generation or 25+ ATS compatibility claim. Live Gemini access and live employer submissions have not been tested.
