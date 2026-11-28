from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values

from agent_b.adapters.fake_data import CONTACTS

PROJECT_ROOT = Path(__file__).resolve().parents[5]

# Fake calendar: even weekdays (Mon, Wed, Fri) and odd weekdays (Tue, Thu) have different slots
SLOTS = {wd: (["09:30-10:30", "14:00-15:00"] if wd % 2 == 0 else ["11:00-12:00", "16:00-17:00"])
         for wd in range(5)}

DDL = """
CREATE TABLE IF NOT EXISTS contacts (
    key TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, role TEXT, tone TEXT);
CREATE TABLE IF NOT EXISTS free_slots (
    weekday INT NOT NULL, slot TEXT NOT NULL, PRIMARY KEY (weekday, slot));
CREATE TABLE IF NOT EXISTS drafts (
    id SERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL);
"""


def default_conninfo() -> str:
    env = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
    if env.get("AGENT_B_DB"):
        return env["AGENT_B_DB"]
    return (f"host={env.get('DB_HOST', 'localhost')} port=5432 dbname=agent_b_db "
            f"user=agent_b_svc password={env.get('SERVICE_DB_PASSWORD', '')}")


class AgentBStore:
    def __init__(self, conninfo: str | None = None):
        self.conninfo = conninfo or default_conninfo()
        self._ready = False

    def _connect(self):
        conn = psycopg.connect(self.conninfo, autocommit=True)
        if not self._ready:
            conn.execute(DDL)
            for key, c in CONTACTS.items():
                conn.execute(
                    "INSERT INTO contacts (key, name, email, role, tone) VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (key) DO NOTHING",
                    (key, c["name"], c["email"], c["role"], c["tone"]))
            for wd, slots in SLOTS.items():
                for slot in slots:
                    conn.execute("INSERT INTO free_slots (weekday, slot) VALUES (%s, %s) "
                                 "ON CONFLICT DO NOTHING", (wd, slot))
            self._ready = True
        return conn

    def contact(self, key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT name, email, role, tone FROM contacts WHERE key = %s",
                               (key,)).fetchone()
        return dict(zip(("name", "email", "role", "tone"), row)) if row else None

    def contact_keys(self) -> list[str]:
        with self._connect() as conn:
            return [r[0] for r in conn.execute("SELECT key FROM contacts ORDER BY key")]

    def slots(self, weekday: int) -> list[str]:
        with self._connect() as conn:
            return [r[0] for r in conn.execute(
                "SELECT slot FROM free_slots WHERE weekday = %s ORDER BY slot", (weekday,))]

    def save_draft(self, to: str, subject: str, body: str) -> int:
        with self._connect() as conn:
            return conn.execute(
                "INSERT INTO drafts (recipient, subject, body) VALUES (%s, %s, %s) RETURNING id",
                (to, subject, body)).fetchone()[0]