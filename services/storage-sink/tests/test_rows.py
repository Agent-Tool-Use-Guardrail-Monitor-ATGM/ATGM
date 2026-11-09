import json
from datetime import datetime, timezone

import pytest

from storage_sink.domain.rows import to_row


def env(kind, data, **extra):
    return {"schema_version": "1.0", "event_id": "ev-1", "event_type": kind,
            "occurred_at": "2026-11-09T12:00:00+00:00", "run_id": "run-1", "session_id": "s-1",
            "sequence": 3, "request_id": None, "data": data, **extra}


def test_mock_tool_call():
    row = to_row("tool-calls.B", env("tool_call.completed", {
        "agent_id": "B", "tool_name": "tone_checker", "arguments": {"draft": "hi"}, "duration_ms": 27,
        "success": True, "session_call_index": 1, "time_since_previous_call_ms": 900}))
    v = row.values
    assert row.table == "agent_events"
    assert (v["agent_id"], v["tool_name"], v["success"], v["duration_ms"], v["session_call_index"]) == (
        "B", "tone_checker", True, 27.0, 1)
    assert v["occurred_at"] == datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    assert json.loads(v["arguments"]) == {"draft": "hi"} and v["sequence"] == 3


def test_agent_a_tool_call_style_and_agent_from_topic():
    row = to_row("agent.events.v1", env("tool_call.failed", {"name": "describe_columns", "latency_ms": 12,
                                                             "status": "rejected"}))
    v = row.values
    assert (v["agent_id"], v["tool_name"], v["duration_ms"], v["success"]) == ("A", "describe_columns", 12.0, False)
    assert v["arguments"] is None


def test_session_events():
    v = to_row("tool-calls.A", env("session.ended", {"agent_id": "A", "call_count": 5})).values
    assert v["event_type"] == "session.ended" and v["tool_name"] is None and v["success"] is None


def test_score_alarm_label():
    s = to_row("scores", env("anomaly.scored", {"scored_event_id": "x", "agent_id": "A", "detector": "d",
                                                "model_version": "v1", "score": "2.5"}))
    assert s.table == "scores" and s.values["score"] == 2.5 and s.values["detector"] == "d"
    a = to_row("alerts", env("alarm.raised", {"scored_event_id": "x", "agent_id": "A", "detector": "d",
                                              "score": 9, "threshold": 3.1, "q": 0.001}))
    assert a.table == "alarms" and (a.values["threshold"], a.values["q"]) == (3.1, 0.001)
    lab = to_row("labels", env("review.labelled", {"scored_event_id": "x", "detector": "d", "verdict": "attack",
                                                   "violation_type": "unsafe_args", "agent_id": "A",
                                                   "reviewer": "simulated"}))
    assert lab.table == "labels" and (lab.values["verdict"], lab.values["violation_type"]) == ("attack", "unsafe_args")


def test_unknown_event_types_are_kept_raw():
    row = to_row("flags", env("decision.made", {"decision": "review", "agent_id": "B"}))
    assert row.table == "other_events" and row.values["event_type"] == "decision.made"
    assert json.loads(row.values["data"])["decision"] == "review" and row.values["agent_id"] == "B"


def test_bad_or_missing_time_falls_back_to_now():
    before = datetime.now(timezone.utc)
    v = to_row("scores", env("anomaly.scored", {"score": 1}, occurred_at="yesterday")).values
    assert v["occurred_at"] >= before


@pytest.mark.parametrize("bad", ["text", {"duration_ms": 120}, {"event_id": "x"}, [1, 2]])
def test_non_envelope_messages_are_rejected(bad):
    with pytest.raises(ValueError):
        to_row("tool-calls.A", bad)
