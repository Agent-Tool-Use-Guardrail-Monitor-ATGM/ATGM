import pytest

from allow_list.detector import Violation
from allow_list.events import agent_id, flagged_event, is_tool_call, parse_toolset_update


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
