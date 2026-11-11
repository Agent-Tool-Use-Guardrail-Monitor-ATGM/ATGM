from __future__ import annotations

import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"
TOOL_CALL_TYPES = {"tool_call.completed", "tool_call.failed"}
DETECTOR = "online_forest"
MODEL_VERSION = "oif-1"


def is_tool_call(event: dict) -> bool:
    return event.get("event_type") in TOOL_CALL_TYPES


def payload(event: dict) -> dict:
    data = event.get("data")
    return data if isinstance(data, dict) else event


def agent_id(event: dict, topic: str) -> str:
    return str(payload(event).get("agent_id") or topic.rsplit(".", 1)[-1])


def scored_event(event: dict, agent: str, score: float) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "event_type": "anomaly.scored",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "run_id": event.get("run_id"),
        "session_id": event.get("session_id"),
        "sequence": event.get("sequence"),
        "request_id": None,
        "data": {
            "scored_event_id": event["event_id"],
            "agent_id": agent,
            "detector": DETECTOR,
            "model_version": MODEL_VERSION,
            "score": round(score, 6),
        },
    }