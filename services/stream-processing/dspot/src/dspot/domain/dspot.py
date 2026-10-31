"""DSPOT: SPOT that follows drift (Siffer et al., KDD 2017, Algorithm 2).

When the normal level of the scores slowly shifts (e.g. agents get busier), a fixed
threshold either floods reviewers with alarms or goes blind. DSPOT therefore runs SPOT
on the *deviation* from the recent normal level:

    M_i  = mean of the last `depth` normal scores (a moving window)
    x'_i = x_i - M_i            -> classified by an ordinary SPOT

Alarms do not enter the window, so attacks cannot drag the local level up either.
Reviewer-confirmed false alarms do (`confirm_normal`), as in SPOT.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from dspot.domain.spot import SPOT, Decision, Kind


class DSPOT:
    """Alarm threshold with false-alarm probability `q`, relative to a moving average."""

    def __init__(self, q: float = 1e-4, level: float = 0.98, depth: int = 50) -> None:
        if depth < 1:
            raise ValueError("depth must be at least 1")
        self.depth = depth
        self.spot = SPOT(q=q, level=level)
        self._window: deque[float] = deque(maxlen=depth)
        self._sum = 0.0

    @property
    def local_mean(self) -> float:
        return self._sum / len(self._window)

    @property
    def threshold(self) -> float | None:
        """Current alarm threshold in the units of the raw scores."""
        if self.spot.threshold is None:
            return None
        return self.local_mean + self.spot.threshold

    def initialize(self, scores) -> float:
        """Fill the window with the first `depth` scores, calibrate SPOT on the rest."""
        x = np.asarray(scores, dtype=float).ravel()
        if np.any(~np.isfinite(x)):
            raise ValueError("initial scores must be finite")
        if x.size <= self.depth:
            raise ValueError("need more initial scores than depth")
        self._window.clear()
        self._sum = 0.0
        for v in x[:self.depth]:
            self._push(v)
        deviations = []
        for v in x[self.depth:]:
            deviations.append(v - self.local_mean)
            self._push(v)
        self.spot.initialize(deviations)
        return self.threshold

    def update(self, score: float) -> Decision:
        """Classify one raw score; normal scores and peaks move the window."""
        if self.spot.threshold is None:
            raise RuntimeError("call initialize() before update()")
        x = float(score)
        if not np.isfinite(x):
            raise ValueError("score must be finite")
        mean = self.local_mean
        d = self.spot.update(x - mean)
        if d.kind is not Kind.ALARM:
            self._push(x)
        return Decision(x, mean + d.threshold, d.kind)

    def confirm_normal(self, score: float, local_mean: float | None = None) -> None:
        """Learn an alarm that a reviewer confirmed as a false alarm.

        The deviation is measured from `local_mean`, the moving average at the time of
        the alarm. Reviewers answer late, after the window has moved on, so pass the
        value saved with the alarm; without it the current average is used.
        """
        if self.spot.threshold is None:
            raise RuntimeError("call initialize() before confirm_normal()")
        x = float(score)
        if not np.isfinite(x):
            raise ValueError("score must be finite")
        mean = self.local_mean if local_mean is None else float(local_mean)
        self.spot.confirm_normal(x - mean)
        self._push(x)

    def run(self, scores) -> list[Decision]:
        return [self.update(s) for s in scores]

    def _push(self, x: float) -> None:
        if len(self._window) == self.depth:
            self._sum -= self._window[0]
        self._window.append(x)
        self._sum += x
