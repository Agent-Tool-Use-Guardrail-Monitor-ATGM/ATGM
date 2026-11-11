import math
import random

import pytest

from aci.domain.tracker import QuantileTracker


def test_decaying_steps_follow_the_paper_schedule():
    t = QuantileTracker(alpha=0.1, bound=1.0, scale=0.5, eps=0.1)
    assert t.eta == pytest.approx(0.5)                     # t = 1
    t.update(0.0)
    assert t.eta == pytest.approx(0.5 * 2 ** -0.6)
    c = QuantileTracker(alpha=0.1, bound=1.0, scale=0.05, step="constant")
    c.update(0.0)
    assert c.eta == 0.05


def test_update_rule_eq_4():
    t = QuantileTracker(alpha=0.1, bound=1.0, scale=0.5, q0=0.3)
    assert t.update(0.8) is True                           # miscovered: q goes up by eta * 0.9
    assert t.q == pytest.approx(0.3 + 0.5 * 0.9)
    q, eta = t.q, t.eta
    assert t.update(0.1) is False                          # covered: q goes down by eta * alpha
    assert t.q == pytest.approx(q - eta * 0.1)


def test_iid_scores_converge_to_the_true_quantile():
    """Theorem 3: q_t -> (1 - alpha) quantile; here Uniform(0, 1), alpha = 0.1 -> 0.9."""
    rng = random.Random(0)
    t = QuantileTracker(alpha=0.1, bound=1.0, scale=0.5)
    for _ in range(50_000):
        t.update(rng.random())
    assert t.q == pytest.approx(0.9, abs=0.01)
    assert t.miscoverage == pytest.approx(0.1, abs=0.01)


def test_constant_step_does_not_settle_but_decaying_does():
    rng = random.Random(1)
    dec = QuantileTracker(alpha=0.1, bound=1.0, scale=0.5)
    con = QuantileTracker(alpha=0.1, bound=1.0, scale=0.05, step="constant")
    late_dec, late_con = [], []
    for i in range(40_000):
        x = rng.random()
        dec.update(x)
        con.update(x)
        if i >= 30_000:
            late_dec.append(dec.q)
            late_con.append(con.q)
    spread = lambda xs: max(xs) - min(xs)
    assert spread(late_dec) < 0.05 and spread(late_con) > 3 * spread(late_dec)


def test_long_run_coverage_on_an_adversarial_sequence():
    """Theorem 1: |miscoverage - alpha| <= (B + eta_1) / (eta_T * T), for any sequence."""
    t = QuantileTracker(alpha=0.2, bound=10.0, scale=1.0)
    T = 20_000
    for i in range(T):                                     # scores jump between regimes
        t.update(9.5 if (i // 500) % 2 else 0.5 + (i % 7))
    eta_T = 1.0 * T ** (-0.6)
    assert abs(t.miscoverage - 0.2) <= (10.0 + 1.0) / (eta_T * T)


def test_validation():
    for kw in ({"alpha": 0}, {"alpha": 1.2}, {"bound": 0}, {"eps": 0.5}, {"step": "fast"}, {"scale": -1}):
        args = {"alpha": 0.1, "bound": 1.0, **kw}
        with pytest.raises(ValueError):
            QuantileTracker(**args)
    with pytest.raises(ValueError):
        QuantileTracker(0.1, 1.0).update(math.nan)
