"""Mock scorer: a simple online "how unusual is this?" score per tool call and per session end.

Stands in for the real detectors (Online Isolation Forest, Markov check, ...) until they
publish anomaly.scored events. Higher = more suspicious. Per agent it learns, from everything
it sees (fine for a mock, not for production: no poisoning protection):

    tool call:   -log P(tool | previous tool)            (unseen tools and orders are surprising)
                 + 0.5 * z-score of the argument length   (only above the usual length)
                 + 3 if the arguments look like a secret  (password, card number, path traversal)
                 + 1 if the call failed
    session end: -log P(end | last tool) + |z-score of the number of calls|   (skipped steps)
"""
from __future__ import annotations

import json
import math
import re
from collections import OrderedDict, defaultdict

_SECRET = re.compile(r"password|\b\d{4} \d{4} \d{4} \d{4}\b|\.\./", re.IGNORECASE)
START, END = "<start>", "<end>"


class _Running:
    """Running mean and standard deviation (Welford)."""

    def __init__(self) -> None:
        self.n, self.mean, self.m2 = 0, 0.0, 0.0

    def z(self, x: float) -> float:
        if self.n < 2:
            return 0.0
        sd = math.sqrt(self.m2 / (self.n - 1))
        return (x - self.mean) / sd if sd > 0 else 0.0

    def add(self, x: float) -> None:
        self.n += 1
        d = x - self.mean
        self.mean += d / self.n
        self.m2 += d * (x - self.mean)


class MockScorer:
    def __init__(self, max_sessions: int = 10_000) -> None:
        self.max_sessions = max_sessions
        self._pairs: dict[str, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
        self._from: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._tools: dict[str, set[str]] = defaultdict(set)
        self._arg_len: dict[tuple[str, str], _Running] = defaultdict(_Running)
        self._calls: dict[str, _Running] = defaultdict(_Running)
        self._last: OrderedDict[str, str] = OrderedDict()          # session -> last tool

    def score(self, event: dict) -> float | None:
        """Score one envelope; None for events that are not scored (session.started, others)."""
        kind, data, session = event.get("event_type"), event.get("data") or {}, event.get("session_id")
        agent = str(data.get("agent_id", "?"))
        if kind == "session.started":
            self._remember(session, START)
            return None
        if kind in ("tool_call.completed", "tool_call.failed"):
            tool = str(data.get("tool_name"))
            prev = self._last.get(session, START)
            args = json.dumps(data.get("arguments", {}), sort_keys=True)
            score = (self._surprise(agent, prev, tool)
                     + 0.5 * max(self._arg_len[(agent, tool)].z(len(args)), 0.0)
                     + (3.0 if _SECRET.search(args) else 0.0)
                     + (0.0 if data.get("success", True) else 1.0))
            self._learn(agent, prev, tool)
            self._arg_len[(agent, tool)].add(len(args))
            self._remember(session, tool)
            return score
        if kind == "session.ended":
            prev = self._last.pop(session, START)
            n = float(data.get("call_count", 0))
            score = self._surprise(agent, prev, END) + abs(self._calls[agent].z(n))
            self._learn(agent, prev, END)
            self._calls[agent].add(n)
            return score
        return None

    def _surprise(self, agent: str, prev: str, nxt: str) -> float:
        vocab = len(self._tools[agent]) + 2                         # known tools + <end> + one unseen
        p = (self._pairs[agent][(prev, nxt)] + 1) / (self._from[agent][prev] + vocab)
        return -math.log(p)

    def _learn(self, agent: str, prev: str, nxt: str) -> None:
        self._pairs[agent][(prev, nxt)] += 1
        self._from[agent][prev] += 1
        if nxt != END:
            self._tools[agent].add(nxt)

    def _remember(self, session, tool: str) -> None:
        self._last[session] = tool
        self._last.move_to_end(session)
        while len(self._last) > self.max_sessions:
            self._last.popitem(last=False)
