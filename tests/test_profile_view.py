from gui.views.profile_view import normalize_experience_entries


def test_profile_experience_serialization_normalizes_multiple_entries():
    entries = normalize_experience_entries([
        {
            "employer": " Example Co ",
            "job_title": "Software Intern",
            "location": "Singapore",
            "start_date": "May 2025",
            "end_date": "Aug 2025",
            "description": "Built internal tools",
        },
        {
            "employer": "Another Co",
            "job_title": "Data Intern",
            "location": "Remote",
            "start_date": "Sep 2025",
            "end_date": "Current",
            "description": "Analyzed application data",
        },
    ])

    assert entries == [
        {
            "employer": "Example Co",
            "job_title": "Software Intern",
            "location": "Singapore",
            "start_date": "May 2025",
            "end_date": "Aug 2025",
            "description": "Built internal tools",
        },
        {
            "employer": "Another Co",
            "job_title": "Data Intern",
            "location": "Remote",
            "start_date": "Sep 2025",
            "end_date": "Current",
            "description": "Analyzed application data",
        },
    ]


def test_profile_experience_serialization_drops_empty_rows_and_fills_missing_keys():
    entries = normalize_experience_entries([
        {},
        {"employer": "Example Co", "job_title": "Software Intern"},
    ])

    assert entries == [{
        "employer": "Example Co",
        "job_title": "Software Intern",
        "location": "",
        "start_date": "",
        "end_date": "",
        "description": "",
    }]
