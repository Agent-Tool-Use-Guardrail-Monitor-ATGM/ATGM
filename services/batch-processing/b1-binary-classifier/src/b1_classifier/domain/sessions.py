"""Collects each session's tool calls from the stream until the session ends.

The `data` of tool_call events are sorted by session_call_index so the model sees the same input as in training.
Sessions whose start we did not see (scorer started mid-session) are skipped.
"""
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class FinishedSession:
    session_id: str
    agent_id: str
    calls: list[dict]
    ended_event_id: str


class SessionBuffer:
    def __init__(self, max_open: int = 10_000):
        self._open: OrderedDict[str, list[dict]] = OrderedDict()
        self._max_open = max_open

    def add(self, event: dict) -> FinishedSession | None:
        """Returns the finished session on session.ended, otherwise None."""
        session = event.get("session_id")
        event_type = event.get("event_type", "")
        if not session:
            return None

        if event_type == "session.started":
            self._open[session] = []
            if len(self._open) > self._max_open:      
                self._open.popitem(last=False)
        elif event_type.startswith("tool_call.") and session in self._open:
            self._open[session].append(event["data"])
        elif event_type == "session.ended" and session in self._open:
            calls = sorted(self._open.pop(session), key=lambda call: call["session_call_index"])
            agent = (event.get("data") or {}).get("agent_id") or (calls[0]["agent_id"] if calls else "")
            return FinishedSession(session, agent, calls, event["event_id"])
        return None

    @property
    def open_sessions(self) -> int:
        return len(self._open)