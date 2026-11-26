"""Turns Kafka events into violations for the top-k monitor.

A violation is "something went wrong", counted per agent, for example:
    anomaly:save_draft        a DSPOT alarm on a save_draft call       (alerts)
    allow_list:send_email     a rule violation from S07                (flags, violation.flagged)
    aci:flag                  ACI flagged a session                    (flags, decision.made)

Alarms and rule violations only contain the id of the event they are about, so
recent tool calls are remembered to find the tool and the partition.
"""
from collections import OrderedDict
from dataclasses import dataclass

OWN_DETECTOR = "topk_counts"     # our own scores: alarms on them must not be counted again


@dataclass(frozen=True)
class ToolCall:
    agent: str
    tool: str
    partition: int


@dataclass(frozen=True)
class Violation:
    agent: str
    partition: int
    item: str
    event: dict          # the input event, to copy run_id / session_id into our output


def bounded_put(store: OrderedDict, key, value, limit: int):
    store[key] = value
    if len(store) > limit:
        store.popitem(last=False)


class ToolCallMemory:
    """Remembers the last `limit` tool calls (and session ends) by event id."""

    def __init__(self, limit=200_000):
        self.limit = limit
        self.calls = OrderedDict()

    def remember(self, topic: str, partition: int, event: dict):
        event_type = event.get("event_type", "")
        if not event.get("event_id"):
            return
        if not (event_type.startswith("tool_call.") or event_type == "session.ended"):
            return
        data = event.get("data") or {}
        agent = data.get("agent_id") or topic.split(".")[-1]
        tool = data.get("tool_name") or data.get("name")
        if not tool:
            tool = "<session>" if event_type == "session.ended" else "unknown"
        bounded_put(self.calls, event["event_id"], ToolCall(agent, tool, partition), self.limit)

    def find(self, event_id):
        return self.calls.get(event_id)


class ViolationReader:
    def __init__(self, memory: ToolCallMemory, limit=200_000):
        self.memory = memory
        self.limit = limit
        self.seen = OrderedDict()

    def read(self, partition: int, event: dict):
        """Returns a Violation, or None if the event is not one we count."""
        event_type = event.get("event_type")
        data = event.get("data") or {}
        if event_type == "alarm.raised" and data.get("detector") != OWN_DETECTOR:
            return self._about_call(partition, event, data.get("scored_event_id"), "anomaly", "alarm")
        if event_type == "violation.flagged":
            rule = data.get("rule") or "violation"
            return self._about_call(partition, event, data.get("flagged_event_id"), rule, "flag")
        if event_type == "decision.made" and data.get("decision") == "flag":
            return Violation(data.get("agent_id") or "unknown", partition, "aci:flag", event)
        return None

    def _about_call(self, partition, event, call_id, kind, source):
        if self._already_counted(f"{source}:{call_id}:{kind}"):
            return None                       # e.g. two detectors alarmed on the same call
        data = event.get("data") or {}
        call = self.memory.find(call_id)
        agent = data.get("agent_id") or (call.agent if call else "unknown")
        tool = data.get("tool_name") or (call.tool if call else "unknown")
        return Violation(agent, call.partition if call else partition, f"{kind}:{tool}", event)

    def _already_counted(self, key: str) -> bool:
        if key in self.seen:
            return True
        bounded_put(self.seen, key, None, self.limit)
        return False
