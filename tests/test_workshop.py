"""The crew translates real checkpoints into a privacy-limited display."""
import json

from PySide6.QtCore import Qt

from core.automation.models import ApplicationRun, FieldAssessment, InterventionRequest
from gui.workshop import crew_row, orbit_of, MAX_BARS


def test_scene_preserves_blockers_and_keeps_form_content_native():
    run = ApplicationRun(job_url="https://jobs.lever.co/example/123", company="Example", status="needs_input",
                         interventions=[InterventionRequest(kind="answer", question="Private question", message="Answer this")])
    for i in range(MAX_BARS * 2):
        disposition = {1: "blocked", 2: "intentionally_omitted", 3: "intentionally_omitted"}.get(i, "verified")
        run.fields[str(i)] = FieldAssessment(key=str(i), label="Private field", value="Private value", disposition=disposition)
    row = crew_row(run, run.id)
    assert row["station"] == 2 and row["ask"] and not row["moving"]
    assert row["total"] == 36 and len(row["bars"]) == MAX_BARS
    assert row["bars"][:3] == [[.5, True, False], [0, False, True], [1, False, False]]
    assert "Private" not in json.dumps(row) and run.job_url not in json.dumps(row)


def test_movement_and_receipts_require_corresponding_engine_state():
    run = ApplicationRun(job_url="https://jobs.lever.co/example/1", status="running", work_phase="fill")
    assert crew_row(run, run.id)["moving"] and crew_row(run, run.id)["station"] == 1
    assert not crew_row(run, None)["moving"] and "work_phase" not in run.model_dump()
    run.submission_attempted = True
    row = crew_row(run, None)
    assert row["station"] == 3 and row["sent"] and not row["receipt"]
    run.status = "ready_for_review"
    assert crew_row(run, run.id)["moving"]
    run.submitted_by_user = True
    assert not crew_row(run, run.id)["moving"] and not crew_row(run, None)["receipt"]
    run.submission_confirmed = True
    assert crew_row(run, None)["receipt"]


def test_bar_tracks_follow_table_order_filters_and_selection(window):
    view = window.tasks_view
    for i in range(6):
        view.add_task(ApplicationRun(job_url=f"https://jobs.lever.co/example/{i}", company=f"Workshop {i}"))
    view.scene_modes.button(1).click()
    view.table.sortItems(1, Qt.DescendingOrder)
    view.table.selectRow(4)
    visible = [view.table.item(i, 0).data(Qt.UserRole) for i in range(3, 6)]
    scene = view.workshop
    assert [row["id"] for row in scene.payload["rows"]] == visible
    assert scene.payload["selected"] == visible[1]
    scene.bridge.selectRun(visible[2])
    assert view.selected().id == visible[2]
    view.search.setText("Workshop 5")
    assert [row["name"] for row in scene.payload["rows"]] == ["Workshop 5"]
    scene.bridge.selectRun(visible[2])
    assert view.selected().company == "Workshop 5"
    view.scene_modes.button(2).click()
    assert scene.isHidden() and window.store.get("application_view") == "List"


def test_orbit_draws_every_visible_row_and_keeps_send_attempts_off_the_applied_orbit(window):
    view = window.tasks_view
    sent = ApplicationRun(job_url="https://jobs.lever.co/example/sent", company="Sent", status="ready_for_review", submission_attempted=True)
    mine = ApplicationRun(job_url="https://jobs.lever.co/example/mine", company="Mine", status="ready_for_review", submitted_by_user=True)
    closed = ApplicationRun(job_url="https://jobs.lever.co/example/closed", company="Closed", pipeline="archived")
    for run in (sent, mine, closed, *(ApplicationRun(job_url=f"https://jobs.lever.co/example/{i}", company=f"Queued {i}") for i in range(4))):
        view.add_task(run)
    view.scene_modes.button(0).click()
    rows = {row["name"]: row for row in view.workshop.payload["rows"]}
    assert len(rows) == 7 and window.store.get("application_view") == "Orbit"
    assert [orbit_of(rows[name]) for name in ("Sent", "Mine", "Closed", "Queued 0")] == [3, 4, 5, 0]
    assert rows["Sent"]["sent"] and not rows["Sent"]["receipt"] and rows["Mine"]["group"] == "Applied"
    assert "jobs.lever.co" not in json.dumps(view.workshop.payload)
