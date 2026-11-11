import numpy as np
import pytest

from dspot.domain.dspot import DSPOT
from dspot.domain.spot import SPOT, Kind


def drifting(rng, n: int, start: float, end: float) -> np.ndarray:
    """Normal noise around a level that moves linearly from start to end."""
    return np.linspace(start, end, n) + rng.normal(size=n)


def test_follows_a_drifting_level():
    """The level climbs by 15 standard deviations; plain SPOT floods, DSPOT stays near q."""
    rng = np.random.default_rng(1)
    q = 2e-3
    init = drifting(rng, 3_000, 0.0, 1.5)
    stream = drifting(rng, 30_000, 1.5, 15.0)

    dspot = DSPOT(q=q, depth=20)
    dspot.initialize(init)
    rate = np.mean([d.alarm for d in dspot.run(stream)])
    assert q / 2 < rate < 4 * q

    spot = SPOT(q=q)                         # plain SPOT on the last 5k scores (level 13-15):
    spot.initialize(init)                    # its fixed threshold flags almost everything
    assert np.mean([d.alarm for d in spot.run(stream[-5_000:])]) > 0.9


def test_reviewed_false_alarms_bring_the_rate_back_to_q():
    rng = np.random.default_rng(2)
    q = 2e-3
    dspot = DSPOT(q=q, depth=20)
    dspot.initialize(drifting(rng, 3_000, 0.0, 1.5))
    stream = drifting(rng, 30_000, 1.5, 15.0)
    alarms = 0
    for x in stream:
        if dspot.update(x).alarm:
            alarms += 1
            dspot.confirm_normal(x)
    assert q / 2 < alarms / stream.size < 1.6 * q


def test_injected_anomalies_are_alarms_despite_drift():
    rng = np.random.default_rng(3)
    dspot = DSPOT(q=1e-3, depth=20)
    dspot.initialize(drifting(rng, 3_000, 0.0, 1.0))
    stream = drifting(rng, 5_000, 1.0, 6.0)
    attacks = rng.choice(np.arange(100, 5_000), size=20, replace=False)
    stream[attacks] += 8.0
    flagged = {i for i, d in enumerate(dspot.run(stream)) if d.alarm}
    assert set(attacks.tolist()) <= flagged


def test_alarms_do_not_move_the_window():
    rng = np.random.default_rng(4)
    dspot = DSPOT(q=1e-3, depth=20)
    dspot.initialize(rng.normal(size=3_000))
    before = (dspot.local_mean, dspot.threshold, dspot.spot.n)
    d = dspot.update(dspot.threshold + 10.0)
    assert d.kind is Kind.ALARM
    assert (dspot.local_mean, dspot.threshold, dspot.spot.n) == before


def test_decision_threshold_is_in_raw_units():
    rng = np.random.default_rng(5)
    dspot = DSPOT(q=1e-3, depth=20)
    dspot.initialize(rng.normal(loc=100.0, size=3_000))
    z = dspot.threshold
    assert 102 < z < 106                     # about 100 + 3.1
    d = dspot.update(100.0)
    assert d.threshold == z and d.kind is Kind.NORMAL


def test_input_validation():
    with pytest.raises(ValueError):
        DSPOT(depth=0)
    dspot = DSPOT(q=1e-3, depth=20)
    with pytest.raises(RuntimeError):
        dspot.update(1.0)
    with pytest.raises(RuntimeError):
        dspot.confirm_normal(1.0)
    with pytest.raises(ValueError):
        dspot.initialize(np.zeros(20))       # nothing left after filling the window
    dspot.initialize(np.random.default_rng(6).normal(size=3_000))
    with pytest.raises(ValueError):
        dspot.update(float("nan"))
