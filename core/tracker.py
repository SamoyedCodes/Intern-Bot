"""Local application CSV interchange and activity totals."""
import csv
from collections import Counter
from datetime import datetime

from core.automation.models import ApplicationRun, canonical_url, job_identity, now

PIPELINE = ("saved", "applied", "screen", "interviewing", "offer", "rejected", "archived")
CSV_FIELDS = ("company", "role", "job_url", "pipeline", "submitted_at", "profile_name", "notes", "job_description")


def export_csv(runs, path):
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for run in runs:
            row = {key: getattr(run, key) for key in CSV_FIELDS}
            # Neutralize spreadsheet formula execution, including whitespace-prefixed formulas.
            writer.writerow({k: "'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v for k, v in row.items()})


def import_csv(store, path):
    aliases = {"title": "role", "job title": "role", "company name": "company", "url": "job_url",
               "job link": "job_url", "date": "submitted_at", "date applied": "submitted_at", "status": "pipeline"}
    known = {job_identity(r.job_url) for r in store.runs()}
    pending, skipped = [], 0
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("CSV needs a header with role and job_url columns.")
        headers = [aliases.get(h.strip().lower(), h.strip().lower()) for h in reader.fieldnames]
        if len(set(headers)) != len(headers) or not {"role", "job_url"} <= set(headers):
            raise ValueError("Use unique columns including role (or Title) and job_url (or URL).")
        for number, source in enumerate(reader, 2):
            if None in source or any(value is None for value in source.values()):
                raise ValueError(f"Row {number}: column count does not match the header.")
            data = {k: v.strip() for k, v in zip(headers, source.values()) if k in CSV_FIELDS}
            if not data["role"]:
                raise ValueError(f"Row {number}: a job title is required.")
            data["job_url"] = canonical_url(data["job_url"], supported_only=False)
            data["pipeline"] = data.get("pipeline") or "applied"
            if data["pipeline"] not in PIPELINE:
                raise ValueError(f"Row {number}: unknown pipeline status.")
            date = data.get("submitted_at", "")
            if date:
                try:
                    datetime.fromisoformat(date)
                except ValueError:
                    raise ValueError(f"Row {number}: use an ISO date such as 2026-10-08.") from None
            elif data["pipeline"] not in {"saved", "archived"}:
                data["submitted_at"] = now()
            identity = job_identity(data["job_url"])
            if identity in known:
                skipped += 1
                continue
            known.add(identity)
            pending.append(ApplicationRun(**data))
    # Validate the entire file before writing; a malformed row never leaves half an import.
    with store.connect() as db:
        db.executemany("INSERT INTO runs VALUES (?, ?)", [(r.id, r.model_dump_json()) for r in pending])
    return len(pending), skipped


def activity(runs):
    pipeline = Counter(r.pipeline if r.pipeline != "saved" or not r.is_submitted else "applied" for r in runs)
    daily = Counter(r.submitted_at[:10] for r in runs if r.submitted_at)
    submitted = sum(bool(r.submitted_at) or r.is_submitted for r in runs)
    interviews = sum(r.pipeline in {"interviewing", "offer"} for r in runs)
    return pipeline, daily, submitted, interviews
