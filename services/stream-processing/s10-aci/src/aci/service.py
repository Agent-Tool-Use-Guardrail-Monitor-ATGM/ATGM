"""ACI service logic: one triage decision per session, learning from audited sessions.

Per session it keeps the highest anomaly score of the chosen detectors. When the agent
reports `session.ended`, it waits `grace` seconds (late scores), then decides
pass / flag / review and publishes `decision.made`:

    every decision                   -> topic `flags`
    review decisions and audits      -> topic `review-queue` (answered by the reviewer)

Audits: a random `audit_rate` share of ALL sessions is sent to review, whatever the decision.
The trackers learn only from these audited verdicts. Learning from the review band alone would
be biased (it only contains sessions that were already uncertain); a random sample keeps the
coverage guarantees meaningful for all sessions. It is also the "sampled review" safeguard
of the design (A5).

Time is passed in by the caller, so tests and offline runs need no clock.
"""
from __future__ import annotations

import logging
import random
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from aci.domain.triage import REVIEW, ConformalTriage

log = logging.getLogger("aci")
DETECTOR = "aci"


class Sink(Protocol):
    def send(self, topic: str, key: str, value: dict) -> None: ...


@dataclass
class _Session:
    agent: str | None = None
    run_id: str | None = None
    score: float = 0.0
    ended_event_id: str | None = None
    due: float | None = None
    scores: int = 0


@dataclass
class Counts:
    decisions: dict = field(default_factory=lambda: {"pass": 0, "flag": 0, "review": 0})
    audits: int = 0
    learned: int = 0


class ACIService:
    def __init__(self, triage: ConformalTriage, sink: Sink, detectors: set[str] | None = None,
                 audit_rate: float = 0.1, grace: float = 2.0, rng: random.Random | None = None,
                 decision_topic: str = "flags", review_topic: str = "review-queue",
                 max_sessions: int = 50_000) -> None:
        if not 0 <= audit_rate <= 1 or grace < 0:
            raise ValueError("need audit_rate in [0, 1] and grace >= 0")
        self.triage, self.sink, self.detectors = triage, sink, detectors
        self.audit_rate, self.grace, self.rng = audit_rate, grace, rng or random.Random()
        self.decision_topic, self.review_topic, self.max_sessions = decision_topic, review_topic, max_sessions
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._audited: OrderedDict[str, tuple[str, float]] = OrderedDict()   # session -> (agent, score)
        self.counts = Counts()

    def handle(self, msg: dict, now: float, topic: str = "") -> None:
        """Process one decoded message; malformed messages are logged and skipped."""
        if not isinstance(msg, dict) or not isinstance(msg.get("data"), dict) or not msg.get("session_id"):
            return
        kind, data, sid = msg.get("event_type"), msg["data"], str(msg["session_id"])
        try:
            if kind == "anomaly.scored":
                if self.detectors is None or data.get("detector") in self.detectors:
                    s = self._session(sid)
                    s.score = max(s.score, float(data["score"]))
                    s.scores += 1
                    s.agent = s.agent or data.get("agent_id")
            elif kind == "session.ended":
                s = self._session(sid)
                s.agent = data.get("agent_id") or s.agent or _agent_from_topic(topic)
                s.run_id, s.ended_event_id, s.due = msg.get("run_id"), msg.get("event_id"), now + self.grace
            elif kind == "review.labelled" and data.get("detector") == DETECTOR:
                audited = self._audited.pop(sid, None)
                if audited is not None and data.get("verdict") in ("attack", "false_alarm"):
                    self.triage.learn(audited[0], audited[1], violating=data["verdict"] == "attack")
                    self.counts.learned += 1
        except (KeyError, TypeError, ValueError) as e:
            log.warning("skipped %s message %s: %s", kind, msg.get("event_id"), e)

    def tick(self, now: float) -> int:
        """Decide every session whose grace period is over; returns the number decided."""
        due = [sid for sid, s in self._sessions.items() if s.due is not None and s.due <= now]
        for sid in due:
            self._decide(sid, self._sessions.pop(sid))
        return len(due)

    def _decide(self, sid: str, s: _Session) -> None:
        agent = s.agent or "?"
        t = self.triage.decide(agent, s.score)
        audit = self.rng.random() < self.audit_rate
        event = {
            "schema_version": "1.0", "event_id": str(uuid.uuid4()), "event_type": "decision.made",
            "occurred_at": datetime.now(timezone.utc).isoformat(), "run_id": s.run_id, "session_id": sid,
            "sequence": None, "request_id": None,
            "data": {"scored_event_id": s.ended_event_id or sid, "agent_id": agent, "detector": DETECTOR,
                     "decision": t.decision, "prediction_set": list(t.prediction_set),
                     "session_score": s.score, "scores_seen": s.scores, "pass_up_to": t.q_compliant,
                     "flag_from": t.flag_from, "audit": audit}}
        self.sink.send(self.decision_topic, agent, event)
        if t.decision == REVIEW or audit:
            self.sink.send(self.review_topic, agent, event)
        if audit:
            self._audited[sid] = (agent, s.score)
            self.counts.audits += 1
            while len(self._audited) > self.max_sessions:
                self._audited.popitem(last=False)
        self.counts.decisions[t.decision] += 1

    def _session(self, sid: str) -> _Session:
        s = self._sessions.get(sid)
        if s is None:
            s = self._sessions[sid] = _Session()
            while len(self._sessions) > self.max_sessions:      # sessions that never ended
                self._sessions.popitem(last=False)
        return s


def _agent_from_topic(topic: str) -> str | None:
    if topic.startswith("tool-calls."):
        return topic.split(".", 1)[1]
    return "A" if topic == "agent.events.v1" else None
