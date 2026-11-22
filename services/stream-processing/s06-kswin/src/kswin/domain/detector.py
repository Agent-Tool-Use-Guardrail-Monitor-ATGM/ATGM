
"""KSWIN statistical change detector."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

from scipy.stats import ks_2samp


@dataclass(frozen=True)
class KSWINResult:
    """Result of one KSWIN statistical comparison."""

    drift_detected: bool
    statistic: float
    p_value: float
    window_size: int


class KSWIN:
    """Kolmogorov-Smirnov Windowing detector for numeric streams."""

    def __init__(
        self,
        window_size: int = 100,
        stat_size: int = 30,
        alpha: float = 0.005,
        random_state: int = 42,
    ) -> None:
        if window_size < 2:
            raise ValueError("window_size must be at least 2")

        if stat_size < 2 or stat_size * 2 > window_size:
            raise ValueError(
                "stat_size must be at least 2 and no more than "
                "half of window_size"
            )

        if not 0 < alpha < 1:
            raise ValueError("alpha must be between 0 and 1")

        self.window_size = window_size
        self.stat_size = stat_size
        self.alpha = alpha

        self.window: deque[float] = deque(maxlen=window_size)
        self.random = random.Random(random_state)

    def update(self, value: float) -> KSWINResult | None:
        """Add one observation and test for distribution change."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("observation must be a numeric value")

        if not float("-inf") < float(value) < float("inf"):
            raise ValueError("observation must be finite")

        self.window.append(float(value))

        # Wait until the complete window is available.
        if len(self.window) < self.window_size:
            return None

        observations = list(self.window)

        # Randomly select older observations as the reference sample.
        reference_pool = observations[:-self.stat_size]
        reference = self.random.sample(reference_pool, self.stat_size)

        # The most recent observations represent the current distribution.
        recent = observations[-self.stat_size:]

        result = ks_2samp(
            reference,
            recent,
            alternative="two-sided",
            method="auto",
        )

        statistic = float(result.statistic)
        p_value = float(result.pvalue)

        # Require both statistical significance and a meaningful
        # difference between the empirical distributions.
        drift_detected = (
            p_value <= self.alpha and statistic > 0.1
        )

        if drift_detected:
            # Keep the recent observations as the starting point
            # for monitoring the new distribution.
            self.window.clear()
            self.window.extend(recent)

        return KSWINResult(
            drift_detected=drift_detected,
            statistic=statistic,
            p_value=p_value,
            window_size=len(self.window),
        )
