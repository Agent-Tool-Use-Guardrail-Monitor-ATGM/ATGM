"""Parse tool-call and anomaly-score events for S06."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


TOOL_CALL_TYPES = {"tool_call.completed", "tool_call.failed"}
SCORE_EVENT_TYPE = "anomaly.scored"


@dataclass(frozen=True)
class ToolCallObservation:
    event_id: str
    agent_id: str
    argument_length: float
    failure_rate: float
    source_event: dict[str, Any]


@dataclass(frozen=True)
class ScoreObservation:
    event_id: str
    agent_id: str
    anomaly_score: float
    source_event: dict[str, Any]


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")

    if not isinstance(data, dict):
        raise ValueError("event data must be an object")

    return data


def _agent_id(data: dict[str, Any], topic: str) -> str:
    agent = data.get("agent_id") or topic.rsplit(".", 1)[-1]

    if not agent:
        raise ValueError("event is missing agent_id")

    return str(agent)


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")

    number = float(value)

    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")

    return number


def parse_tool_call(
    event: dict[str, Any], topic: str
) -> ToolCallObservation:
    """Extract argument length and binary failure observation."""
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")

    event_type = event.get("event_type")

    if event_type not in TOOL_CALL_TYPES:
        raise ValueError("unsupported tool-call event type")

    data = _payload(event)
    event_id = event.get("event_id")

    if not event_id:
        raise ValueError("tool-call event is missing event_id")

    arguments = data.get("arguments", {})

    try:
        serialized = json.dumps(
            arguments,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
    except (TypeError, ValueError):
        raise ValueError("arguments must be JSON-serializable") from None

    success = data.get("success")

    if event_type == "tool_call.failed":
        failure_rate = 1.0
    elif isinstance(success, bool):
        failure_rate = 0.0 if success else 1.0
    else:
        failure_rate = 0.0

    return ToolCallObservation(
        event_id=str(event_id),
        agent_id=_agent_id(data, topic),
        argument_length=float(len(serialized)),
        failure_rate=failure_rate,
        source_event=event,
    )


def parse_score(
    event: dict[str, Any], topic: str
) -> ScoreObservation:
    """Extract a numeric anomaly score from an anomaly.scored event."""
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")

    if event.get("event_type") != SCORE_EVENT_TYPE:
        raise ValueError("unsupported score event type")

    data = _payload(event)
    event_id = event.get("event_id")

    if not event_id:
        raise ValueError("score event is missing event_id")

    return ScoreObservation(
        event_id=str(event_id),
        agent_id=_agent_id(data, topic),
        anomaly_score=_finite_number(data.get("score"), "score"),
        source_event=event,
    )
