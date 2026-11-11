"""Online conformal threshold with decaying step sizes.

Angelopoulos, Barber & Bates (2024), "Online conformal prediction with decaying step sizes",
arXiv:2402.01139. For a nonconformity score s_t in [0, B] and the set C_t = {y : s_t(y) <= q_t}:

    q_{t+1} = q_t + eta_t * (err_t - alpha),    err_t = 1{ s_t > q_t }   (eq. 4)
    eta_t   = c * t^(-1/2 - eps)                                       (decaying, eps in (0, 1/2))

Guarantees (paper, Theorems 1 and 3):
  - any sequence:  |miscoverage rate - alpha| <= (B + eta_1) / (eta_T * T)  ->  0
  - i.i.d. scores: q_t converges to the true (1 - alpha) quantile.
With a constant step (Gibbs & Candes 2021, Adaptive Conformal Inference) the first guarantee
holds, but q_t keeps jumping around and never converges; `step="constant"` keeps that variant
for comparison.
"""
from __future__ import annotations

import math


class QuantileTracker:
    def __init__(self, alpha: float, bound: float, scale: float | None = None, eps: float = 0.1,
                 step: str = "decaying", q0: float = 0.0) -> None:
        if not 0 < alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        if bound <= 0:
            raise ValueError("bound must be positive")
        if not 0 < eps < 0.5:
            raise ValueError("eps must be in (0, 1/2)")
        if step not in ("decaying", "constant"):
            raise ValueError("step must be 'decaying' or 'constant'")
        self.alpha, self.bound, self.eps, self.step = alpha, bound, eps, step
        self.scale = bound / 10 if scale is None else scale
        if self.scale <= 0:
            raise ValueError("scale must be positive")
        self.q = float(q0)
        self.t = 0                    # number of updates so far
        self.errors = 0

    @property
    def eta(self) -> float:
        """Step size used by the next update."""
        if self.step == "constant":
            return self.scale
        return self.scale * (self.t + 1) ** (-0.5 - self.eps)

    def covers(self, score: float) -> bool:
        return min(max(score, 0.0), self.bound) <= self.q

    def update(self, score: float) -> bool:
        """Feed one labelled score; returns True if it was a miscoverage."""
        if not math.isfinite(score):
            raise ValueError("score must be finite")
        err = not self.covers(score)
        self.q += self.eta * (err - self.alpha)
        self.t += 1
        self.errors += err
        return err

    @property
    def miscoverage(self) -> float | None:
        return self.errors / self.t if self.t else None
