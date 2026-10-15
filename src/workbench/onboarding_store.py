"""One local SQLite snapshot, atomically saved with optimistic concurrency.

The activity inside the snapshot is a local demo history, not a secure audit log.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable


class RevisionConflict(Exception):
    def __init__(self, revision: int):
        super().__init__("This plan changed in another tab. Reload before saving.")
        self.revision = revision


class StorageError(Exception):
    """Existing data cannot be read or saved; never silently reset it."""


class OnboardingStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=5)
            try:
                db.execute("CREATE TABLE IF NOT EXISTS onboarding (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
                from .onboarding import empty_state
                db.execute("INSERT OR IGNORE INTO onboarding (id, data) VALUES (1, ?)",
                           (json.dumps(empty_state()),))
                db.commit()
                return db
            except BaseException:
                db.close()
                raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Local plan storage is unavailable; existing data was not reset.") from exc

    @staticmethod
    def _read(db: sqlite3.Connection) -> dict:
        try:
            from .onboarding import parse_intake, parse_plan
            row = db.execute("SELECT data FROM onboarding WHERE id=1").fetchone()
            state = json.loads(row[0])
            if (not isinstance(state, dict) or state.get("schema_version") != 1
                    or type(state.get("revision")) is not int
                    or state["revision"] < 0
                    or any(not isinstance(state.get(key), list) for key in ("customers", "tasks", "activity"))):
                raise ValueError("Invalid state schema")
            # Check domain records too: a syntactically valid JSON document can
            # still be damaged. Report it instead of crashing a later response.
            parsed = parse_intake(json.dumps(state["customers"]), "json") if state["customers"] else {"issues": []}
            if parsed["issues"]:
                raise ValueError("Invalid saved customers")
            tasks = parse_plan(json.dumps({"schema_version": 1, "tasks": state["tasks"]}), "json")
            customer_ids = {customer["customer_id"] for customer in state["customers"]}
            if any(task["customer_id"] not in customer_ids for task in tasks):
                raise ValueError("Orphaned saved tasks")
            if any(not isinstance(event, dict) or any(not isinstance(event.get(key), str)
                   for key in ("at", "action", "details")) for event in state["activity"]):
                raise ValueError("Invalid saved activity")
            return state
        except (TypeError, IndexError, KeyError, ValueError, RecursionError, sqlite3.Error) as exc:
            raise StorageError("Saved plan is unreadable; existing data was not reset.") from exc

    def read(self) -> dict:
        db = self._connect()
        try:
            return self._read(db)
        finally:
            db.close()

    def change(self, expected_revision: int, transform: Callable[[dict], dict]) -> dict:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db)
            if state["revision"] != expected_revision:
                raise RevisionConflict(state["revision"])
            result = transform(state)
            db.execute("UPDATE onboarding SET data=? WHERE id=1", (json.dumps(result),))
            db.commit()
            return result
        except sqlite3.Error as exc:
            db.rollback()
            raise StorageError("Could not save the local plan. Reload before trying again.") from exc
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
