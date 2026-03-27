# Intern-Bot: Automated ATS Application Framework

Intern-Bot is an advanced, automated desktop application designed to streamline the internship and job application process. It utilizes headless browser automation, Large Language Models (LLMs) for dynamic field mapping, and a secured local database to navigate Applicant Tracking Systems (ATS) like Workday, Greenhouse, and Lever.

The graphical interface is built with **PySide6**, featuring a premium, dark-themed aesthetic (inspired by Cybersole) and leveraging fully asynchronous event loops to maintain a responsive UI while heavy browser automation runs in the background.

---

## 🏗️ High-Level Architecture

The framework is divided into modular components to ensure long-term maintainability against the ever-changing web DOM and strict anti-bot web application firewalls (WAFs):

1. **GUI (PySide6)**: A native, non-blocking asynchronous desktop interface.
2. **Core Database (SQLModel)**: A strictly-typed ORM persisting User Profiles, Education, and Job Histories locally in SQLite.
3. **Core Security (SQLCipher & PBKDF2)**: Ensures all user Personally Identifiable Information (PII) and generated passwords are encrypted at rest using a Master Password.
4. **Browser Engines (Playwright & Nodriver)**: A dynamic dual-engine approach to bypass Cloudflare Turnstile while retaining multi-tab DOM injection capabilities.
5. **LLM Semantic Parser (Pydantic AI)**: Dynamically maps the user's JSON profile to raw HTML inputs using OpenAI's GPT-4o-mini, eliminating the need for brittle, hardcoded CSS selectors.
6. **Plugin System**: An extensible, auto-discovering plugin manager that routes intercepted URLs to the correct module scripts (e.g., parsing a URL to the `WorkdayPlugin`).

---

## 📂 Module & Class Deep Dive

### 1. `gui/` (Graphical User Interface)
The frontend layer connecting the user's data to the background asyncio loops.
- **`main_window.py` - `MainWindow` Class:**
  - The primary application shell containing the QTabWidget navigation. It handles the injection of the `styles.qss` layout and manages the `status_widget` at the bottom of the screen.
- **`views/profile_view.py` - `ProfileView` Class:**
  - The settings tab replacing traditional account managers. Utilizes `QFormLayout` to capture the master resume variables (First Name, Last Name, Email, Phone, etc.) which are then synced to the `User` database model.
- **`views/tasks_view.py` - `TasksView` Class:**
  - Contains the core active tasks table (`QTableWidget`). Rows represent instances of asynchronous ATS tasks.
  - Exposes `start_all_tasks()` and `start_single_task(row_index)` which are designed to queue the Workday or Greenhouse plugins into the PySide6 event loop.

### 2. `core/database/` (Data Persistence Layer)
Manages saving and retrieving the candidate's master profile to automatically inject it into forms.
- **`models.py`:**
  - Relational `SQLModel` schemas:
    - `User`: Base applicant data (Demographics, Contact Info).
    - `Education` & `Experience`: One-to-Many relationships bounded to `User`.
    - `PlatformCredential`: Encrypted storage for ATS-specific account passwords (e.g., Workday subdomains).
    - `JobApplication`: Tracks status strings for monitoring task completion in the UI.
- **`engine.py`:**
  - Exposes the `init_engine(db_key)` hook which validates bindings to `pysqlcipher3`. If a valid cipher key is provided, it unlocks the local DB. Features a fallback to standard `sqlite3` bridging for unencrypted local development.
  - Provides the `get_session()` capability for transactions.

### 3. `core/security/` (Cryptography)
- **`crypto.py` - `SecurityManager` Class:**
  - `_load_or_create_salt()`: Initializes cryptographic randomness.
  - `derive_key(master_password)`: Utilizes `hashlib.pbkdf2_hmac` with 100,000 iterations to turn the GUI master password into the hex key that unlocks the SQLCipher SQL engine.
  - `verify_master_password()`: Syntactically verifies the key against `sqlite_master` headers before unlocking the app.

### 4. `core/browser/` (Headless Automation Hooking)
Handles the instantiation of hidden Chromium clusters to act on behalf of the user.
- **`playwright_mgr.py` - `AsyncPlaywrightManager` Class:**
  - Binds the `async_playwright` module to persistent context profiles (`user_data_dir`). This preserves WAF cookies to dramatically reduce bot detection during sequential task runs.
- **`nodriver_mgr.py` - `NodriverManager` Class:**
  - A fallback wrapper utilizing `nodriver` to interface directly with the Chrome DevTools Protocol (CDP). Crucial for penetrating rigorous "Turnstile" or "PerimeterX" initial captchas.

### 5. `core/llm/` (Semantic Field Extraction)
Reduces frontend fragility by abandoning hardcoded XPaths.
- **`field_mapper.py`:**
  - **`ApplicationFormMapping`:** A Pydantic schema enforcing the LLM to output a `Dict[str, str]` connecting `input#emailLocator` to `user.email`.
  - **`extract_fields(html_blob, user_profile)`:** A lazy-evaluated Pydantic AI agent targeting `GPT-4o-mini`. It processes raw HTML page strings and intelligently deduces which input fields correspond to which of the user's profile JSON variables.

### 6. `plugins/` (Dynamic ATS Discovery)
Every ATS behaves differently; this folder acts as a Drop-In bucket for extending bot functionality.
- **`base.py` - `ATSPluginInterface` Abstract Class:**
  - Enforces three mandatory coroutines for any custom script: `detect_account_existence()`, `create_account()`, and `apply_to_job()`.
  - Requires the `domain_matchers` array for routing.
- **`manager.py` - `PluginManager` Class:**
  - Utilizes Python's `pkgutil` and `importlib` to scan the folder at runtime. It automatically detects and binds classes inheriting from `ATSPluginInterface` perfectly mapping them to a URL. 
  - Exposes `get_plugin_for_url(url)` to be called by the `TasksView` start button.

---

## 🚀 Setup and Execution

**1. Create the Environment**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

**2. Setup API Variables**
Set the OpenAI token for the Pydantic AI HTML mapper to function properly:
```bash
export OPENAI_API_KEY="sk-proj-xyz..."
```

**3. Launch the Application**
```bash
python main.py
```
*(Ensure you use `pythonw main.py` on macOS if outside a terminal to prevent detached UI freezing, though `python main.py` is fine for local dev).*