"""Evaluate two B1 candidates on the same held-out sessions."""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from b1_classifier.adapters import dataset
from b1_classifier.domain.features import session_features
from b1_classifier.domain.training import CLASSES, make_model
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split


def evaluate(sessions):
    ordered = sorted(sessions, key=lambda session: session[0])
    ids = [session_id for session_id, _, _ in ordered]
    labels = [label for _, _, label in ordered]
    counts = Counter(labels)
    if len(set(ids)) != len(ids):
        raise ValueError("Evaluation requires unique session IDs")
    if set(counts) != set(CLASSES) or min(counts.values()) < 2:
        raise ValueError("Evaluation requires at least two sessions of each B1 class")

    train, holdout = train_test_split(
        ordered, test_size=0.25, stratify=labels, random_state=0
    )
    train_x, train_y = [session_features(calls) for _, calls, _ in train], [row[2] for row in train]
    test_x, test_y = [session_features(calls) for _, calls, _ in holdout], [row[2] for row in holdout]
    if set(train_y) != set(CLASSES) or set(test_y) != set(CLASSES):
        raise ValueError("Both splits must contain both B1 classes")

    scores = {}
    for kind in ("logistic_regression", "random_forest"):
        predictions = make_model(kind).fit(train_x, train_y).predict(test_x)
        scores[kind] = f1_score(test_y, predictions, labels=CLASSES, average="macro", zero_division=0)
    return {"training_sessions": len(train), "held_out_sessions": len(holdout),
            "held_out_class_counts": dict(Counter(test_y)), "macro_f1": scores}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, help="Agent B fixture directory. Defaults to reviewed database data.")
    args = parser.parse_args()
    if args.dataset_dir is None:
        sessions = dataset.from_database(
            os.environ.get("ANALYTICS_DB", "host=localhost dbname=analytics_db user=analytics_svc")
        )
    else:
        sessions = dataset.from_dataset(args.dataset_dir, "scenario_01_500.jsonl")
    print(json.dumps(evaluate(sessions), indent=2))


if __name__ == "__main__":
    main()
