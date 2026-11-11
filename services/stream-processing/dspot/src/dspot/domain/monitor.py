"""Alarm monitor: one DSPOT per (agent, detector) score stream, plus reviewer feedback.

This is the application logic of the DSPOT service, still without Kafka:

- Every (agent_id, detector) pair gets its own DSPOT, because each detector has its own
  score scale and each agent its own normal behaviour.
- Warm-up: the first `warmup` scores of a stream calibrate its DSPOT and never raise
  alarms. They are assumed to be normal (run the scenario generator with normal tasks
  only at the start).
- Alarms are remembered per session until a reviewer judges that session. The review queue
  is fed by ACI (one item per session), not by DSPOT, so an alarm flood cannot swamp the
  reviewers. A session verdict "normal" (false alarm) means every call in it was normal: all
  of the session's pending alarms are learned, with the moving average saved at alarm time.
  A verdict "attack" says some call was bad but not which, so nothing is learned.
"""
from __future__ import annotations

import math
from collections import OrderedDict, deque
from dataclasses import dataclass

from dspot.domain.dspot import DSPOT

RETRY_EVERY = 100   # if calibration fails (e.g. constant scores), retry after this many new scores


@dataclass(frozen=True)
class Score:
    ref: str            # id of the scored event (for session scores: the session's latest event)
    agent_id: str
    detector: str
    value: float        # higher = more suspicious
    session_id: str | None = None


@dataclass(frozen=True)
class Alarm:
    score: Score
    threshold: float
    q: float


@dataclass(frozen=True)
class Verdict:
    session_id: str
    false_alarm: bool   # True: the reviewer judged the whole session normal


class AlarmMonitor:
    def __init__(self, q: float = 1e-3, level: float = 0.98, depth: int = 20,
                 warmup: int = 3_000, max_pending: int = 10_000) -> None:
        """max_pending: sessions with unanswered alarms that are remembered (oldest forgotten)."""
        DSPOT(q=q, level=level, depth=depth)          # validate the parameters early
        if warmup <= depth:
            raise ValueError("warmup must be larger than depth")
        self.q, self.level, self.depth = q, level, depth
        self.warmup = warmup
        self.max_pending = max_pending
        self.detectors: dict[tuple[str, str], DSPOT] = {}
        self._warming: dict[tuple[str, str], deque[float]] = {}
        self._since_attempt: dict[tuple[str, str], int] = {}
        # session -> [(stream key, score, moving average at alarm time), ...]
        self._pending: OrderedDict[str, list[tuple[tuple[str, str], float, float]]] = OrderedDict()

    def on_score(self, s: Score) -> Alarm | None:
        if not math.isfinite(s.value):
            raise ValueError(f"score must be finite, got {s.value!r}")
        key = (s.agent_id, s.detector)
        dspot = self.detectors.get(key)
        if dspot is None:
            self._warm_up(key, s.value)
            return None
        decision = dspot.update(s.value)
        if not decision.alarm:
            return None
        if s.session_id is not None:
            self._pending.setdefault(s.session_id, []).append((key, s.value, dspot.local_mean))
            self._pending.move_to_end(s.session_id)
            if len(self._pending) > self.max_pending:
                self._pending.popitem(last=False)     # forget the oldest unanswered session
        return Alarm(s, decision.threshold, self.q)

    def on_verdict(self, v: Verdict) -> int:
        """Apply a reviewer's session verdict; returns the number of alarms learned as normal."""
        pending = self._pending.pop(v.session_id, [])
        if not v.false_alarm:
            return 0
        for key, value, mean in pending:
            self.detectors[key].confirm_normal(value, local_mean=mean)
        return len(pending)

    def status(self) -> dict[str, str]:
        out = {f"{a}/{d}": f"warming up {len(b)}/{self.warmup}" for (a, d), b in self._warming.items()}
        out.update({f"{a}/{d}": f"threshold {m.threshold:.4g}" for (a, d), m in self.detectors.items()})
        return out

    def _warm_up(self, key: tuple[str, str], value: float) -> None:
        buf = self._warming.setdefault(key, deque(maxlen=self.warmup))
        buf.append(value)
        if len(buf) < self.warmup:
            return
        since = self._since_attempt.get(key)
        if since is not None and since < RETRY_EVERY:
            self._since_attempt[key] = since + 1
            return
        dspot = DSPOT(q=self.q, level=self.level, depth=self.depth)
        try:
            dspot.initialize(list(buf))
        except ValueError:                            # e.g. almost constant scores: no tail yet
            self._since_attempt[key] = 1
            return
        self.detectors[key] = dspot
        del self._warming[key]
        self._since_attempt.pop(key, None)
