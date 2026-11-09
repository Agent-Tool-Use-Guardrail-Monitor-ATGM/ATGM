"""Session -> Kafka events in Agent A's envelope (datalens-agent, schema_version "1.0").

Per session: session.started, one tool_call.completed / tool_call.failed per call, session.ended.
The tool-call `data` carries the fields the Online Isolation Forest reads
(arguments, duration_ms, success, session_call_index, time_since_previous_call_ms).
Labels (normal / attack) are never put into events; they go to the ground-truth store only.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from atgm_mocks.domain.sessions import Session

SCHEMA_VERSION = "1.0"


def envelope(event_type: str, data: dict, *, run_id: str, session_id: str, sequence: int,
             occurred_at: datetime) -> dict:
    return {"schema_version": SCHEMA_VERSION, "event_id": str(uuid.uuid4()), "event_type": event_type,
            "occurred_at": occurred_at.isoformat(), "run_id": run_id, "session_id": session_id,
            "sequence": sequence, "request_id": None, "data": data}


def session_events(s: Session, run_id: str, start: datetime | None = None,
                   rng: random.Random | None = None) -> list[dict]:
    rng = rng or random.Random()
    t = start or datetime.now(timezone.utc)
    seq = 1
    common = {"run_id": run_id, "session_id": s.session_id}
    events = [envelope("session.started", {"agent_id": s.agent}, sequence=seq, occurred_at=t, **common)]
    previous_end = t
    for i, call in enumerate(s.calls, start=1):
        think = timedelta(milliseconds=rng.randint(300, 2500))      # LLM time between tool calls
        started = previous_end + think
        previous_end = started + timedelta(milliseconds=call.duration_ms)
        seq += 1
        events.append(envelope(
            "tool_call.completed" if call.success else "tool_call.failed",
            {"agent_id": s.agent, "tool_call_id": str(uuid.uuid4()), "tool_name": call.tool,
             "arguments": call.arguments, "duration_ms": call.duration_ms, "success": call.success,
             "session_call_index": i,
             "time_since_previous_call_ms": int((started - t).total_seconds() * 1000) if i == 1
             else int(think.total_seconds() * 1000)},
            sequence=seq, occurred_at=previous_end, **common))
    seq += 1
    events.append(envelope("session.ended", {"agent_id": s.agent, "call_count": len(s.calls)},
                           sequence=seq, occurred_at=previous_end + timedelta(milliseconds=500), **common))
    return events
