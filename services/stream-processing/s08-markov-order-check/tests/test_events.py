from conftest import feed, make_pipeline, session_events, v2_session

from markov_order_check.events import CALL_DETECTOR, SESSION_DETECTOR, agent_id, call_from_result


def _session_event(outputs):
    return next(o.event for o in outputs if o.kind == "session")


def test_flat_completed_and_failed_each_give_one_call(model_b):
    events = session_events("B", ["find_contact", "get_current_datetime", "get_free_slots"], failed={2})
    out = feed(make_pipeline(model_b), events)
    assert _session_event(out)["data"]["n_calls"] == 3


def test_v2_requested_result_pair_counts_once_with_requested_name(model_a):
    out = feed(make_pipeline(model_a), v2_session(["inspect_dataset", "finalize_statistics"]), agent="A")
    data = _session_event(out)["data"]
    assert data["n_calls"] == 2
    assert data["n_unseen"] == 0  # names came from the requested events, so the normal path is known


def test_call_without_name_is_unk(model_a):
    out = feed(make_pipeline(model_a), v2_session(["aggregate_statistics", None]), agent="A")
    data = _session_event(out)["data"]
    assert data["n_calls"] == 2
    seen_next = {data["worst_transition"]["next"]} | {
        o.event["data"]["transition"]["next"] for o in out if o.kind == "call"}
    assert "<UNK>" in seen_next


def test_model_call_events_give_no_call(model_a):
    events = v2_session(["inspect_dataset"])
    assert sum(e["event_type"].startswith("model_call") for e in events) == 1
    out = feed(make_pipeline(model_a), events, agent="A")
    assert _session_event(out)["data"]["n_calls"] == 1


def test_agent_id_from_payload_or_topic():
    assert agent_id({"data": {"agent_id": "A"}}, "tool-calls.B") == "A"
    assert agent_id({"data": {}}, "tool-calls.B") == "B"


def test_failed_result_without_success_field_is_unsuccessful():
    call = call_from_result({"event_type": "tool_call.failed", "data": {"status": "failed"}}, "x")
    assert call.success is False and call.tool_name == "x"


def test_envelope_matches_s04_core(model_b):
    out = feed(make_pipeline(model_b), session_events("B", ["save_draft", "find_contact"]))
    for o in out:
        e = o.event
        assert set(e) == {"schema_version", "event_id", "event_type", "occurred_at", "run_id", "session_id",
                          "sequence", "request_id"} | {"data"}
        assert e["event_type"] == "anomaly.scored" and e["request_id"] is None
        assert list(e["data"])[:5] == ["scored_event_id", "agent_id", "detector", "model_version", "score"]
        assert e["data"]["detector"] == (CALL_DETECTOR if o.kind == "call" else SESSION_DETECTOR)
