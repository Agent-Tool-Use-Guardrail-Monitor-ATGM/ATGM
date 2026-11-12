import pytest

from agent_a_adapter.translate import Translator

RUN, SID = "93901cd7-55d7-46fc-9b62-be0a4c66e199", "baeb9a78-b64e-4948-8021-681759461d1e"


def ev(n, kind, data, t, sid=SID):
    """A DataLens event as documented in KAFKA_DEVELOPER_HANDOFF.md."""
    return {"schema_version": "1.0", "event_id": f"ev-{sid}-{n}", "event_type": kind,
            "occurred_at": f"2026-11-12T10:00:{t:06.3f}Z", "run_id": RUN, "session_id": sid,
            "sequence": n, "request_id": None,
            "data": {"payload_version": "agent-run-events-v2", **data}}


def session():
    feats = {"argument_shape": "valid", "dataset_selection": "selected", "column_count": 3, "operation": "mean"}
    return [
        ev(1, "session.started", {"conversation_id": "c1", "dataset_count": 1, "versions": {}}, 0.0),
        ev(2, "model_call.completed", {"model_call_id": "m1", "attempt_index": 1, "latency_ms": 900,
                                       "usage": {"input_tokens": 10}}, 1.0),
        ev(3, "tool_call.requested", {"tool_call_id": "t1", "kind": "numerical", "name": "inspect_dataset",
                                      "arguments_sha256": "ab" * 32, "features": {"argument_shape": "valid"}}, 1.5),
        ev(4, "tool_call.completed", {"tool_call_id": "t1", "status": "completed"}, 1.62),
        ev(5, "tool_call.requested", {"tool_call_id": "t2", "kind": "numerical", "name": "aggregate_statistics",
                                      "arguments_sha256": "cd" * 32, "features": feats}, 3.0),
        ev(6, "tool_call.failed", {"tool_call_id": "t2", "status": "rejected", "reason": "policy_denied"}, 3.25),
        ev(7, "session.ended", {"lifecycle": "finished", "outcome": "incomplete", "verified_result_count": 1}, 4.0),
    ]


def run(events, tr=None):
    tr = tr or Translator()
    return [out for e in events if (out := tr.translate(e)) is not None]


def test_requests_and_results_are_joined_into_one_tool_call():
    out = run(session())
    assert [e["event_type"] for e in out] == ["session.started", "model_call.completed",
                                              "tool_call.completed", "tool_call.failed", "session.ended"]
    first, second = out[2]["data"], out[3]["data"]
    assert (first["tool_name"], first["success"], first["duration_ms"], first["session_call_index"]) == (
        "inspect_dataset", True, 120, 1)
    assert first["time_since_previous_call_ms"] == 1500            # from session start to the request
    assert first["arguments"] == {"argument_shape": "valid"}       # categorical features, no raw arguments
    assert (second["tool_name"], second["success"], second["status"], second["reason"]) == (
        "aggregate_statistics", False, "rejected", "policy_denied")
    assert second["duration_ms"] == 250 and second["session_call_index"] == 2
    assert second["time_since_previous_call_ms"] == 1380           # end of call 1 (1.62 s) -> request 2 (3.0 s)


def test_every_event_is_in_the_atgm_envelope_for_agent_a():
    out = run(session())
    for o, src in zip(out, [session()[i] for i in (0, 1, 3, 5, 6)]):
        assert o["schema_version"] == "1.0" and o["data"]["agent_id"] == "A"
        assert (o["session_id"], o["run_id"], o["sequence"]) == (SID, RUN, src["sequence"])
        assert o["data"]["source_event_id"] == src["event_id"] and o["event_id"] != src["event_id"]
    assert out[-1]["data"]["call_count"] == 2 and out[-1]["data"]["outcome"] == "incomplete"


def test_redelivered_events_are_dropped_and_replays_give_the_same_ids():
    events = session()
    once = run(events)
    twice = run(events + events[2:])                                 # Kafka redelivers part of the session
    assert [e["event_id"] for e in twice] == [e["event_id"] for e in once]
    assert [e["event_id"] for e in run(events)] == [e["event_id"] for e in once]   # fresh translator, same ids


def test_result_without_its_request_is_still_reported():
    out = run([ev(1, "session.started", {}, 0.0), ev(2, "tool_call.completed", {"tool_call_id": "x"}, 1.0)])
    assert out[1]["data"]["tool_name"] == "unknown" and out[1]["data"]["arguments"] == {}


def test_sessions_are_independent_and_memory_is_bounded():
    tr = Translator(max_sessions=3)
    for i in range(10):
        tr.translate(ev(1, "session.started", {}, 0.0, sid=f"s{i}"))
    assert len(tr._sessions) == 3
    a = run([ev(1, "session.started", {}, 0.0, sid="a"), ev(2, "tool_call.requested", {"tool_call_id": "t", "name": "x"}, 1.0, sid="a"),
             ev(1, "session.started", {}, 0.0, sid="b"), ev(3, "tool_call.completed", {"tool_call_id": "t"}, 2.0, sid="a")])
    assert a[-1]["data"]["tool_name"] == "x" and a[-1]["data"]["session_call_index"] == 1


@pytest.mark.parametrize("bad", ["text", {"event_type": "session.started"}, {"event_id": "x", "data": {}}])
def test_non_envelopes_are_rejected(bad):
    with pytest.raises(ValueError):
        Translator().translate(bad)
