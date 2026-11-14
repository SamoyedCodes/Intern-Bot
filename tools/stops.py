"""Where runs stop and why, per site, from the events the engine already records.

    PYTHONPATH=. .venv/bin/python tools/stops.py [path/to/intern-bot.sqlite3]
"""
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import get_args

from core.automation.models import ApplicationRun, InterventionRequest, ats_name, site_key

# Every intervention kind hands the run to you; the rest explain a stop without causing one.
STOPS = {*get_args(InterventionRequest.model_fields["kind"].annotation), "failed"}
TROUBLE = {"adapter_stalled", "recipe_stale", "ai_match_failed", "http_error"}


def stops(path):
    """{site: {"runs", "reviewed", "reasons": Counter[(kind, section, note)] counted in runs, not events}}."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # read-only: safe while the app is open
    try:
        runs = [ApplicationRun.model_validate_json(row[0]) for row in db.execute("SELECT payload FROM runs")]
        events = db.execute("SELECT run_id,kind,stage,note FROM events").fetchall()
    finally:
        db.close()
    site_of = {run.id: ats_name(run.job_url) or site_key(run.job_url) for run in runs}
    report = defaultdict(lambda: {"runs": 0, "reviewed": 0, "reasons": Counter()})
    reviewed = {run.id for run in runs if run.is_submitted or run.status == "ready_for_review"}
    seen = set()
    for run_id, kind, stage, note in events:
        if run_id not in site_of:
            continue
        if kind == "ready_for_review":
            reviewed.add(run_id)
        # Stages end in a per-page hash ("Workday:0cbd052d2e"); the name before it is what repeats across runs.
        reason = (kind, stage.split(":")[0], note)
        if kind in STOPS | TROUBLE and not note.startswith("Paused by you") and (run_id, reason) not in seen:
            seen.add((run_id, reason))
            report[site_of[run_id]]["reasons"][reason] += 1
    for run in runs:
        report[site_of[run.id]]["runs"] += 1
        report[site_of[run.id]]["reviewed"] += run.id in reviewed
    return dict(report)


if __name__ == "__main__":
    report = stops(sys.argv[1] if len(sys.argv) > 1 else "data/intern-bot.sqlite3")
    for site, entry in sorted(report.items(), key=lambda item: -item[1]["runs"]):
        print(f"\n{site}: {entry['reviewed']} of {entry['runs']} runs reached review")
        for (kind, section, note), count in entry["reasons"].most_common(15):
            print(f"  {count:>3} run{'s' if count > 1 else ' '}  {kind:<13} at {section or '-'}: {note[:140]}")
