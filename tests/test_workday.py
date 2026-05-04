import asyncio

from plugins.workday import WorkdayPlugin


def test_workday_profile_normalization_keeps_supplied_values():
    plugin = WorkdayPlugin()

    profile = plugin._normalize_profile({
        "first_name": "Ada",
        "email": "ada@example.com",
        "phone": None,
    })

    assert profile["first_name"] == "Ada"
    assert profile["email"] == "ada@example.com"
    assert profile["phone"] == ""
    assert profile["last_name"] == ""
    assert profile["resume_path"] == ""


def test_workday_credential_for_job_uses_site_specific_login():
    plugin = WorkdayPlugin()
    profile = {
        "email": "fallback@example.com",
        "workday_credentials": {
            "company.wd1.myworkdayjobs.com": {
                "username": "company_intern@applications.example.com",
                "password": "Secure123!",
            }
        },
    }

    credential = plugin._credential_for_job(
        "https://company.wd1.myworkdayjobs.com/job/software-engineering-intern",
        profile,
    )

    assert credential["username"] == "company_intern@applications.example.com"
    assert credential["password"] == "Secure123!"
    assert profile["email"] == "fallback@example.com"


def test_workday_credential_lookup_normalizes_urls_with_scheme():
    plugin = WorkdayPlugin()
    profile = {
        "workday_credentials": {
            "https://uobgroup.wd3.myworkdayjobs.com": {
                "username": "intern_uob@benson.sg",
                "password": "Existing123!",
            }
        },
    }

    credential = plugin._credential_for_job(
        "https://uobgroup.wd3.myworkdayjobs.com/en-US/job/123",
        profile,
    )

    assert credential["username"] == "intern_uob@benson.sg"


def test_workday_result_payload_contains_phase_status_and_note():
    plugin = WorkdayPlugin()

    result = plugin._result(False, "Awaiting Activation", "phase_1_awaiting_activation", "Confirm email")

    assert result == {
        "success": False,
        "status": "Awaiting Activation",
        "phase": "phase_1_awaiting_activation",
        "note": "Confirm email",
    }


def test_workday_profile_normalization_includes_experience():
    plugin = WorkdayPlugin()

    profile = plugin._normalize_profile({
        "experience": [
            {
                "employer": "Example Co",
                "job_title": "Software Intern",
                "location": "Singapore",
                "start_date": "May 2025",
                "end_date": "Aug 2025",
                "description": "Built internal tools",
            }
        ]
    })

    assert profile["experience"][0]["employer"] == "Example Co"
    assert profile["address"] == ""
    assert profile["linkedin_url"] == ""


def test_workday_manual_questions_result_payload():
    plugin = WorkdayPlugin()

    result = plugin._manual_questions_result()

    assert result["success"] is True
    assert result["status"] == "Manual Questions"
    assert result["phase"] == "phase_3_application_questions_manual"
    assert "company-specific" in result["note"]


def test_workday_new_account_creation_is_needs_review(monkeypatch):
    plugin = WorkdayPlugin()
    page = FakePage({})

    async def account_created(_page, _profile):
        return True

    monkeypatch.setattr(plugin, "create_account", account_created)

    result = asyncio.run(plugin._phase_1_create_account(
        page,
        {"workday_credential": {"username": "new@example.com", "password": "Secure123!"}},
    ))

    assert result["success"] is True
    assert result["status"] == "Needs Review"
    assert result["phase"] == "phase_1_awaiting_activation"


def test_workday_failed_results_keep_browser_open_for_debugging():
    plugin = WorkdayPlugin()

    result = plugin._result(False, "Failed", "phase_1_login", "Still on login")

    assert plugin._should_keep_browser_open(result) is True


def test_existing_account_sign_in_continues_to_phase_2_status(monkeypatch):
    plugin = WorkdayPlugin()
    page = FakePage({})

    async def signed_in(_page):
        return True

    async def phase_2_result(_page, _profile, _phase):
        return plugin._manual_questions_result()

    monkeypatch.setattr(plugin, "_submit_sign_in", signed_in)
    monkeypatch.setattr(plugin, "_run_phase_2_until_questions", phase_2_result)

    result = asyncio.run(plugin._phase_1_sign_in(
        page,
        {"workday_credential": {"username": "existing@example.com", "password": "Secure123!"}},
    ))

    assert result["status"] == "Manual Questions"
    assert result["phase"] == "phase_3_application_questions_manual"


def test_upload_resume_returns_false_without_resume_path():
    plugin = WorkdayPlugin()
    page = FakePage({"input[type='file']": []})

    uploaded = asyncio.run(plugin._upload_resume_if_available(page, {"resume_path": ""}))

    assert uploaded is False


def test_upload_resume_chooses_first_visible_file_input(tmp_path):
    plugin = WorkdayPlugin()
    resume = tmp_path / "resume.pdf"
    resume.write_text("resume", encoding="utf-8")
    hidden = FakeElement(visible=False)
    visible = FakeElement(visible=True)
    page = FakePage({"input[type='file']": [hidden, visible]})

    uploaded = asyncio.run(plugin._upload_resume_if_available(page, {"resume_path": str(resume)}))

    assert uploaded is True
    assert hidden.uploaded_path is None
    assert visible.uploaded_path == str(resume)


