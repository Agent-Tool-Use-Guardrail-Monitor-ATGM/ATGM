"""Envelope helpers: parsing tool-call events (spec Sec. 3.1) and building anomaly.scored (Sec. 7).

The output envelope is the one S04 (Online Forest) publishes, with S08's extra
fields inside ``data`` after the shared core.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"
SESSION_DETECTOR = "markov"
CALL_DETECTOR = "markov_order"
CALL_RESULT_TYPES = {"tool_call.completed", "tool_call.failed"}
ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "atgm:s08-markov-order-check")


def payload(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else event


def agent_id(event: dict[str, Any], topic: str) -> str:
    return str(payload(event).get("agent_id") or topic.rsplit(".", 1)[-1])


def event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or "")


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Call:
    """One tool call, counted once at its result event."""

    tool_name: str | None
    call_index: int | None
    sequence: int | None
    success: bool
    arguments: dict[str, Any] | None
    tool_call_id: str | None
    event_id: str | None
    occurred_at: str | None
    run_id: str | None


def tool_name(data: dict[str, Any]) -> str | None:
    """Flat payload: data.tool_name; agent-run-events-v2: data.name on tool_call.requested."""
    name = data.get("tool_name") or data.get("name")
    return str(name) if name else None


def call_from_result(event: dict[str, Any], requested_name: str | None) -> Call:
    data = payload(event)
    args = data.get("arguments")
    success = data.get("success")
    if success is None:
        success = event_type(event) == "tool_call.completed" and data.get("status", "completed") == "completed"
    return Call(
        tool_name=tool_name(data) or requested_name,
        call_index=_int(data.get("session_call_index")),
        sequence=_int(event.get("sequence")),
        success=bool(success),
        arguments=args if isinstance(args, dict) else None,
        tool_call_id=str(data["tool_call_id"]) if data.get("tool_call_id") else None,
        event_id=event.get("event_id"),
        occurred_at=event.get("occurred_at"),
        run_id=event.get("run_id"),
    )


def deterministic_id(*parts: Any) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, "|".join("" if p is None else str(p) for p in parts)))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def latency_ms(scored_event_occurred_at: str | None, produced_at: str) -> int | None:
    if not scored_event_occurred_at:
        return None
    try:
        a = datetime.fromisoformat(scored_event_occurred_at.replace("Z", "+00:00"))
        b = datetime.fromisoformat(produced_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((b - a).total_seconds() * 1000)


def scored_event(
    *,
    detector: str,
    agent: str,
    session_id: str,
    run_id: str | None,
    sequence: int | None,
    scored_event_id: str | None,
    model_version: str,
    score: float,
    id_parts: tuple[Any, ...],
    extra: dict[str, Any],
    produced_at: str | None = None,
    scored_event_occurred_at: str | None = None,
) -> dict[str, Any]:
    """anomaly.scored in S04's envelope (S04 events.scored_event) plus S08 extension fields."""
    produced_at = produced_at or now_iso()
    data: dict[str, Any] = {
        "scored_event_id": scored_event_id,
        "agent_id": agent,
        "detector": detector,
        "model_version": model_version,
        "score": round(float(score), 6),
    }
    data.update(extra)
    data["scored_event_occurred_at"] = scored_event_occurred_at
    data["latency_ms"] = latency_ms(scored_event_occurred_at, produced_at)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": deterministic_id(*id_parts),
        "event_type": "anomaly.scored",
        "occurred_at": produced_at,
        "run_id": run_id,
        "session_id": session_id,
        "sequence": sequence,
        "request_id": None,
        "data": data,
    }
