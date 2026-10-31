import numpy as np
import pytest
from scipy import stats

from dspot.domain.spot import SPOT, Kind


def normal_scores(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=n)


def test_initial_threshold_matches_the_true_tail_quantile():
    """On N(0, 1) scores, z_q should approximate the exact quantile with tail mass q."""
    spot = SPOT(q=1e-3, level=0.98)
    z = spot.initialize(normal_scores(20_000, seed=1))
    assert spot.t == pytest.approx(stats.norm.ppf(0.98), abs=0.05)
    assert z == pytest.approx(stats.norm.isf(1e-3), abs=0.25)     # 3.09


@pytest.mark.parametrize("draw", [
    lambda rng, n: rng.normal(size=n),
    lambda rng, n: rng.exponential(size=n),
    lambda rng, n: rng.pareto(4.0, size=n),          # heavy tail
])
def test_false_alarm_rate_is_close_to_q(draw):
    rng = np.random.default_rng(7)
    q = 2e-3
    spot = SPOT(q=q, level=0.98)
    spot.initialize(draw(rng, 3_000))
    stream = draw(rng, 30_000)
    rate = np.mean([d.alarm for d in spot.run(stream)])
    # Excluding alarms from the model makes SPOT cautious (see spot.py): measured 1.4-2.6x q.
    assert q / 2 < rate < 4 * q


def test_injected_anomalies_are_alarms():
    rng = np.random.default_rng(3)
    spot = SPOT(q=1e-3)
    spot.initialize(rng.normal(size=3_000))
    stream = rng.normal(size=2_000)
    attacks = rng.choice(2_000, size=20, replace=False)
    stream[attacks] += 8.0
    decisions = spot.run(stream)
    flagged = {i for i, d in enumerate(decisions) if d.alarm}
    assert set(attacks.tolist()) <= flagged


def test_alarms_do_not_change_the_model():
    spot = SPOT(q=1e-3)
    spot.initialize(normal_scores(3_000, seed=4))
    before = (spot.threshold, spot.n, spot.n_peaks)
    d = spot.update(spot.threshold + 10.0)
    assert d.kind is Kind.ALARM
    assert (spot.threshold, spot.n, spot.n_peaks) == before


def test_peaks_refit_and_normal_scores_are_counted():
    spot = SPOT(q=1e-3)
    spot.initialize(normal_scores(3_000, seed=5))
    n, peaks, z = spot.n, spot.n_peaks, spot.threshold

    d = spot.update(spot.t - 1.0)
    assert d.kind is Kind.NORMAL and spot.n == n + 1 and spot.n_peaks == peaks

    d = spot.update((spot.t + z) / 2)
    assert d.kind is Kind.PEAK and spot.n_peaks == peaks + 1
    assert spot.threshold != z
    assert d.threshold == z           # the decision reports the threshold used for it


def test_input_validation():
    with pytest.raises(ValueError):
        SPOT(q=0.05, level=0.98)              # q must be below 1 - level
    with pytest.raises(ValueError):
        SPOT(level=1.0)
    spot = SPOT(q=1e-3)
    with pytest.raises(RuntimeError):
        spot.update(1.0)                      # not initialized
    with pytest.raises(ValueError):
        spot.initialize(normal_scores(100, seed=6))   # only ~2 peaks
    spot.initialize(normal_scores(3_000, seed=6))
    with pytest.raises(ValueError):
        spot.update(float("nan"))
