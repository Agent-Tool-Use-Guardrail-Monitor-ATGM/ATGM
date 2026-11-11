import numpy as np
import pytest

from dspot.domain.spot import SPOT
from dspot.evaluate import evaluate, main, make_detector, read_csv, synthetic_stream


def test_metrics_on_a_hand_made_stream():
    rng = np.random.default_rng(0)
    scores = np.concatenate([rng.normal(size=3_000), [0.0, 20.0, 0.0, 25.0, 0.1]])
    labels = np.array([0] * 3_000 + [0, 1, 0, 0, 1])     # second big score is unlabelled
    r = evaluate(SPOT(q=1e-3), scores, labels, init=3_000)
    assert [d.alarm for d in r.decisions] == [False, True, False, True, False]
    assert r.alarm_rate == pytest.approx(2 / 5)
    assert r.precision == pytest.approx(1 / 2)
    assert r.recall == pytest.approx(1 / 2)
    assert r.false_alarm_rate == pytest.approx(1 / 3)


def test_without_labels_only_the_alarm_rate_is_reported():
    r = evaluate(SPOT(q=1e-3), np.random.default_rng(1).normal(size=4_000), init=3_000)
    assert r.precision is None and r.recall is None and r.false_alarm_rate is None
    assert "precision" not in r.summary()


def test_dspot_with_review_catches_all_synthetic_attacks():
    scores, labels = synthetic_stream(seed=2)
    r = evaluate(make_detector("dspot", 1e-3, 0.98, 20), scores, labels, review=True)
    assert r.recall == 1.0
    assert r.false_alarm_rate < 3e-3


def test_review_needs_labels():
    with pytest.raises(ValueError):
        evaluate(SPOT(), np.zeros(10), review=True)


def test_csv_and_command_line(tmp_path):
    pytest.importorskip("matplotlib")
    scores, labels = synthetic_stream(seed=3, n=6_000)
    csv_path = tmp_path / "scores.csv"
    csv_path.write_text("score,label\n" + "".join(f"{s},{l}\n" for s, l in zip(scores, labels)))
    s, l = read_csv(str(csv_path), "score", "label")
    assert np.allclose(s, scores) and (l == labels).all()

    png = tmp_path / "eval.png"
    assert main(["--csv", str(csv_path), "--labels", "label", "--review", "--plot", str(png)]) == 0
    assert png.read_bytes()[:4] == b"\x89PNG"
