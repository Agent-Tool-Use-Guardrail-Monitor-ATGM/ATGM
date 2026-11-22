import pytest

from allow_list.detector import Violation
from allow_list.events import (COMPLETION, FLAT, REQUESTED, agent_id, call_shape, flagged_event, is_tool_call,
                               parse_call, parse_toolset_update)


def test_toolset_update_shapes():
    assert parse_toolset_update({"agent_id": "B", "allowed_tools": ["a", "b"]}) == {"B": ["a", "b"]}
    assert parse_toolset_update({"data": {"agent_id": "B", "tools": ["a"]}}) == {"B": ["a"]}
    assert parse_toolset_update({"allowed_tools": ["a"]}, key="A") == {"A": ["a"]}
    assert parse_toolset_update({"toolsets": {"A": ["x"], "B": {"allowed_tools": ["y"]}}}) == {"A": ["x"], "B": ["y"]}
    assert parse_toolset_update({"data": {"agents": {"A": ["x"]}}}) == {"A": ["x"]}
    assert parse_toolset_update({"agent_id": "B", "allowed_tools": []}) == {"B": []}      # revoke everything


@pytest.mark.parametrize("bad", [{}, {"agent_id": "B"}, {"agent_id": "B", "allowed_tools": "save_draft"},
                                 {"agent_id": "B", "allowed_tools": [1]}, {"toolsets": {"A": 3}}])
def test_bad_toolset_updates_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_toolset_update(bad)


def test_agent_id_falls_back_to_the_topic():
    assert agent_id({"data": {"agent_id": "B"}}, "tool-calls.A") == "B"
    assert agent_id({"data": {}}, "tool-calls.A") == "A"
    assert is_tool_call({"event_type": "tool_call.failed"}) and not is_tool_call({"event_type": "session.ended"})


def test_flagged_event_envelope():
    event = {"event_id": "e-1", "run_id": "r", "session_id": "s", "sequence": 7,
             "data": {"agent_id": "B", "tool_name": "save_draft"}}
    out = flagged_event(event, "B", Violation("recipient_not_allowed", "high", "why"), "allow-list-1")
    assert out["schema_version"] == "1.0" and out["event_type"] == "violation.flagged"
    assert (out["run_id"], out["session_id"], out["sequence"], out["request_id"]) == ("r", "s", 7, None)
    assert out["data"] == {"flagged_event_id": "e-1", "agent_id": "B", "tool_name": "save_draft",
                           "detector": "allow_list", "policy_version": "allow-list-1",
                           "rule": "recipient_not_allowed", "severity": "high", "detail": "why"}
    assert out["event_id"] and out["occurred_at"]


def test_call_shapes():
    flat = {"event_type": "tool_call.completed", "data": {"tool_name": "t", "arguments": {}, "success": True}}
    flat_failed_no_name = {"event_type": "tool_call.failed", "data": {"arguments": {"a": 1}, "success": False}}
    requested = {"event_type": "tool_call.requested", "data": {"name": "t", "features": {}, "tool_call_id": "c"}}
    outcome = {"event_type": "tool_call.completed", "data": {"status": "completed", "tool_call_id": "c"}}
    assert [call_shape(e) for e in (flat, flat_failed_no_name, requested, outcome)] == [
        FLAT, FLAT, REQUESTED, COMPLETION]
    assert [call_shape(e) for e in ({"event_type": "session.ended"}, {"event_type": "model_call.completed"}, {})] == [
        None, None, None]
    assert is_tool_call(requested) and is_tool_call(outcome) and not is_tool_call({"event_type": "session.started"})


def test_parse_flat_call():
    c = parse_call({"event_type": "tool_call.completed", "data": {"tool_name": "find_contact", "tool_call_id": "c",
                                                                  "arguments": {"name": "Anna"}, "success": True}})
    assert (c.tool, c.arguments, c.features, c.success, c.call_id) == ("find_contact", {"name": "Anna"}, None, True, "c")
    assert c.values == {"name": "Anna"}
    failed = parse_call({"event_type": "tool_call.failed", "data": {"tool_name": "t", "arguments": {}}})
    assert failed.success is False                                         # no `success` field: the type decides
    assert parse_call({"event_type": "tool_call.completed", "data": {"arguments": []}}).tool is None


def test_parse_requested_call_has_features_but_no_arguments():
    c = parse_call({"event_type": "tool_call.requested", "data": {
        "name": "aggregate_statistics", "kind": "numerical", "tool_call_id": "c",
        "features": {"operation": "sum", "column_count": 1}}})
    assert (c.tool, c.arguments, c.success, c.call_id) == ("aggregate_statistics", None, None, "c")
    assert c.values == {"operation": "sum", "column_count": 1}
    unnamed = parse_call({"event_type": "tool_call.requested", "data": {"kind": "unknown", "features": None}})
    assert unnamed.tool is None and unnamed.values == {}


def test_flagged_event_names_the_tool_of_a_requested_call():
    event = {"event_id": "e", "session_id": "s", "data": {"name": "aggregate_statistics"}}
    assert flagged_event(event, "A", Violation("r", "low", "d"), "v")["data"]["tool_name"] == "aggregate_statistics"
    assert flagged_event({"event_id": "e", "data": {}}, "A", Violation("r", "low", "d"), "v")["data"]["tool_name"] is None
