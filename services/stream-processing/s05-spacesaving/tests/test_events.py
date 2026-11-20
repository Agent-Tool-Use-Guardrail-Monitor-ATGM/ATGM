from datetime import datetime, timezone

import pytest

from spacesaving.adapters.events import (
    parse_review_label,
    parse_tool_call,
)


def test_parse_tool_call():
    event = {
        "event_id": "call-123",
        "event_type": "tool_call.completed",
        "occurred_at": "2026-11-19T10:00:00+00:00",
        "session_id": "session-1",
        "data": {
            "agent_id": "A",
            "tool_name": "web_search",
            "arguments": {"query": "weather"},
        },
    }

    result = parse_tool_call(event, "tool-calls.A")

    assert result.event_id == "call-123"
    assert result.agent_id == "A"
    assert result.tool_name == "web_search"
    assert result.arguments == {"query": "weather"}
    assert result.occurred_at.tzinfo == timezone.utc


def test_agent_id_falls_back_to_topic():
    event = {
        "event_id": "call-123",
        "event_type": "tool_call.failed",
        "occurred_at": "2026-11-19T10:00:00+00:00",
        "session_id": "session-1",
        "data": {"tool_name": "calculator", "arguments": {}},
    }

    result = parse_tool_call(event, "tool-calls.B")

    assert result.agent_id == "B"


def test_parse_false_alarm_label():
    event = {
        "event_type": "review.labelled",
        "session_id": "session-1",
        "data": {
            "scored_event_id": "call-123",
            "agent_id": "A",
            "verdict": "false_alarm",
            "violation_type": None,
        },
    }

    result = parse_review_label(event)

    assert result.scored_event_id == "call-123"
    assert result.verdict == "false_alarm"
    assert result.violation_type is None


def test_parse_attack_label():
    event = {
        "event_type": "review.labelled",
        "session_id": "session-1",
        "data": {
            "scored_event_id": "call-123",
            "agent_id": "A",
            "verdict": "attack",
            "violation_type": "unsafe_args",
        },
    }

    result = parse_review_label(event)

    assert result.verdict == "attack"
    assert result.violation_type == "unsafe_args"


def test_invalid_verdict_is_rejected():
    event = {
        "event_type": "review.labelled",
        "session_id": "session-1",
        "data": {
            "scored_event_id": "call-123",
            "agent_id": "A",
            "verdict": "unknown",
        },
    }

    with pytest.raises(ValueError):
        parse_review_label(event)


def test_timestamp_without_timezone_is_rejected():
    event = {
        "event_id": "call-123",
        "event_type": "tool_call.completed",
        "occurred_at": "2026-11-19T10:00:00",
        "session_id": "session-1",
        "data": {
            "agent_id": "A",
            "tool_name": "web_search",
            "arguments": {},
        },
    }

    with pytest.raises(ValueError):
        parse_tool_call(event, "tool-calls.A")
