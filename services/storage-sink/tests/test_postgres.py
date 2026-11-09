"""Runs against a real PostgreSQL if ATGM_TEST_PG is set (a conninfo string), else skipped.

    ATGM_TEST_PG="host=localhost dbname=analytics_db user=analytics_svc password=..." pytest
"""
import os

import pytest

from storage_sink.domain.rows import to_row

PG = os.environ.get("ATGM_TEST_PG")
pytestmark = pytest.mark.skipif(not PG, reason="set ATGM_TEST_PG to run against PostgreSQL")


def env(event_id, kind, data):
    return {"schema_version": "1.0", "event_id": event_id, "event_type": kind,
            "occurred_at": "2026-11-09T12:00:00+00:00", "session_id": "s-1", "run_id": "r", "data": data}


@pytest.fixture
def writer():
    from storage_sink.adapters.postgres import PostgresWriter
    w = PostgresWriter(PG)
    with w.conn.transaction():
        for t in ("agent_events", "scores", "alarms", "labels", "other_events"):
            w.conn.execute(f"DELETE FROM {t} WHERE event_id LIKE 'test-%'")
    yield w
    w.close()


def test_rows_are_stored_once_even_if_delivered_twice(writer):
    rows = [to_row("tool-calls.A", env("test-1", "tool_call.completed", {"agent_id": "A", "tool_name": "t",
                                                                          "arguments": {"a": 1}})),
            to_row("scores", env("test-2", "anomaly.scored", {"agent_id": "A", "detector": "d", "score": 1.5})),
            to_row("alerts", env("test-3", "alarm.raised", {"agent_id": "A", "detector": "d", "score": 9,
                                                            "threshold": 3, "q": 0.001})),
            to_row("labels", env("test-4", "review.labelled", {"detector": "d", "verdict": "attack"})),
            to_row("flags", env("test-5", "decision.made", {"decision": "flag"}))]
    writer.write(rows)
    writer.write(rows)                                    # redelivery
    c = writer.conn
    assert c.execute("SELECT count(*) FROM agent_events WHERE event_id LIKE 'test-%'").fetchone()[0] == 1
    assert c.execute("SELECT arguments->>'a' FROM agent_events WHERE event_id = 'test-1'").fetchone()[0] == "1"
    assert c.execute("SELECT score FROM scores WHERE event_id = 'test-2'").fetchone()[0] == 1.5
    assert c.execute("SELECT threshold FROM alarms WHERE event_id = 'test-3'").fetchone()[0] == 3
    assert c.execute("SELECT verdict FROM labels WHERE event_id = 'test-4'").fetchone()[0] == "attack"
    assert c.execute("SELECT data->>'decision' FROM other_events WHERE event_id = 'test-5'").fetchone()[0] == "flag"
