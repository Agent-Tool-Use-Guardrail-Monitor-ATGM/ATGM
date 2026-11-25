import pytest

from b2_classifier.domain.training import train_and_evaluate
from b2_classifier.adapters.dataset import CLASSES


def make_sample(labels, index):
    return {
        "n_calls": index + 1,
        "n_distinct_tools": index % 3 + 1,
        "secret_like_argument": int("unsafe_args" in labels),
        "n_failed": int("skipped_check" in labels),
        f"sample:{index}": 1,
    }


def sample_data():
    features = []
    labels = []

    for index in range(80):
        current = []

        if index % 2 == 0:
            current.append("unsafe_args")
        if index % 3 == 0:
            current.append("skipped_check")
        if index % 5 == 0:
            current.append("out_of_order")

        labels.append(current)
        features.append(make_sample(current, index))

    return features, labels


def test_training_returns_metrics_for_all_classes():
    features, labels = sample_data()

    result = train_and_evaluate(features, labels)

    assert result.model is not None
    assert result.metrics["n_sessions"] == 80
    assert result.metrics["n_train"] + result.metrics["n_test"] == 80
    assert set(result.metrics["per_class"]) == set(CLASSES)
    assert result.metrics["per_class"]["unauthorized_tool"]["trained"] is False
    assert result.metrics["per_class"]["unauthorized_tool"]["f1"] is None

    for label in ("unsafe_args", "skipped_check", "out_of_order"):
        assert 0 <= result.metrics["per_class"][label]["f1"] <= 1
        assert len(result.metrics["confusion_matrices"][label]) == 2


def test_training_rejects_missing_class():
    features, labels = sample_data()

    filtered = [
        (feature, current)
        for feature, current in zip(features, labels)
        if "out_of_order" not in current
    ]

    with pytest.raises(ValueError, match="Not enough positive examples"):
        train_and_evaluate(
            [item[0] for item in filtered],
            [item[1] for item in filtered],
        )


def test_training_rejects_unknown_label():
    with pytest.raises(ValueError, match="Unsupported violation labels"):
        train_and_evaluate(
            [{"n_calls": 1}, {"n_calls": 2}],
            [["unsafe_args"], ["unknown_type"]],
        )


def test_training_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        train_and_evaluate(
            [{"n_calls": 1}],
            [["unsafe_args"], ["skipped_check"]],
        )
