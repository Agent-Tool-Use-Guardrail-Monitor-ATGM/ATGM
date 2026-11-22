import pytest

from kswin.adapters.events import parse_score, parse_tool_call


def make_tool_event(event_type="tool_call.completed", arguments=None, success=True):
    return {
        "event_id": "event-1",
        "event_type": event_type,
        "data": {
            "agent_id": "A",
            "arguments": arguments or {},
            "success": success,
        },
    }


def make_score_event(score=0.75):
    return {
        "event_id": "score-1",
        "event_type": "anomaly.scored",
        "data": {
            "agent_id": "B",
            "score": score,
        },
    }


def test_parse_successful_tool_call():
    result = parse_tool_call(
        make_tool_event(arguments={"query": "hello"}),
        "tool-calls.A",
    )

    assert result.agent_id == "A"
    assert result.argument_length > 0
    assert result.failure_rate == 0.0


def test_parse_failed_tool_call():
    result = parse_tool_call(
        make_tool_event("tool_call.failed", success=False),
        "tool-calls.A",
    )

    assert result.failure_rate == 1.0


def test_agent_id_falls_back_to_topic():
    event = make_tool_event()
    event["data"].pop("agent_id")

    result = parse_tool_call(event, "tool-calls.B")

    assert result.agent_id == "B"


def test_parse_anomaly_score():
    result = parse_score(make_score_event(0.75), "scores")

    assert result.agent_id == "B"
    assert result.anomaly_score == 0.75


def test_reject_non_numeric_score():
    with pytest.raises(ValueError):
        parse_score(make_score_event("high"), "scores")


def test_reject_infinite_score():
    with pytest.raises(ValueError):
        parse_score(make_score_event(float("inf")), "scores")


def test_reject_wrong_event_type():
    with pytest.raises(ValueError):
        parse_tool_call(
            {"event_id": "x", "event_type": "other", "data": {}},
            "tool-calls.A",
        )
