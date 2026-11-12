"""Agent A (DataLens) telemetry -> ATGM tool-call events. Pure Python, no Kafka.

DataLens publishes to `agent.events.v1` (payload_version agent-run-events-v2):

    tool_call.requested   tool_call_id, kind, name, arguments_sha256, features{...}
    tool_call.completed   tool_call_id, status, policy_evaluation           (no tool name, no duration)
    tool_call.failed      tool_call_id, status, reason, policy_evaluation
    session.started / session.ended / model_call.*

The ATGM detectors expect one event per finished tool call with the tool name and its features
(see services/stream-processing/README.md). This translator:

- remembers each `tool_call.requested` and emits nothing for it;
- on `tool_call.completed` / `tool_call.failed`, joins the request by `tool_call_id` and emits
  one ATGM tool call: tool_name, arguments (= DataLens' categorical features; raw arguments are
  never published by DataLens), duration_ms (requested -> finished), success,
  session_call_index, time_since_previous_call_ms;
- passes every other event through, with `data.agent_id = "A"`, and adds `call_count` to
  `session.ended`;
- drops duplicates (DataLens delivers at least once) and derives output ids from the source
  `event_id`, so a replay produces the same ids and the storage sink stores them once.
"""
from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone

AGENT_ID = "A"
SCHEMA_VERSION = "1.0"
_NAMESPACE = uuid.UUID("6d0f0d1e-5a6c-4c2e-9b7a-2f3d1c4e5a60")    # fixed: same source id -> same output id


def _time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _ms(later: datetime | None, earlier: datetime | None) -> int:
    if later is None or earlier is None:
        return 0
    return max(0, round((later - earlier).total_seconds() * 1000))


@dataclass
class _Session:
    started: datetime | None = None
    last_end: datetime | None = None
    calls: int = 0
    pending: dict[str, dict] = field(default_factory=dict)       # tool_call_id -> request info


class Translator:
    def __init__(self, max_sessions: int = 10_000, max_seen: int = 200_000) -> None:
        self.max_sessions, self.max_seen = max_sessions, max_seen
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._seen: OrderedDict[str, None] = OrderedDict()              # recent source event ids

    def translate(self, event: dict) -> dict | None:
        """The ATGM event for one DataLens event, or None (requests, duplicates, non-envelopes)."""
        if not isinstance(event, dict) or not event.get("event_id") or not event.get("session_id"):
            raise ValueError("not a DataLens event envelope")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        kind, sid, eid = event.get("event_type"), str(event["session_id"]), str(event["event_id"])
        if eid in self._seen:
            return None                                           # at-least-once redelivery
        self._seen[eid] = None
        if len(self._seen) > self.max_seen:
            self._seen.popitem(last=False)
        s = self._session(sid)
        when = _time(event.get("occurred_at"))

        if kind == "session.started":
            s.started = s.last_end = when
            return self._out(event, kind, {**data, "agent_id": AGENT_ID})

        if kind == "tool_call.requested":
            s.pending[str(data.get("tool_call_id"))] = {
                "name": data.get("name"), "kind": data.get("kind"), "features": data.get("features") or {},
                "arguments_sha256": data.get("arguments_sha256"), "at": when}
            return None

        if kind in ("tool_call.completed", "tool_call.failed"):
            req = s.pending.pop(str(data.get("tool_call_id")), None) or {"features": {}}
            requested_at = req.get("at") or when
            s.calls += 1
            out = {
                "agent_id": AGENT_ID,
                "tool_call_id": data.get("tool_call_id"),
                "tool_name": req.get("name") or "unknown",
                "tool_kind": req.get("kind"),
                "arguments": req["features"],
                "arguments_sha256": req.get("arguments_sha256"),
                "duration_ms": _ms(when, requested_at),
                "success": kind == "tool_call.completed",
                "status": data.get("status"),
                "reason": data.get("reason"),
                "policy_evaluation": data.get("policy_evaluation"),
                "session_call_index": s.calls,
                "time_since_previous_call_ms": _ms(requested_at, s.last_end or s.started),
            }
            s.last_end = when or s.last_end
            return self._out(event, kind, out)

        if kind == "session.ended":
            self._sessions.pop(sid, None)
            return self._out(event, kind, {**data, "agent_id": AGENT_ID, "call_count": s.calls})

        return self._out(event, kind, {**data, "agent_id": AGENT_ID})     # model_call.* and others

    def _session(self, sid: str) -> _Session:
        s = self._sessions.get(sid)
        if s is None:
            s = self._sessions[sid] = _Session()
            while len(self._sessions) > self.max_sessions:            # sessions that never ended
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(sid)
        return s

    @staticmethod
    def _out(source: dict, kind: str, data: dict) -> dict:
        return {"schema_version": SCHEMA_VERSION,
                "event_id": str(uuid.uuid5(_NAMESPACE, str(source["event_id"]))),
                "event_type": kind, "occurred_at": source.get("occurred_at"),
                "run_id": source.get("run_id"), "session_id": source.get("session_id"),
                "sequence": source.get("sequence"), "request_id": source.get("request_id"),
                "data": {**data, "source_event_id": source["event_id"]}}
