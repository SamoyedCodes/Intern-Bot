from core.profile_export import build_extension_profile_payload


def test_extension_profile_payload_carries_profile_and_credentials():
    payload = build_extension_profile_payload(
        {"first_name": "Ada", "default_answers": "Require sponsorship: No"},
        {"company.wd1.myworkdayjobs.com": {"username": "u", "password": "p"}},
    )

    assert payload["schema_version"] == 1
    assert payload["source"] == "intern-bot-desktop"
    assert payload["profile"]["first_name"] == "Ada"
    assert payload["profile"]["workday_credentials"]["company.wd1.myworkdayjobs.com"]["username"] == "u"
    assert payload["workday_credentials"]["company.wd1.myworkdayjobs.com"]["password"] == "p"
