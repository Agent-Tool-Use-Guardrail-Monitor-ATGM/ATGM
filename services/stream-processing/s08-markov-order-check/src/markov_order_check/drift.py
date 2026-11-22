"""Counters and a Page-Hinkley test on session scores (spec Sec. 8.4, Page 1954).

A drift signal is only logged and counted; it never changes the model and is not
published to ``scores``.
"""

from __future__ import annotations

from collections import Counter


class PageHinkley:
    """Detects a sustained increase of the mean of a stream of values."""

    def __init__(self, delta: float = 0.05, threshold: float = 50.0):
        self.delta = delta
        self.threshold = threshold
        self.reset()

    def reset(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.cumulative = 0.0
        self.minimum = 0.0

    def update(self, value: float) -> bool:
        """Add one value; return True when drift is signalled (the test then restarts)."""
        self.n += 1
        self.mean += (value - self.mean) / self.n
        self.cumulative += value - self.mean - self.delta
        self.minimum = min(self.minimum, self.cumulative)
        if self.cumulative - self.minimum > self.threshold:
            self.reset()
            return True
        return False


class Metrics:
    """Per (agent, model_version) counters, plus one Page-Hinkley test per agent."""

    def __init__(self, ph_delta: float = 0.05, ph_lambda: float = 50.0):
        self.counters: Counter[tuple[str, str, str]] = Counter()
        self._ph_delta, self._ph_lambda = ph_delta, ph_lambda
        self._ph: dict[str, PageHinkley] = {}

    def inc(self, agent: str, name: str, version: str = "-", by: int = 1) -> None:
        self.counters[(agent, version, name)] += by

    def get(self, agent: str, name: str, version: str | None = None) -> int:
        return sum(v for (a, ver, n), v in self.counters.items() if a == agent and n == name and (
            version is None or ver == version))

    def session_score(self, agent: str, version: str, score: float) -> bool:
        ph = self._ph.setdefault(agent, PageHinkley(self._ph_delta, self._ph_lambda))
        drift = ph.update(score)
        if drift:
            self.inc(agent, "drift_suspected", version)
        return drift

    def snapshot(self) -> dict[str, int]:
        return {f"{a}/{v}/{n}": c for (a, v, n), c in sorted(self.counters.items())}
