"""Allow-list detector: judges every tool call against the agent's toolset and the static policy.

Stateless checks (tool allowed, argument constraints) need only the call itself. Stateful checks (call
caps, ordering, saved text == scanned text) use a small per-session state built from the calls seen so
far. A session whose `session.started` was not seen (e.g. after a restart) is judged on the stateless
checks only, so a half-seen session never produces ordering false positives.

A call is judged exactly once: flat events (mock agents, Agent B) when they arrive; for the real Agent A
when its `tool_call.requested` arrives, i.e. before the tool ran. Its later `tool_call.completed` /
`tool_call.failed` only tell the detector whether the call succeeded (for the ordering rules).
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from allow_list.events import COMPLETION, ToolCall, call_shape, parse_call, payload
from allow_list.policy import load_policy
from allow_list.rules import CHECKS

logger = logging.getLogger(__name__)
_STATEFUL = {"precondition_missing", "unscanned_content"}


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: str
    detail: str


@dataclass
class _Session:
    complete: bool                                   # session.started was seen
    counts: dict = field(default_factory=dict)       # tool -> calls so far (failed ones included)
    done: set = field(default_factory=set)           # tools that completed successfully
    texts: dict = field(default_factory=dict)        # (tool, arg) -> values of successful calls
    pending: dict = field(default_factory=dict)      # tool_call_id -> tool, requested but not yet completed


def _event_day(event: dict) -> date:
    try:
        return datetime.fromisoformat(str(event["occurred_at"])).date()
    except (KeyError, ValueError):
        return datetime.now(timezone.utc).date()


class AllowListDetector:
    def __init__(self, policy: dict | None = None, max_sessions: int = 10_000) -> None:
        self.policy = policy or load_policy(None)
        self.max_sessions = max_sessions
        self.toolsets: dict[str, set[str]] = {}
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._warned: set[str] = set()

    # --- configuration and session lifecycle ---
    @property
    def version(self) -> str:
        return self.policy["version"]

    def set_toolset(self, agent: str, tools: list[str]) -> None:
        self.toolsets[agent] = set(tools)

    def start_session(self, session_id: str) -> None:
        self._sessions[session_id] = _Session(complete=True)
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)

    def end_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # --- the check ---
    def process(self, event: dict, agent: str) -> list[Violation]:
        shape = call_shape(event)
        if shape is None:
            return []
        state = self._state(event.get("session_id"))
        if shape == COMPLETION:                          # outcome of a call judged at its request
            self._complete(state, payload(event))
            return []

        call = parse_call(event)
        agent_policy = self.policy["agents"].get(agent, {})
        tool, label = call.tool, call.tool or "<unnamed tool>"
        found: list[tuple[str, str]] = []

        allowed = self.toolsets.get(agent)
        if allowed is None:
            if agent not in self._warned:
                self._warned.add(agent)
                logger.warning("no toolset-config for agent %s yet: tool allow-list not checked", agent)
        elif tool is None:
            found.append(("tool_not_allowed", f"a call without a resolvable tool name (agent {agent})"))
        elif tool not in allowed:
            found.append(("tool_not_allowed", f"{tool!r} is not in the current toolset of agent {agent}"))

        cap = agent_policy.get("max_calls", {}).get(tool)
        if cap is not None and state.counts.get(tool, 0) + 1 > cap:
            found.append(("max_calls_exceeded", f"{label} call {state.counts.get(tool, 0) + 1}, at most {cap} allowed"))

        missing = [t for t in agent_policy.get("requires_before", {}).get(tool, []) if t not in state.done]
        if missing:
            found.append(("precondition_missing", f"{label} needs {', '.join(missing)} first"))

        today, values = _event_day(event), call.values
        for spec in agent_policy.get("arguments", []):
            if tool in spec["tools"]:
                for arg in spec["args"]:
                    if arg in values:
                        found += CHECKS[spec["check"]](spec, values[arg], today)

        args = call.arguments or {}
        for spec in agent_policy.get("consistency", []):
            if tool == spec["tool"]:
                scanned = state.texts.get((spec["source"]["tool"], spec["source"]["arg"]), [])
                changed = [f for f in spec["fields"] if isinstance(args.get(f), str)
                           and scanned and not any(args[f] in text for text in scanned)]
                if changed:
                    found.append((spec["rule"], f"{', '.join(changed)} not covered by the {spec['source']['tool']} text"))

        self._record(state, agent_policy, call)
        severity = self.policy["severity"]
        return [Violation(rule, severity.get(rule, "medium"), detail) for rule, detail in found
                if state.complete or rule not in _STATEFUL]

    # --- internals ---
    def _state(self, session_id) -> _Session:
        if session_id is None:
            return _Session(complete=False)
        if session_id not in self._sessions:
            self.start_session(session_id)
            self._sessions[session_id].complete = False       # started before we were listening
        self._sessions.move_to_end(session_id)
        return self._sessions[session_id]

    @staticmethod
    def _record(state: _Session, agent_policy: dict, call: ToolCall) -> None:
        state.counts[call.tool] = state.counts.get(call.tool, 0) + 1
        if call.success is None:                         # requested: success is reported by the completion
            if call.call_id is not None:
                state.pending[call.call_id] = call.tool
            return
        if not call.success:
            return
        _mark_done(state, agent_policy, call.tool, call.arguments or {})

    def _complete(self, state: _Session, data: dict) -> None:
        tool = state.pending.pop(data.get("tool_call_id"), None)
        if tool is not None and data.get("status") == "completed":
            _mark_done(state, {}, tool, {})


def _mark_done(state: _Session, agent_policy: dict, tool: str | None, args: dict) -> None:
    if tool is None:
        return
    state.done.add(tool)
    for spec in agent_policy.get("consistency", []):
        src = spec["source"]
        if tool == src["tool"] and isinstance(args.get(src["arg"]), str):
            state.texts.setdefault((tool, src["arg"]), []).append(args[src["arg"]])
