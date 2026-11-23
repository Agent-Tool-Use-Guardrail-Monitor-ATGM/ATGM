"""Persist reviewed errors and drift notifications before acknowledging Kafka input."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime

from optwin.detector import Optwin

ERROR_TOPIC = "classifier-errors"
DRIFT_TOPIC = "drift"


class DriftService:
    def __init__(self, path, detector: Optwin):
        self.detector = detector
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA locking_mode = EXCLUSIVE")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS windows (
                agent TEXT NOT NULL, model TEXT NOT NULL, errors TEXT NOT NULL, PRIMARY KEY (agent, model)
            );
            CREATE TABLE IF NOT EXISTS reviewed (
                agent TEXT NOT NULL, model TEXT NOT NULL, session TEXT NOT NULL, PRIMARY KEY (agent, model, session)
            );
            CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, event TEXT NOT NULL);
        """)

    def handle(self, event: object) -> None:
        if not isinstance(event, dict) or event.get("event_type") != "classifier.error":
            return
        data = event.get("data")
        if not isinstance(data, dict) or data.get("detector") != "online_bls":
            return
        agent, model, session = data.get("agent_id"), data.get("model_version"), event.get("session_id")
        error = data.get("error")
        if agent not in ("A", "B") or not isinstance(model, str) or not model:
            return
        if not isinstance(session, str) or not session or type(error) is not int or error not in (0, 1):
            return

        with self.db:
            inserted = self.db.execute("INSERT OR IGNORE INTO reviewed VALUES (?, ?, ?)", (agent, model, session))
            if not inserted.rowcount:
                return
            row = self.db.execute("SELECT errors FROM windows WHERE agent = ? AND model = ?",
                                  (agent, model)).fetchone()
            window = ((row[0] if row else "") + str(error))[-self.detector.maximum:]
            details = self.detector.detect(window)
            if details is not None:
                event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(["atgm", "optwin", agent, model, session])))
                drift = {
                    "schema_version": "1.0",
                    "event_id": event_id,
                    "event_type": "drift.detected",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "run_id": event.get("run_id"),
                    "session_id": session,
                    "sequence": None,
                    "request_id": None,
                    "data": {
                        "agent_id": agent,
                        "detector": "optwin",
                        "monitored": "online_bls_error",
                        "model_version": model,
                        "details": details,
                    },
                }
                self.db.execute("INSERT INTO outbox VALUES (?, ?)", (event_id, json.dumps(drift)))
                window = ""
            self.db.execute("INSERT OR REPLACE INTO windows VALUES (?, ?, ?)", (agent, model, window))

    def pending(self):
        return self.db.execute("SELECT id, event FROM outbox ORDER BY rowid").fetchall()

    def acknowledge(self, event_id):
        with self.db:
            self.db.execute("DELETE FROM outbox WHERE id = ?", (event_id,))
