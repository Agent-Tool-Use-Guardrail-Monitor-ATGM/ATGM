"""Multilabel training and evaluation for the B2 violation classifier."""
from dataclasses import dataclass

from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputClassifier
from sklearn.pipeline import make_pipeline

from b2_classifier.adapters.dataset import CLASSES, TRAINABLE_CLASSES


def make_model(kind: str = "random_forest"):
    if kind == "logistic_regression":
        classifier = LogisticRegression(
            class_weight="balanced",
            max_iter=2000,
        )
    elif kind == "random_forest":
        classifier = RandomForestClassifier(
            n_estimators=300,
            class_weight="balanced",
            random_state=0,
        )
    else:
        raise ValueError(f"Unknown model type: {kind}")

    return make_pipeline(
        DictVectorizer(),
        MultiOutputClassifier(classifier),
    )


@dataclass
class Result:
    model: object
    metrics: dict


def train_and_evaluate(
    features: list[dict],
    labels: list[list[str]],
    kind: str = "random_forest",
    test_size: float = 0.25,
    seed: int = 0,
) -> Result:
    """Evaluate on a holdout, then refit the model on all usable sessions."""
    if len(features) != len(labels):
        raise ValueError("Features and labels must have the same length.")
    if not features:
        raise ValueError("No training sessions were provided.")
    if not 0 < test_size < 1:
        raise ValueError("test_size must be between 0 and 1.")

    unknown = sorted({
        label
        for session_labels in labels
        for label in session_labels
    } - set(CLASSES))
    if unknown:
        raise ValueError(f"Unsupported violation labels: {unknown}")

    targets = [
        [int(label in session_labels) for label in TRAINABLE_CLASSES]
        for session_labels in labels
    ]

    counts = {
        label: sum(row[index] for row in targets)
        for index, label in enumerate(TRAINABLE_CLASSES)
    }

    missing = [label for label, count in counts.items() if count < 2]
    if missing:
        raise ValueError(
            f"Not enough positive examples to train and evaluate: {missing}. "
            f"Counts: {counts}"
        )

    # Find a deterministic split with positive examples in both partitions.
    split = None
    for candidate_seed in range(seed, seed + 100):
        train_x, test_x, train_y, test_y = train_test_split(
            features,
            targets,
            test_size=test_size,
            random_state=candidate_seed,
        )

        train_counts = [
            sum(row[i] for row in train_y)
            for i in range(len(TRAINABLE_CLASSES))
        ]
        test_counts = [
            sum(row[i] for row in test_y)
            for i in range(len(TRAINABLE_CLASSES))
        ]

        if all(train_counts) and all(test_counts):
            split = train_x, test_x, train_y, test_y, candidate_seed
            break

    if split is None:
        raise ValueError(
            "Could not create a train/test split containing positive "
            "examples of every trainable class."
        )

    train_x, test_x, train_y, test_y, used_seed = split

    model = make_model(kind)
    model.fit(train_x, train_y)
    predicted = model.predict(test_x)

    per_class = {}
    confusion = {}

    for index, label in enumerate(TRAINABLE_CLASSES):
        true_values = [row[index] for row in test_y]
        predicted_values = [row[index] for row in predicted]

        precision, recall, f1, support = precision_recall_fscore_support(
            true_values,
            predicted_values,
            average="binary",
            zero_division=0,
        )

        per_class[label] = {
            "precision": round(float(precision), 3),
            "recall": round(float(recall), 3),
            "f1": round(float(f1), 3),
            "support": int(sum(true_values)),
            "trained": True,
        }

        confusion[label] = confusion_matrix(
            true_values,
            predicted_values,
            labels=[0, 1],
        ).tolist()

    # Keep all four requested classes visible in the report.
    per_class["unauthorized_tool"] = {
        "precision": None,
        "recall": None,
        "f1": None,
        "support": 0,
        "trained": False,
        "reason": "No actual examples in the available dataset.",
    }

    final_model = make_model(kind)
    final_model.fit(features, targets)

    metrics = {
        "model": kind,
        "task": "multilabel_classification",
        "n_sessions": len(labels),
        "n_train": len(train_y),
        "n_test": len(test_y),
        "random_seed": used_seed,
        "class_counts": {
            **counts,
            "unauthorized_tool": 0,
        },
        "per_class": per_class,
        "subset_accuracy": round(
            float(accuracy_score(test_y, predicted)), 3
        ),
        "confusion_matrices": confusion,
        "confusion_matrix_labels": ["no_violation", "violation"],
    }

    return Result(final_model, metrics)

