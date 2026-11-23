"""OPTWIN Algorithm 1 with the deterioration rule from §III-D."""

from dataclasses import dataclass
from functools import lru_cache
from math import sqrt

import numpy as np
from scipy.stats import f, t


def welch_df(old, new, n_old, n_new):
    return (old + new) ** 2 / (old**2 / (n_old - 1) + new**2 / (n_new - 1))


@dataclass(frozen=True)
class Optwin:
    minimum: int = 30
    maximum: int = 512
    confidence: float = 0.99
    robustness: float = 0.5

    def __post_init__(self):
        if not 4 <= self.minimum <= self.maximum or not 0 < self.confidence < 1 or self.robustness <= 0:
            raise ValueError("invalid OPTWIN parameters")

    @property
    def quantile(self):
        return self.confidence ** 0.25

    def split(self, size: int) -> tuple[int, float]:
        return optimal_cut(size, self.quantile, self.robustness)

    def detect(self, window: str) -> dict | None:
        if len(window) < self.minimum:
            return None
        cut, f_limit = self.split(len(window))
        history, recent = window[:cut], window[cut:]
        old_rate = history.count("1") / len(history)
        new_rate = recent.count("1") / len(recent)
        if new_rate <= old_rate:
            return None

        old_sd = sqrt(old_rate * (1 - old_rate)) + 1e-5
        new_sd = sqrt(new_rate * (1 - new_rate)) + 1e-5
        f_value = (new_sd / old_sd) ** 2
        old, new = old_sd**2 / len(history), new_sd**2 / len(recent)
        t_value = (new_rate - old_rate) / sqrt(old + new)
        t_limit = float(t.ppf(self.quantile, welch_df(old, new, len(history), len(recent))))
        if f_value <= f_limit and t_value <= t_limit:
            return None
        return {
            "test": "f" if f_value > f_limit else "t",
            "history_size": len(history),
            "recent_size": len(recent),
            "history_error_rate": old_rate,
            "recent_error_rate": new_rate,
            "f_statistic": f_value,
            "f_threshold": f_limit,
            "t_statistic": t_value,
            "t_threshold": t_limit,
        }


@lru_cache(maxsize=1024)
def optimal_cut(size: int, quantile: float, robustness: float) -> tuple[int, float]:
    # Discrete form of Equation 1. Maximize history among feasible integer cuts.
    history = np.arange(2, size - 1)
    recent = size - history
    bounds = f.ppf(quantile, history - 1, recent - 1)
    old, new = 1 / history, bounds / recent
    df = welch_df(old, new, history, recent)
    feasible = history[t.ppf(quantile, df) * np.sqrt(old + new) <= robustness]
    cut = int(feasible[-1]) if len(feasible) else size // 2
    return cut, float(bounds[cut - 2])
