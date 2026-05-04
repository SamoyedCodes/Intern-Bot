from gui.views.tasks_view import ApplicationTask, TasksView


def test_task_view_extracts_company_name_from_workday_url():
    company = TasksView._company_name_from_workday_url("https://united-overseas-bank.wd3.myworkdayjobs.com/job/123")

    assert company == "United Overseas Bank"


def test_application_task_round_trips_dict():
    task = ApplicationTask(
        company="Example",
        role="Software Engineering Intern",
        job_url="https://example.wd3.myworkdayjobs.com/job/123",
        status="Needs Review",
        note="Review browser",
    )

    restored = ApplicationTask.from_dict(task.to_dict())

    assert restored == task
