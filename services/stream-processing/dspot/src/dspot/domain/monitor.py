"""Alarm monitor: one DSPOT per (agent, detector) score stream, plus reviewer feedback.

This is the application logic of the DSPOT service, still without Kafka:

- Every (agent_id, detector) pair gets its own DSPOT, because each detector has its own
  score scale and each agent its own normal behaviour.
- Warm-up: the first `warmup` scores of a stream calibrate its DSPOT and never raise
  alarms. They are assumed to be normal (run the scenario generator with normal tasks
  only at the start).
- Alarms are remembered until a reviewer answers. A "false alarm" verdict is learned
  with the moving average saved at alarm time; an "attack" verdict is never learned.
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


@dataclass(frozen=True)
class Alarm:
    score: Score
    threshold: float
    q: float


@dataclass(frozen=True)
class Verdict:
    ref: str
    detector: str
    false_alarm: bool


class AlarmMonitor:
    def __init__(self, q: float = 1e-3, level: float = 0.98, depth: int = 20,
                 warmup: int = 3_000, max_pending: int = 10_000) -> None:
        DSPOT(q=q, level=level, depth=depth)          # validate the parameters early
        if warmup <= depth:
            raise ValueError("warmup must be larger than depth")
        self.q, self.level, self.depth = q, level, depth
        self.warmup = warmup
        self.max_pending = max_pending
        self.detectors: dict[tuple[str, str], DSPOT] = {}
        self._warming: dict[tuple[str, str], deque[float]] = {}
        self._since_attempt: dict[tuple[str, str], int] = {}
        # (ref, detector) -> (stream key, score, moving average at alarm time)
        self._pending: OrderedDict[tuple[str, str], tuple[tuple[str, str], float, float]] = OrderedDict()

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
        self._pending[(s.ref, s.detector)] = (key, s.value, dspot.local_mean)
        if len(self._pending) > self.max_pending:
            self._pending.popitem(last=False)         # forget the oldest unanswered alarm
        return Alarm(s, decision.threshold, self.q)

    def on_verdict(self, v: Verdict) -> bool:
        """Apply a reviewer verdict; True if the score was learned as normal."""
        pending = self._pending.pop((v.ref, v.detector), None)
        if pending is None or not v.false_alarm:
            return False
        key, value, mean = pending
        self.detectors[key].confirm_normal(value, local_mean=mean)
        return True

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
