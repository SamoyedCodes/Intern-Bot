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
