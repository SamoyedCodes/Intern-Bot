"""Transactional local state; only credential references enter SQLite."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, now
from core.storage.vault import CredentialVault


class LocalStore:
    def __init__(self, path="data/intern-bot.sqlite3", vault=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.vault = vault
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS answers (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS opportunities (profile TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(profile,id));
                CREATE TABLE IF NOT EXISTS scout_scans (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, stage TEXT NOT NULL, note TEXT NOT NULL);
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def migrate_local_engine(self):
        """Invalidate verification only; preserve all historical submission decisions."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM state WHERE key='local_adapter_migration_v1'").fetchone():
                return
            for run_id, payload in db.execute("SELECT id,payload FROM runs").fetchall():
                run = ApplicationRun.model_validate_json(payload)
                if run.is_submitted or run.submitted_at:
                    continue
                run.fields, run.completed_sections = {}, []
                if run.status in {"running", "ready_for_review"}:
                    run.status = "needs_input"
                db.execute("UPDATE runs SET payload=? WHERE id=?", (run.model_dump_json(), run_id))
                db.execute("INSERT INTO events(run_id,at,kind,stage,note) VALUES (?,?,?,?,?)",
                    (run_id, now(), "engine_migration", run.stage, "Local adapters require fresh verification. Chromium may require employer sign-in again; existing browser directories are preserved."))
            db.execute("INSERT INTO state VALUES ('local_adapter_migration_v1','true')")

    def _vault(self):
        if self.vault is None:
            self.vault = CredentialVault()
        return self.vault

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, json.dumps(value)))

    def profiles(self):
        profiles = self.get("profiles", {})
        active = self.get("active_profile", "Default")
        profiles[active] = self.get("verified_profile", {})
        return {name: ApplicantProfile.model_validate(value) for name, value in profiles.items()}

    def save_profile(self, name, profile):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Use a profile name of 1–80 characters.")
        profiles = {k: v.model_dump() for k, v in self.profiles().items()}
        profiles[name] = profile.model_dump()
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO state VALUES (?, ?)", [
                ("profiles", json.dumps(profiles)), ("active_profile", json.dumps(name)),
                ("verified_profile", profile.model_dump_json()),
            ])

    def save_run(self, run: ApplicationRun):
        run.updated_at = now()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (run.id, run.model_dump_json()))

    def opportunities(self, profile_name=None):
        from core.scout import Opportunity
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM opportunities" + (" WHERE profile=?" if profile_name is not None else ""),
                              (profile_name,) if profile_name is not None else ()).fetchall()
        return [Opportunity.model_validate_json(row[0]) for row in rows]

    def save_opportunity(self, item):
        from core.scout import Opportunity
        with self.connect() as db:
            row = db.execute("SELECT payload FROM opportunities WHERE profile=? AND id=?", (item.profile_name, item.id)).fetchone()
            old = Opportunity.model_validate_json(row[0]) if row else None
            if old:
                item.first_seen = old.first_seen
                if old.published and not item.published:
                    item.published, item.freshness = old.published, old.freshness
                    item.evidence["published"] = old.evidence["published"]
            db.execute("INSERT OR REPLACE INTO opportunities VALUES (?,?,?)", (item.profile_name, item.id, item.model_dump_json()))
        return old is None or (old.freshness == "undated" and item.freshness == "recent")

    def close_opportunity(self, profile_name, item_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM opportunities WHERE profile=? AND id=?", (profile_name, item_id)).fetchone()
            if row:
                payload = json.loads(row[0])
                payload["active"] = False
                db.execute("UPDATE opportunities SET payload=? WHERE profile=? AND id=?", (json.dumps(payload), profile_name, item_id))

    def save_scout_report(self, report):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO scout_scans VALUES (?,?)", (report["id"], json.dumps(report)))

    def scout_reports(self, profile_name):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM scout_scans ORDER BY rowid DESC").fetchall()
        return [r for row in rows if (r := json.loads(row[0]))["profile_name"] == profile_name]

    def get_run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return ApplicationRun.model_validate_json(row[0]) if row else None

    def runs(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs ORDER BY rowid").fetchall()
        return [ApplicationRun.model_validate_json(row[0]) for row in rows]

    def save_answer(self, answer: ApprovedAnswer):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO answers VALUES (?, ?)", (answer.id, answer.model_dump_json()))

    def answers(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM answers ORDER BY rowid").fetchall()
        return [ApprovedAnswer.model_validate_json(row[0]) for row in rows]


    def delete_answer(self, answer_id):
        with self.connect() as db:
            db.execute("DELETE FROM answers WHERE id=?", (answer_id,))


    def record_event(self, run_id, kind, stage, note=""):
        with self.connect() as db:
            db.execute("INSERT INTO events(run_id,at,kind,stage,note) VALUES (?,?,?,?,?)", (run_id, now(), kind, stage, note))

    def events(self, run_id):
        with self.connect() as db:
            rows = db.execute("SELECT at,kind,stage,note FROM events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [dict(zip(("at", "kind", "stage", "note"), row)) for row in rows]


    def recent_events(self, run_id, limit):
        with self.connect() as db:
            rows = db.execute("SELECT at,kind,note FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit)).fetchall()
        return [dict(zip(("at", "kind", "note"), row)) for row in rows]

    def delete_run(self, run_id):
        self.delete_runs([run_id])

    def delete_runs(self, run_ids):
        keys = [(run_id,) for run_id in run_ids]
        with self.connect() as db:
            db.executemany("DELETE FROM runs WHERE id=?", keys)
            db.executemany("DELETE FROM events WHERE run_id=?", keys)
