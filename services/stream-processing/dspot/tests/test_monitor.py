import numpy as np
import pytest

from dspot.domain.monitor import RETRY_EVERY, AlarmMonitor, Score, Verdict


def feed(monitor, values, agent="A", detector="iforest", start=0):
    return [monitor.on_score(Score(f"e{start + i}", agent, detector, float(v)))
            for i, v in enumerate(values)]


def test_warm_up_raises_no_alarms_then_calibrates():
    m = AlarmMonitor(q=1e-3, warmup=3_000)
    rng = np.random.default_rng(0)
    warm = rng.normal(size=3_000)
    warm[100] = 50.0                                   # even an extreme score during warm-up
    assert all(a is None for a in feed(m, warm))
    assert ("A", "iforest") in m.detectors
    assert m.status() == {"A/iforest": f"threshold {m.detectors[('A', 'iforest')].threshold:.4g}"}


def test_each_agent_and_detector_has_its_own_threshold():
    m = AlarmMonitor(q=1e-3, warmup=3_000)
    rng = np.random.default_rng(1)
    feed(m, rng.normal(size=3_000), agent="A", detector="iforest")
    feed(m, rng.normal(loc=10, scale=3, size=3_000), agent="A", detector="markov")
    feed(m, rng.normal(size=1_000), agent="B", detector="iforest")
    a_if = m.detectors[("A", "iforest")].threshold
    a_mk = m.detectors[("A", "markov")].threshold
    assert 2 < a_if < 5 and 15 < a_mk < 30
    assert m.status()["B/iforest"] == "warming up 1000/3000"


def test_alarms_and_reviewer_verdicts():
    m = AlarmMonitor(q=1e-3, warmup=3_000)
    feed(m, np.random.default_rng(2).normal(size=3_000))
    dspot = m.detectors[("A", "iforest")]

    alarm = m.on_score(Score("x1", "A", "iforest", 9.0))
    assert alarm is not None and alarm.threshold < 9.0 and alarm.q == 1e-3
    n_peaks = dspot.spot.n_peaks
    assert m.on_verdict(Verdict("x1", "iforest", false_alarm=True))
    assert dspot.spot.n_peaks == n_peaks + 1              # learned
    assert not m.on_verdict(Verdict("x1", "iforest", false_alarm=True))   # only once

    m.on_score(Score("x2", "A", "iforest", 12.0))
    assert not m.on_verdict(Verdict("x2", "iforest", false_alarm=False))  # attack: not learned
    assert dspot.spot.n_peaks == n_peaks + 1
    assert not m.on_verdict(Verdict("unknown", "iforest", false_alarm=True))


def test_late_verdict_uses_the_moving_average_of_the_alarm_time():
    m = AlarmMonitor(q=1e-3, depth=20, warmup=3_000)
    rng = np.random.default_rng(3)
    feed(m, rng.normal(size=3_000))
    dspot = m.detectors[("A", "iforest")]
    m.on_score(Score("x", "A", "iforest", 9.0))
    mean_then = dspot.local_mean
    feed(m, rng.normal(loc=2.0, size=200), start=5_000)  # level moves before the reviewer answers
    assert dspot.local_mean > mean_then + 1
    peaks_before = list(dspot.spot._peaks)
    m.on_verdict(Verdict("x", "iforest", false_alarm=True))
    assert dspot.spot._peaks[len(peaks_before)] == pytest.approx(9.0 - mean_then - dspot.spot.t)


def test_unanswered_alarms_are_bounded():
    m = AlarmMonitor(q=1e-3, warmup=3_000, max_pending=5)
    feed(m, np.random.default_rng(4).normal(size=3_000))
    for i in range(8):
        m.on_score(Score(f"x{i}", "A", "iforest", 20.0))
    assert len(m._pending) == 5
    assert not m.on_verdict(Verdict("x0", "iforest", false_alarm=True))   # oldest forgotten
    assert m.on_verdict(Verdict("x7", "iforest", false_alarm=True))


def test_constant_scores_keep_warming_up_without_crashing():
    m = AlarmMonitor(warmup=3_000)
    feed(m, np.zeros(3_000 + 3 * RETRY_EVERY))
    assert m.detectors == {}
    rng = np.random.default_rng(5)
    feed(m, rng.normal(size=3_000))                   # real scores arrive: calibration succeeds
    assert ("A", "iforest") in m.detectors


def test_validation():
    with pytest.raises(ValueError):
        AlarmMonitor(warmup=10, depth=20)
    with pytest.raises(ValueError):
        AlarmMonitor(q=0.5)
    with pytest.raises(ValueError):
        AlarmMonitor().on_score(Score("e", "A", "d", float("nan")))
