"""Parse ATGM tool-call and review-label events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


TOOL_CALL_TYPES = {"tool_call.completed", "tool_call.failed"}
LABEL_EVENT_TYPE = "review.labelled"


@dataclass(frozen=True)
class ToolCallEvent:
    event_id: str
    occurred_at: datetime
    session_id: str
    agent_id: str
    tool_name: str
    arguments: object


@dataclass(frozen=True)
class ReviewLabel:
    scored_event_id: str
    agent_id: str
    session_id: str
    verdict: str
    violation_type: str | None


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("occurred_at must be a non-empty string")

    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid occurred_at timestamp") from None

    if timestamp.tzinfo is None:
        raise ValueError("occurred_at must include a timezone")

    return timestamp


def parse_tool_call(event: dict, topic: str) -> ToolCallEvent:
    """Parse a completed or failed tool-call event."""
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")

    if event.get("event_type") not in TOOL_CALL_TYPES:
        raise ValueError("unsupported tool-call event type")

    data = event.get("data")
    if not isinstance(data, dict):
        raise ValueError("event data must be an object")

    event_id = event.get("event_id")
    session_id = event.get("session_id")
    agent_id = data.get("agent_id") or topic.rsplit(".", 1)[-1]
    tool_name = data.get("tool_name")

    if not event_id or not session_id or not agent_id or not tool_name:
        raise ValueError("tool-call event is missing a required identifier")

    if not isinstance(data.get("arguments"), (dict, list, str, int, float, bool, type(None))):
        raise ValueError("arguments must contain JSON-compatible data")

    return ToolCallEvent(
        event_id=str(event_id),
        occurred_at=_parse_timestamp(event.get("occurred_at")),
        session_id=str(session_id),
        agent_id=str(agent_id),
        tool_name=str(tool_name),
        arguments=data.get("arguments"),
    )


def parse_review_label(event: dict) -> ReviewLabel:
    """Parse a review.labelled event."""
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")

    if event.get("event_type") != LABEL_EVENT_TYPE:
        raise ValueError("unsupported review event type")

    data = event.get("data")
    if not isinstance(data, dict):
        raise ValueError("event data must be an object")

    scored_event_id = data.get("scored_event_id")
    agent_id = data.get("agent_id")
    session_id = event.get("session_id")
    verdict = data.get("verdict")
    violation_type = data.get("violation_type")

    if not scored_event_id or not agent_id or not session_id:
        raise ValueError("review label is missing a required identifier")

    if verdict not in {"attack", "false_alarm"}:
        raise ValueError("verdict must be 'attack' or 'false_alarm'")

    if verdict == "attack" and not violation_type:
        violation_type = "unknown"

    return ReviewLabel(
        scored_event_id=str(scored_event_id),
        agent_id=str(agent_id),
        session_id=str(session_id),
        verdict=verdict,
        violation_type=str(violation_type) if violation_type else None,
    )
