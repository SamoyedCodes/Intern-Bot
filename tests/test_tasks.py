from gui.views.tasks_view import ApplicationTask, TasksView


def test_task_view_extracts_company_name_from_workday_url():
    company = TasksView._company_name_from_workday_url("https://united-overseas-bank.wd3.myworkdayjobs.com/job/123")

    assert company == "United Overseas Bank"


def test_application_task_round_trips_dict():
    task = ApplicationTask(
        company="Example",
        role="Software Engineering Intern",
        job_url="https://example.wd3.myworkdayjobs.com/job/123",
        phase="phase_1_awaiting_activation",
        status="Needs Review",
        note="Review browser",
    )

    restored = ApplicationTask.from_dict(task.to_dict())

    assert restored == task


def test_application_task_migrates_old_non_account_needs_review_status():
    task = ApplicationTask.from_dict({
        "company": "Example",
        "role": "Internship",
        "job_url": "https://example.wd3.myworkdayjobs.com/job/123",
        "phase": "phase_2_my_experience",
        "status": "Needs Review",
    })

    assert task.status == "Manual Required"


def test_application_task_keeps_new_account_needs_review_status():
    task = ApplicationTask.from_dict({
        "company": "Example",
        "role": "Internship",
        "job_url": "https://example.wd3.myworkdayjobs.com/job/123",
        "phase": "phase_1_awaiting_activation",
        "status": "Awaiting Activation",
    })

    assert task.status == "Needs Review"
