from collections import OrderedDict
from dataclasses import dataclass


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
    def __init__(self, memory: ToolCallMemory, flag_types=(), limit=200_000):
        self.memory = memory
        self.flag_types = set(flag_types)
        self.limit = limit
        self.seen = OrderedDict()

    def from_alarm(self, partition: int, event: dict):
        if event.get("event_type") != "alarm.raised":
            return None
        data = event.get("data") or {}
        call_id = data.get("scored_event_id")
        if self._already_counted(f"alarm:{call_id}"):
            return None                       # another detector already alarmed on this call
        call = self.memory.find(call_id)
        agent = data.get("agent_id") or (call.agent if call else "unknown")
        tool = call.tool if call else "unknown"
        return Violation(agent, call.partition if call else partition, f"anomaly:{tool}")

    def from_flag(self, partition: int, event: dict):
        if event.get("event_type") not in self.flag_types:
            return None
        if self._already_counted(f"flag:{event.get('event_id')}"):
            return None
        data = event.get("data") or {}
        call = self.memory.find(data.get("tool_call_event_id") or data.get("scored_event_id"))
        agent = data.get("agent_id") or (call.agent if call else "unknown")
        tool = data.get("tool_name") or (call.tool if call else "unknown")
        violation_type = data.get("violation_type") or "violation"
        return Violation(agent, call.partition if call else partition, f"{violation_type}:{tool}")

    def _already_counted(self, key: str) -> bool:
        if key in self.seen:
            return True
        bounded_put(self.seen, key, None, self.limit)
        return False