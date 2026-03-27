# Intern-Bot

## 1. Project Overview
**Intern-Bot** is an extensible, Python-based desktop application designed to automate submission loops for internship applications across Applicant Tracking Systems (ATS) like Workday. The system utilizes headless browsers (Playwright & Nodriver) for DOM manipulation and features a dynamic semantic field mapper powered by Google's Gemini LLM to interpret dynamic HTML forms. The intuitive native GUI is constructed via PySide6.

## 2. Prerequisites
- **OS**: macOS (Intel or Apple Silicon)
- **Python**: 3.8+ (Testing performed on 3.13)
- **Compilers**: Xcode Command Line Tools (required if manually compiling `pysqlcipher3` for encrypted DBs).

## 3. Installation & Setup
1. **Clone & Environment**
    ```bash
    git clone https://github.com/albinomac/Intern-Bot.git
    cd Intern-Bot
    python3 -m venv venv
    source venv/bin/activate
    ```
2. **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```
3. **Install Browser Binaries**
    ```bash
    playwright install chromium
    ```

## 4. Environment Variables
API keys and dynamic configurations are securely injected at runtime via `python-dotenv`.

1. Copy `.env.example` to `.env`:
    ```bash
    cp .env.example .env
    ```
2. Open `.env` and set the following variables:
    * `GEMINI_API_KEY`: A valid Google AI studio key required by Pydantic AI to parse raw HTML blocks into application profiles.

## 5. Usage Examples
To launch the native graphical application:
```bash
source venv/bin/activate
python main.py
```
*(Note: Use `pythonw main.py` on macOS if executing completely detached from a terminal).*

### Running Tasks
Clicking the green **"▶ Start Tasks"** button inside the GUI dynamically injects the automation pipelines into a background `AsyncIOScheduler`. This safely invokes the Playwright processes on a distinct thread allowing the native PySide6 loop to retain unblocked 60fps rendering callbacks.

```python
# Expected Console Output upon clicking Play
[GUI] 'Start All Tasks' clicked! Initiating automation loop...
[GUI] 'Play' clicked on task row 0! Queueing job...
[WorkdayPlugin] Intercepting Workday Portal: https://company.wd1.myworkdayjobs.com/
```

---

## 6. Architecture & System Design
The system employs an event-driven architecture bridging a synchronous GUI with asynchronous headless background processors.

**Data Flow Pipeline:**
1. **Initialization:** `main.py` binds the `PySide6.QtAsyncio.run()` loop.
2. **Data Ingestion:** The user fills out their global profile in `ProfileView`. This data binds to the `User` instances in the `SQLModel` ORM (`core/database/models.py`).
3. **Orchestration:** When a task is queued, the `PluginManager` dynamically reads the target job URL and iterates over `/plugins` to find an `ATSPluginInterface` matching the domain string (e.g., `*.myworkdayjobs.com`).
4. **Execution:** The bound Plugin invokes the `AsyncPlaywrightManager` to navigate the DOM. When encountering dynamic inputs, the raw HTML chunk and `User` JSON dict are fed to `extract_fields()` (`core/llm/field_mapper.py`).
5. **LLM Parsing:** Gemini maps the specific profile keys to explicit CSS identifiers.
6. **Completion:** Playwright injects the string primitives safely into the web DOM, completing the application cycle.

---

## 7. Code & API Reference

### `core/browser/playwright_mgr.py`
Manages the lifecycle of Microsoft Playwright engines avoiding Cloudflare signatures.
*   **`class AsyncPlaywrightManager`**
    *   `start()`: Initializes the `chromium` process utilizing a `launch_persistent_context`. Passing `--disable-blink-features=AutomationControlled` explicitly stops `navigator.webdriver` fingerprint leaks.
    *   `stop()`: Safely closes the page and persistent context targets.

### `core/llm/field_mapper.py`
Dynamic semantic DOM parser eliminating strict XPath dependencies.
*   **`class ApplicationFormMapping(BaseModel)`**: Extends Pydantic logic forcing the LLM to return `mappings: Dict[str, str]` corresponding to CSS ID -> Profile Data Value.
*   **`async def extract_fields(html_blob: str, user_profile: Dict[str, Any]) -> ApplicationFormMapping`**:
    *   *Parameters*: `html_blob` (Raw HTML source string), `user_profile` (A JSON serializable dictionary of the applicant).
    *   *Returns*: Validated `ApplicationFormMapping` struct containing exact DOM insertion maps.
    *   *Error Handling*: Throws `ValueError` if `GEMINI_API_KEY` is completely missing from the `.env` execution frame.

### `plugins/manager.py`
Hot-pluggable ATS script auto-discoverer.
*   **`class PluginManager`**
    *   `get_plugin_for_url(url: str) -> Optional[ATSPluginInterface]`: Accepts a raw standard HTTP Job listing string, iterates all dynamically imported subclasses matching the embedded `domain_matchers` strings, and yields the instance required to automate the portal.

### `plugins/workday.py`
The concrete implementation of the Workday Applicant Tracking System.
*   **`class WorkdayPlugin`**
    *   `_get_clean_html(page) -> str`: Minifies massive React DOM responses utilizing `beautifulsoup4` to drastically reduce token payload costs before transit to Gemini.
    *   `detect_account_existence()`: Identifies `'input[type="email"]'`, executes `.fill()`, and intercepts subsequent DOM loads evaluating if the challenge promotes registration or password ingestion.
    *   `apply_to_job()`: Replaces human interaction traversing across the paginated `My Experience / Disclosures` tabs dynamically prompting the `field_mapper` AI agent sequentially until `Submit` is evaluated logically and paused for user review.

### `core/security/crypto.py`
Ensures all profile JSON payloads and generated Passwords remain natively encrypted via AES-256 local SQLCipher binaries.
*   **`class SecurityManager`**
    *   `derive_key(master_password: str) -> str`: Executes a 100,000 iteration `pbkdf2_hmac` targeting `sha256` hashing on the Master Password yielding the 64-character raw hex buffer required by the DB engine.

---

## 8. Developer Guide

**Local Environment Setup**
Follow the steps strictly denoted in section `3. Installation & Setup`. 

**Managing Dependencies**
If you import additional PyPI packages, ensure they are pinned:
```bash
pip freeze > requirements.txt
```

**Running Tests**
The application enforces strict behavior contracts evaluated via a rigorous test suite utilizing `pytest` and `pytest-asyncio`.

To run the full suite isolated within your virtual environment explicitly testing database hydration and cryptographic bindings, simply invoke:
```bash
pytest tests/ -v
```
