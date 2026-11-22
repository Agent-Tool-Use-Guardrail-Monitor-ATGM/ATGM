"""Sessions: building them from raw batch events (training). Live buffering lives in the stream pipeline (spec Sec. 14).

A Session holds only what the Markov chain needs: the ordered tool names. Category / label are kept
for selecting the normal sessions and for evaluation.
"""
from dataclasses import dataclass, field


@dataclass
class Call:
    tool: str
    args: dict = field(default_factory=dict)
    occurred_at: str | None = None    # ISO timestamp of the tool_call event


def to_call(data: dict) -> Call:
    return Call(data["tool_name"], data.get("arguments") or {}, data.get("occurred_at"))


@dataclass
class Session:
    session_id: str
    tools: list[str]
    category: str = "normal"          # session.started data.category: normal | adversarial
    attack_type: str | None = None
    label: str | None = None          # behaviour label: compliant | violating (None if unknown)
    calls: list[Call] = field(default_factory=list)

    def __post_init__(self):
        if not self.calls:            # sequence-only construction (tests, tool lists)
            self.calls = [Call(tool) for tool in self.tools]


@dataclass
class FinishedSession:
    session_id: str
    agent_id: str
    calls: list[dict]
    ended_event_id: str

    @property
    def tools(self) -> list[str]:
        return [call["tool_name"] for call in self.calls]

    @property
    def call_objects(self) -> list[Call]:
        return [to_call(call) for call in self.calls]


CALL_EVENTS = ("tool_call.completed", "tool_call.failed")     # a failed call is a call too (spec Sec. 15.2)


def build_sessions(events: list[dict]) -> tuple[list[Session], dict]:
    """Groups raw events into complete sessions.

    Duplicated events (same event_id) are dropped. Sessions without session.ended, or whose number
    of tool calls differs from the declared call_count (e.g. a truncated file), are skipped.
    Returns (sessions, report) with the counts of what was dropped.
    """
    seen: set[str] = set()
    started: dict[str, dict] = {}
    calls: dict[str, list[dict]] = {}
    ended: dict[str, int | None] = {}
    duplicates = 0
    for event in events:
        event_id = event.get("event_id")
        if event_id in seen:
            duplicates += 1
            continue
        seen.add(event_id)
        session, kind = event.get("session_id"), event.get("event_type", "")
        if not session:
            continue
        if kind == "session.started":
            started[session] = event.get("data") or {}
        elif kind in CALL_EVENTS:
            calls.setdefault(session, []).append({**event["data"], "occurred_at": event.get("occurred_at")})
        elif kind == "session.ended":
            ended[session] = (event.get("data") or {}).get("call_count")

    sessions, incomplete = [], []
    for session, info in started.items():
        ordered = sorted(calls.get(session, []), key=lambda call: call["session_call_index"])
        if session not in ended or (ended[session] is not None and ended[session] != len(ordered)):
            incomplete.append(session)
            continue
        sessions.append(Session(session, [call["tool_name"] for call in ordered],
                                info.get("category", "normal"), info.get("attack_type"),
                                calls=[to_call(call) for call in ordered]))
    return sessions, {"duplicate_events": duplicates, "incomplete_sessions": incomplete}
