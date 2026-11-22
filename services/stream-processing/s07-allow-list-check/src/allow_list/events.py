"""Event helpers: Agent A's envelope (schema_version "1.0", body in `data`), same as the other services.

Two shapes of tool-call message are understood on `tool-calls.A` / `tool-calls.B`:

    flat       one `tool_call.completed` / `tool_call.failed` event per call, with `tool_name`, `arguments`
               and `success` in `data` (the mock agents, Agent B).
    run-events the real Agent A (`agent-run-events-v2`): `tool_call.requested` carries the tool `name` and
               coarse `features` of the arguments (never the arguments themselves, only their hash);
               `tool_call.completed` / `tool_call.failed` carry only `tool_call_id` and `status`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"
TOOL_CALL_TYPES = {"tool_call.requested", "tool_call.completed", "tool_call.failed"}
DETECTOR = "allow_list"
EVENT_TYPE = "violation.flagged"

FLAT, REQUESTED, COMPLETION = "flat", "requested", "completion"


@dataclass(frozen=True)
class ToolCall:
    """One proposed tool call, whichever shape it arrived in."""
    tool: str | None             # None: the tool name could not be resolved (the runner publishes no name)
    arguments: dict | None       # raw arguments; None when only `features` are published
    features: dict | None        # coarse description of the arguments (run-events shape)
    success: bool | None         # None until the completion event (run-events shape)
    call_id: str | None

    @property
    def values(self) -> dict:
        """What the argument checks look at: the arguments if present, else the features."""
        return self.arguments if self.arguments is not None else (self.features or {})


def call_shape(event: dict) -> str | None:
    """FLAT, REQUESTED, COMPLETION or None (not a tool-call event).

    A completed/failed event is FLAT if it names its tool or carries arguments, otherwise it only
    reports the outcome of an earlier `tool_call.requested` (COMPLETION).
    """
    kind = event.get("event_type")
    if kind == "tool_call.requested":
        return REQUESTED
    if kind in ("tool_call.completed", "tool_call.failed"):
        data = payload(event)
        return FLAT if "tool_name" in data or "arguments" in data else COMPLETION
    return None


def is_tool_call(event: dict) -> bool:
    return call_shape(event) is not None


def parse_call(event: dict) -> ToolCall:
    """The ToolCall of a FLAT or REQUESTED event."""
    data = payload(event)
    call_id = data.get("tool_call_id")
    if call_shape(event) == REQUESTED:
        features = data.get("features")
        return ToolCall(data.get("name") or None, None, features if isinstance(features, dict) else {},
                        None, call_id)
    arguments = data.get("arguments")
    return ToolCall(str(data["tool_name"]) if data.get("tool_name") else None,
                    arguments if isinstance(arguments, dict) else {}, None,
                    bool(data.get("success", event.get("event_type") != "tool_call.failed")), call_id)


def payload(event: dict) -> dict:
    data = event.get("data")
    return data if isinstance(data, dict) else event


def agent_id(event: dict, topic: str) -> str:
    return str(payload(event).get("agent_id") or topic.rsplit(".", 1)[-1])


def parse_toolset_update(event: dict, key: str | None = None) -> dict[str, list[str]]:
    """Agent -> allowed tools from one `toolset-config` message. Accepted shapes (plain or in `data`):

        {"agent_id": "B", "allowed_tools": ["find_contact", ...]}      one agent ("tools" also accepted;
                                                                        the message key is used if agent_id is missing)
        {"toolsets": {"A": [...], "B": {"allowed_tools": [...]}}}      several agents ("agents" also accepted)

    The newest message for an agent replaces the previous one. Raises ValueError if nothing usable is found.
    """
    body = payload(event)
    update: dict[str, list[str]] = {}
    many = body.get("toolsets") or body.get("agents")
    if isinstance(many, dict):
        for agent, value in many.items():
            update[str(agent)] = _tool_list(value)
    else:
        agent = body.get("agent_id") or key
        if not agent:
            raise ValueError("toolset-config message has no agent_id")
        update[str(agent)] = _tool_list(body)
    return update


def _tool_list(value) -> list[str]:
    if isinstance(value, dict):
        value = value.get("allowed_tools", value.get("tools"))
    if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
        raise ValueError("allowed tools must be a list of tool names")
    return list(value)


def flagged_event(event: dict, agent: str, violation, policy_version: str) -> dict:
    """The `violation.flagged` envelope for one rule broken by one tool call."""
    p = payload(event)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "event_type": EVENT_TYPE,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "run_id": event.get("run_id"),
        "session_id": event.get("session_id"),
        "sequence": event.get("sequence"),
        "request_id": None,
        "data": {
            "flagged_event_id": event.get("event_id"),
            "agent_id": agent,
            "tool_name": p.get("tool_name") or p.get("name"),
            "detector": DETECTOR,
            "policy_version": policy_version,
            "rule": violation.rule,
            "severity": violation.severity,
            "detail": violation.detail,
        },
    }
