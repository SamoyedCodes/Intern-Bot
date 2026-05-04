from core.storage import JsonStore


def test_json_store_round_trips_state(tmp_path):
    store = JsonStore(str(tmp_path / "app_state.json"))
    data = {
        "profile": {"first_name": "Ada"},
        "workday_credentials": {
            "company.wd3.myworkdayjobs.com": {
                "username": "company_intern@example.com",
                "password": "Secure123!",
            }
        },
    }

    store.save(data)

    assert store.load() == data


def test_json_store_profile_and_tasks_can_share_state(tmp_path):
    store = JsonStore(str(tmp_path / "app_state.json"))
    store.save({"tasks": [{"company": "Example", "job_url": "https://example.com"}]})

    data = store.load()
    data["profile"] = {"first_name": "Ada"}
    store.save(data)

    loaded = store.load()
    assert loaded["tasks"] == [{"company": "Example", "job_url": "https://example.com"}]
    assert loaded["profile"] == {"first_name": "Ada"}
