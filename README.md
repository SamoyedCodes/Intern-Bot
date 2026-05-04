# Intern-Bot

Intern-Bot is a local desktop prototype for preparing and running Workday internship applications. It keeps a local applicant profile, generates per-Workday-site usernames/passwords from a catchall domain, launches a visible Playwright browser, fills known account fields deterministically, and uses Gemini for dynamic form-field mapping when Workday pages vary.

The bot intentionally pauses before final submission so the user can review the application.

## Current Scope

- PySide6 desktop UI
- Workday task queue
- Applicant profile editor
- Workday credential table
- Plain JSON prototype storage
- Gemini API key entry in Settings
- Playwright browser automation
- Workday plugin routing by URL

## Local Data

Prototype state is stored in:

```text
data/app_state.json
```

This includes applicant profile fields and Workday usernames/passwords in plain text. That is acceptable for this prototype, but it is not production-safe.

The Gemini API key is stored in:

```text
.env
```

Both `data/` and `.env` are ignored by git.

## Install

From the project directory:

```bat
conda create -n intern-bot python=3.11 -y
conda activate intern-bot
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bat
conda activate intern-bot
cd C:\Users\Albino\Desktop\Git\Intern-Bot
python main.py
```

## Workflow

1. Open `Profile`.
2. Fill applicant profile fields.
3. Open `Workday Credentials`.
4. Enter your catchall domain.
5. Open `Settings`.
6. Paste and save your Gemini API key.
7. Open `Tasks`.
8. Add a Workday job URL.
9. Start the task.

For a URL like:

```text
https://company.wd3.myworkdayjobs.com/...
```

Intern-Bot creates or reuses a credential for that exact site. If it creates a new one, the username format is:

```text
company_intern@your-domain.com
```

## Project Structure

```text
main.py
core/
  browser/playwright_mgr.py
  llm/field_mapper.py
  storage/json_store.py
gui/
  main_window.py
  styles.qss
  views/profile_view.py
  views/tasks_view.py
plugins/
  base.py
  manager.py
  workday.py
tests/
```

## Verify

```bat
python -m compileall main.py gui plugins core tests
python -m pytest tests -v
```
