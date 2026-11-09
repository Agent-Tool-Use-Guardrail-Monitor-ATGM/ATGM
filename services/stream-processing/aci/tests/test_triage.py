import random

import pytest

from aci.domain.triage import FLAG, PASS, REVIEW, ConformalTriage


def test_safe_start_reviews_everything():
    tri = ConformalTriage(bound=20)
    assert {tri.decide("A", r).decision for r in (0.5, 3, 10, 19)} == {REVIEW}


def test_prediction_sets_map_to_decisions():
    tri = ConformalTriage(bound=10)
    c, v = tri._pair("A")
    c.q, v.q = 3.0, 4.0                    # pass up to 3, flag from 6, gap (3, 6) is empty -> review
    assert tri.decide("A", 2).decision == PASS and tri.decide("A", 2).prediction_set == ("compliant",)
    assert tri.decide("A", 7).decision == FLAG and tri.decide("A", 7).prediction_set == ("violating",)
    assert tri.decide("A", 4.5).prediction_set == () and tri.decide("A", 4.5).decision == REVIEW
    c.q = 7.0                              # overlap [6, 7] holds both labels -> review
    assert tri.decide("A", 6.5).prediction_set == ("compliant", "violating")
    assert tri.decide("A", 6.5).decision == REVIEW
    assert tri.decide("A", 50).decision == FLAG                 # clipped to the bound


def simulate(tri, n, rng, attack_rate=0.1, shift=0.0):
    """Normal session score ~ Exp(1)+shift, attack ~ 4+shift+Exp(1); all sessions labelled."""
    out = {"normal": [0, 0], "attack": [0, 0], "decisions": []}
    for _ in range(n):
        attack = rng.random() < attack_rate
        r = shift + rng.expovariate(1.0) + (4.0 if attack else 0.0)
        d = tri.decide("A", r).decision
        out["decisions"].append(d)
        key = "attack" if attack else "normal"
        out[key][0] += 1
        out[key][1] += d != (FLAG if attack else PASS)
        tri.learn("A", r, attack)
    return out


def test_error_rates_meet_the_targets():
    tri = ConformalTriage(alpha_normal=0.05, alpha_attack=0.1, bound=20)
    res = simulate(tri, 40_000, random.Random(0))
    normal_not_passed = res["normal"][1] / res["normal"][0]
    attack_not_flagged = res["attack"][1] / res["attack"][0]
    assert normal_not_passed == pytest.approx(0.05, abs=0.01)
    assert attack_not_flagged == pytest.approx(0.10, abs=0.02)
    st = tri.status()["A"]
    assert st["pass_up_to"] == pytest.approx(3.0, abs=0.15)          # 95% quantile of Exp(1)
    assert st["flag_from"] == pytest.approx(4.105, abs=0.25)          # 10% quantile of 4 + Exp(1)


def test_thresholds_follow_drift():
    tri = ConformalTriage(alpha_normal=0.05, alpha_attack=0.1, bound=20)
    rng = random.Random(1)
    simulate(tri, 20_000, rng)
    res = simulate(tri, 20_000, rng, shift=2.0)            # every score rises by 2
    assert res["normal"][1] / res["normal"][0] < 0.15
    assert tri.status()["A"]["pass_up_to"] > 4.0


def test_agents_have_separate_thresholds():
    tri = ConformalTriage(bound=20)
    rng = random.Random(2)
    for _ in range(5_000):
        tri.learn("A", rng.expovariate(1.0), False)
        tri.learn("B", 5 + rng.expovariate(1.0), False)
    assert tri.status()["B"]["pass_up_to"] > tri.status()["A"]["pass_up_to"] + 3


def test_validation():
    with pytest.raises(ValueError):
        ConformalTriage(alpha_normal=0)
    with pytest.raises(ValueError):
        ConformalTriage(step="nope")