def test_click_continue_uses_visible_next_button():
    plugin = WorkdayPlugin()
    next_button = FakeElement(visible=True)
    page = FakePage({'[data-automation-id="bottom-navigation-next-button"]': [next_button]})

    clicked = asyncio.run(plugin._click_continue(page))

    assert clicked is True
    assert next_button.clicked is True


def test_phase_2_stops_on_application_questions(monkeypatch):
    plugin = WorkdayPlugin()
    page = FakePage({})

    async def questions_visible(_page):
        return True

    monkeypatch.setattr(plugin, "_is_application_questions_page", questions_visible)

    result = asyncio.run(plugin._run_phase_2_until_questions(page, {}, "phase_2_autofill_resume"))

    assert result["phase"] == "phase_3_application_questions_manual"
    assert result["status"] == "Manual Questions"


def test_phase_2_does_not_fill_profile_email_on_sign_in_page():
    plugin = WorkdayPlugin()
    login_email = FakeElement(visible=True)
    page = FakePage({
        'input[type="password"]': [FakeElement(visible=True)],
        'input[type="email"]': [login_email],
    })

    filled = asyncio.run(plugin._fill_profile_gaps(page, {"email": "profile@example.com"}))

    assert filled is False
    assert login_email.value == ""


def test_phase_2_login_failure_stays_at_phase_1(monkeypatch):
    plugin = WorkdayPlugin()
    page = FakePage({'input[type="password"]': [FakeElement(visible=True)]})

    async def sign_in_fails(_page, _profile):
        return False

    monkeypatch.setattr(plugin, "_ensure_signed_in_for_phase_2", sign_in_fails)

    result = asyncio.run(plugin._run_phase_2_until_questions(
        page,
        {"email": "profile@example.com"},
        "phase_2_my_information",
    ))

    assert result["success"] is False
    assert result["status"] == "Failed"
    assert result["phase"] == "phase_1_login"


def test_phase_2_restarts_autofill_after_reauthentication(monkeypatch):
    plugin = WorkdayPlugin()
    page = FakePage({})
    sign_in_states = iter([True, False])

    async def sign_in_state(_page):
        return next(sign_in_states)

    async def signed_in(_page, _profile):
        return True

    async def no_questions(_page):
        return False

    async def uploaded(_page, _profile):
        return True

    async def no_continue(_page):
        return False

    monkeypatch.setattr(plugin, "_is_sign_in_page", sign_in_state)
    monkeypatch.setattr(plugin, "_ensure_signed_in_for_phase_2", signed_in)
    monkeypatch.setattr(plugin, "_is_application_questions_page", no_questions)
    monkeypatch.setattr(plugin, "_upload_resume_if_available", uploaded)
    monkeypatch.setattr(plugin, "_click_continue", no_continue)

    result = asyncio.run(plugin._run_phase_2_until_questions(
        page,
        {"workday_credential": {"username": "workday@example.com", "password": "Secure123!"}},
        "phase_2_my_experience",
    ))

    assert result["phase"] == "phase_2_autofill_resume"
    assert result["status"] == "Manual Required"
    assert "Resume step" in result["note"]


def test_phase_2_uses_workday_credential_when_sign_in_reappears(monkeypatch):
    plugin = WorkdayPlugin()
    workday_email = FakeElement(visible=True)
    password = FakeElement(visible=True)
    sign_in = FakeElement(visible=True)
    page = FakePage({
        'input[type="password"]': [password],
        'input[type="email"]': [workday_email],
        'button:has-text("Sign In")': [sign_in],
    })
    states = iter([True, False])

    async def sign_in_state(_page):
        return next(states)

    monkeypatch.setattr(plugin, "_is_sign_in_page", sign_in_state)

    signed_in = asyncio.run(plugin._ensure_signed_in_for_phase_2(
        page,
        {
            "email": "profile@example.com",
            "workday_credential": {
                "username": "uobgroup_intern@applications.example.com",
                "password": "Secure123!",
            },
        },
    ))

    assert signed_in is True
    assert workday_email.value == "uobgroup_intern@applications.example.com"
    assert password.value == "Secure123!"
    assert sign_in.clicked is True


class FakeElement:
    def __init__(self, visible=True, value="", text=""):
        self.visible = visible
        self.value = value
        self.text = text
        self.clicked = False
        self.uploaded_path = None

    async def is_visible(self):
        return self.visible

    async def fill(self, value):
        self.value = value

    async def input_value(self):
        return self.value

    async def text_content(self):
        return self.text

    async def scroll_into_view_if_needed(self):
        return None

    async def click(self):
        self.clicked = True

    async def set_input_files(self, path):
        self.uploaded_path = path

    async def press(self, key):
        self.pressed = key

    async def check(self):
        self.checked = True


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements
        self.first = elements[0] if elements else FakeElement(visible=False)

    async def count(self):
        return len(self.elements)

    def nth(self, index):
        return self.elements[index]


class FakePage:
    def __init__(self, selectors):
        self.selectors = selectors

    def locator(self, selector):
        return FakeLocator(self.selectors.get(selector, []))

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    async def wait_for_timeout(self, *args, **kwargs):
        return None
