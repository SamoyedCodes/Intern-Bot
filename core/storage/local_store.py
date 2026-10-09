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


    def delete_run(self, run_id):
        with self.connect() as db:
            db.execute("DELETE FROM runs WHERE id=?", (run_id,))
            db.execute("DELETE FROM events WHERE run_id=?", (run_id,))
