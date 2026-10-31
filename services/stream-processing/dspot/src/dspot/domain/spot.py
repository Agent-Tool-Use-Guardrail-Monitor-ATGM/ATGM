"""SPOT: streaming peaks-over-threshold alarms (Siffer et al., KDD 2017, Algorithm 1).

Calibration on an initial batch of (mostly normal) scores:
    t    = empirical `level` quantile of the batch (e.g. 0.98)
    peaks = scores above t, stored as excesses (score - t)
    GPD fit on the excesses, then the alarm threshold z_q from `tail_quantile`.

For every new score x:
    x > z_q        -> alarm; NOT added to the model, so attacks cannot raise the threshold
    t < x <= z_q   -> peak: excess stored, GPD refitted, z_q updated
    otherwise      -> normal: only counted

Known behaviour: because alarms are excluded, the scores that would reveal an early
underestimate of the tail are never seen, so the threshold can stay too low. On normal
and heavy-tailed test streams this gives roughly 2-3x the requested false-alarm rate:
SPOT errs on the cautious side. Learning from every score would fix the accuracy, but
would let attackers push the threshold up by sending high scores (poisoning).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from dspot.domain.gpd import GPDFit, fit_gpd, tail_quantile

MIN_INITIAL_PEAKS = 10


class Kind(str, Enum):
    ALARM = "alarm"
    PEAK = "peak"
    NORMAL = "normal"


@dataclass(frozen=True)
class Decision:
    score: float
    threshold: float      # alarm threshold z_q the score was compared against
    kind: Kind

    @property
    def alarm(self) -> bool:
        return self.kind is Kind.ALARM


class SPOT:
    """Alarm threshold with false-alarm probability `q` on normal scores."""

    def __init__(self, q: float = 1e-4, level: float = 0.98) -> None:
        if not 0 < level < 1:
            raise ValueError("level must be in (0, 1)")
        if not 0 < q < 1 - level:
            raise ValueError("q must be in (0, 1 - level): the alarm level must lie above t")
        self.q = q
        self.level = level
        self._peaks: list[float] = []
        self.t: float | None = None
        self.n = 0
        self.fit: GPDFit | None = None
        self.threshold: float | None = None

    @property
    def n_peaks(self) -> int:
        return len(self._peaks)

    def initialize(self, scores) -> float:
        """Calibrate on an initial batch and return the first alarm threshold."""
        x = np.asarray(scores, dtype=float).ravel()
        if np.any(~np.isfinite(x)):
            raise ValueError("initial scores must be finite")
        self.t = float(np.quantile(x, self.level))
        excesses = x[x > self.t] - self.t
        if excesses.size < MIN_INITIAL_PEAKS:
            raise ValueError(
                f"only {excesses.size} initial peaks above t; need {MIN_INITIAL_PEAKS} "
                "(use a larger initial batch or a lower level)")
        self._peaks = excesses.tolist()
        self.n = x.size
        self._refit()
        return self.threshold

    def update(self, score: float) -> Decision:
        """Classify one new score and update the model if it is a peak."""
        if self.threshold is None:
            raise RuntimeError("call initialize() before update()")
        x = float(score)
        if not np.isfinite(x):
            raise ValueError("score must be finite")
        z = self.threshold
        if x > z:
            return Decision(x, z, Kind.ALARM)
        self.n += 1
        if x > self.t:
            self._peaks.append(x - self.t)
            self._refit()
            return Decision(x, z, Kind.PEAK)
        return Decision(x, z, Kind.NORMAL)

    def run(self, scores) -> list[Decision]:
        return [self.update(s) for s in scores]

    def _refit(self) -> None:
        self.fit = fit_gpd(np.asarray(self._peaks))
        self.threshold = tail_quantile(self.t, self.fit, self.q, self.n, self.n_peaks)
