"""Event helpers: Agent A's envelope (schema_version "1.0", body in `data`), same as the other services."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"
TOOL_CALL_TYPES = {"tool_call.completed", "tool_call.failed"}
DETECTOR = "allow_list"
EVENT_TYPE = "violation.flagged"


def is_tool_call(event: dict) -> bool:
    return event.get("event_type") in TOOL_CALL_TYPES


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
            "tool_name": p.get("tool_name"),
            "detector": DETECTOR,
            "policy_version": policy_version,
            "rule": violation.rule,
            "severity": violation.severity,
            "detail": violation.detail,
        },
    }
