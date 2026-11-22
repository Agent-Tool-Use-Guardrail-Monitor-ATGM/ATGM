import pytest

from kswin.domain.detector import KSWIN


def test_stationary_stream_does_not_detect_drift():
    detector = KSWIN(
        window_size=40,
        stat_size=10,
        alpha=0.005,
        random_state=42,
    )

    results = [
        detector.update(10.0)
        for _ in range(100)
    ]

    completed = [result for result in results if result is not None]

    assert len(completed) == 61
    assert not any(result.drift_detected for result in completed)


def test_sudden_distribution_change_detects_drift():
    detector = KSWIN(
        window_size=40,
        stat_size=10,
        alpha=0.005,
        random_state=42,
    )

    for _ in range(40):
        detector.update(10.0)

    results = [
        detector.update(100.0)
        for _ in range(15)
    ]

    detected = [
        result for result in results
        if result is not None and result.drift_detected
    ]

    assert detected, "Expected KSWIN to detect the distribution change"


def test_detector_waits_for_full_window():
    detector = KSWIN(window_size=40, stat_size=10)

    for _ in range(39):
        assert detector.update(10.0) is None


def test_detector_rejects_non_numeric_values():
    detector = KSWIN()

    with pytest.raises(ValueError):
        detector.update("not a number")


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_detector_rejects_non_finite_values(value):
    detector = KSWIN()

    with pytest.raises(ValueError):
        detector.update(value)


def test_detector_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        KSWIN(window_size=1)

    with pytest.raises(ValueError):
        KSWIN(window_size=20, stat_size=11)

    with pytest.raises(ValueError):
        KSWIN(alpha=0)
