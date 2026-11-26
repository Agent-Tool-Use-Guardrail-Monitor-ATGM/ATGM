from b3_markov.domain.sessions import build_sessions
from helpers import FULL, SHORT, events


def test_build_sorts_calls_and_reads_category():
    ev = events("a", SHORT, "adversarial", "unsafe_args")
    ev[1], ev[3] = ev[3], ev[1]
    sessions, _ = build_sessions(ev)
    assert sessions[0].tools == SHORT and sessions[0].category == "adversarial" and sessions[0].attack_type == "unsafe_args"


def test_duplicate_events_are_dropped():
    sessions, report = build_sessions(events("a", SHORT) + events("a", SHORT))
    assert len(sessions) == 1 and sessions[0].tools == SHORT and report["duplicate_events"] == 6


def test_incomplete_or_miscounted_sessions_are_skipped():
    ev = events("a", SHORT, ended=False) + events("b", SHORT, count=9) + events("c", SHORT)
    sessions, report = build_sessions(ev)
    assert [s.session_id for s in sessions] == ["c"] and sorted(report["incomplete_sessions"]) == ["a", "b"]


def test_zero_call_session_is_kept():
    sessions, _ = build_sessions(events("z", []))
    assert sessions[0].tools == []


def test_build_sessions_keeps_arguments_and_timestamps():
    ev = events("a", SHORT)
    ev[1]["occurred_at"] = "2026-11-19T07:20:12+00:00"
    ev[1]["data"]["arguments"] = {"name": "Tom"}
    (s,), _ = build_sessions(ev)
    assert s.calls[0].tool == "find_contact" and s.calls[0].args == {"name": "Tom"} and s.calls[0].occurred_at.startswith("2026-11-19")
    assert s.calls[1].args == {}


def test_failed_call_is_a_call_but_requested_is_not():
    ev = events("a", SHORT)
    ev[2]["event_type"] = "tool_call.failed"
    ev.insert(1, {"event_id": "req", "event_type": "tool_call.requested", "session_id": "a",
                  "data": {"agent_id": "B", "tool_name": "find_contact", "session_call_index": 1}})
    (s,), _ = build_sessions(ev)
    assert s.tools == SHORT
