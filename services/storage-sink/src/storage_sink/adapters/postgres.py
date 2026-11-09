"""PostgreSQL writer for analytics_db: creates the tables and inserts rows idempotently.

Inserts use ON CONFLICT (event_id) DO NOTHING: a message delivered twice (Kafka is
at-least-once) is stored once. Grafana's read-only role gets SELECT on these tables
automatically (see infra/postgres/init.sh).
"""
from __future__ import annotations

from collections import defaultdict

import psycopg

from storage_sink.domain.rows import Row

COLUMNS = {
    "agent_events": ["event_id", "occurred_at", "session_id", "run_id", "topic", "agent_id", "event_type",
                     "sequence", "tool_name", "success", "duration_ms", "session_call_index", "arguments", "data"],
    "scores": ["event_id", "occurred_at", "session_id", "run_id", "agent_id", "detector", "model_version",
               "scored_event_id", "score"],
    "alarms": ["event_id", "occurred_at", "session_id", "run_id", "agent_id", "detector", "scored_event_id",
               "score", "threshold", "q"],
    "labels": ["event_id", "occurred_at", "session_id", "run_id", "agent_id", "detector", "scored_event_id",
               "verdict", "violation_type", "reviewer"],
    "other_events": ["event_id", "occurred_at", "session_id", "run_id", "topic", "agent_id", "event_type", "data"],
}

DDL = """
CREATE TABLE IF NOT EXISTS agent_events (
    event_id TEXT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL, session_id TEXT, run_id TEXT,
    topic TEXT NOT NULL, agent_id TEXT, event_type TEXT NOT NULL, sequence BIGINT,
    tool_name TEXT, success BOOLEAN, duration_ms DOUBLE PRECISION, session_call_index INT,
    arguments JSONB, data JSONB, stored_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS agent_events_time ON agent_events (occurred_at);
CREATE INDEX IF NOT EXISTS agent_events_session ON agent_events (session_id);

CREATE TABLE IF NOT EXISTS scores (
    event_id TEXT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL, session_id TEXT, run_id TEXT,
    agent_id TEXT, detector TEXT, model_version TEXT, scored_event_id TEXT, score DOUBLE PRECISION,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS scores_time ON scores (occurred_at);

CREATE TABLE IF NOT EXISTS alarms (
    event_id TEXT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL, session_id TEXT, run_id TEXT,
    agent_id TEXT, detector TEXT, scored_event_id TEXT, score DOUBLE PRECISION,
    threshold DOUBLE PRECISION, q DOUBLE PRECISION, stored_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS alarms_time ON alarms (occurred_at);

CREATE TABLE IF NOT EXISTS labels (
    event_id TEXT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL, session_id TEXT, run_id TEXT,
    agent_id TEXT, detector TEXT, scored_event_id TEXT, verdict TEXT, violation_type TEXT, reviewer TEXT,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS labels_time ON labels (occurred_at);
CREATE INDEX IF NOT EXISTS labels_session ON labels (session_id);

CREATE TABLE IF NOT EXISTS other_events (
    event_id TEXT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL, session_id TEXT, run_id TEXT,
    topic TEXT NOT NULL, agent_id TEXT, event_type TEXT NOT NULL, data JSONB,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS other_events_time ON other_events (occurred_at);
"""


class PostgresWriter:
    def __init__(self, conninfo: str | None = None, **params) -> None:
        self.conn = psycopg.connect(conninfo or "", **params)
        with self.conn.transaction():
            self.conn.execute(DDL)

    def write(self, rows: list[Row]) -> None:
        """Insert all rows in one transaction (all or nothing)."""
        by_table: dict[str, list[tuple]] = defaultdict(list)
        for row in rows:
            by_table[row.table].append(tuple(row.values.get(c) for c in COLUMNS[row.table]))
        with self.conn.transaction(), self.conn.cursor() as cur:
            for table, values in by_table.items():
                cols = COLUMNS[table]
                cur.executemany(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                    "ON CONFLICT (event_id) DO NOTHING", values)

    def close(self) -> None:
        self.conn.close()
