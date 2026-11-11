"""Kafka event -> table row (pure Python, no database).

Every event in Agent A's envelope (schema_version "1.0") becomes one row:

    agent_events  tool calls and session start/end from the agent topics
    scores        anomaly.scored     (every detector)
    alarms        alarm.raised       (DSPOT)
    labels        review.labelled    (review queue)
    other_events  anything else, e.g. decision.made, flags, toolset changes (raw JSON)

Both tool-call styles are understood: the mocks / Online Isolation Forest fields
(tool_name, duration_ms) and Agent A's own (name, latency_ms).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Row:
    table: str
    values: dict


def _time(value) -> datetime:
    if isinstance(value, str):
        try:
            t = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _agent_from_topic(topic: str) -> str | None:
    if topic.startswith("tool-calls."):
        return topic.split(".", 1)[1]
    if topic == "agent.events.v1":                     # Agent A's own topic name
        return "A"
    return None


def _float(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def to_row(topic: str, event: dict) -> Row:
    """Map one decoded message; raises ValueError if it is not an event envelope."""
    if not isinstance(event, dict) or not event.get("event_id") or not event.get("event_type"):
        raise ValueError("not an event envelope (event_id and event_type are required)")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    kind = event["event_type"]
    base = {"event_id": str(event["event_id"]), "occurred_at": _time(event.get("occurred_at")),
            "session_id": event.get("session_id"), "run_id": event.get("run_id")}
    agent = data.get("agent_id") or _agent_from_topic(topic)

    if kind.startswith("session.") or kind.startswith("tool_call."):
        return Row("agent_events", {
            **base, "topic": topic, "agent_id": agent, "event_type": kind, "sequence": event.get("sequence"),
            "tool_name": data.get("tool_name") or data.get("name"),
            "success": data.get("success", None if not kind.startswith("tool_call.") else kind != "tool_call.failed"),
            "duration_ms": _float(data.get("duration_ms", data.get("latency_ms"))),
            "session_call_index": data.get("session_call_index"),
            "arguments": json.dumps(data["arguments"]) if "arguments" in data else None,
            "data": json.dumps(data)})
    if kind == "anomaly.scored":
        return Row("scores", {**base, "agent_id": agent, "detector": data.get("detector"),
                              "model_version": data.get("model_version"),
                              "scored_event_id": data.get("scored_event_id"), "score": _float(data.get("score"))})
    if kind == "alarm.raised":
        return Row("alarms", {**base, "agent_id": agent, "detector": data.get("detector"),
                              "scored_event_id": data.get("scored_event_id"), "score": _float(data.get("score")),
                              "threshold": _float(data.get("threshold")), "q": _float(data.get("q"))})
    if kind == "review.labelled":
        return Row("labels", {**base, "agent_id": agent, "detector": data.get("detector"),
                              "scored_event_id": data.get("scored_event_id"), "verdict": data.get("verdict"),
                              "violation_type": data.get("violation_type"), "reviewer": data.get("reviewer")})
    return Row("other_events", {**base, "topic": topic, "agent_id": agent, "event_type": kind,
                                "data": json.dumps(data)})
