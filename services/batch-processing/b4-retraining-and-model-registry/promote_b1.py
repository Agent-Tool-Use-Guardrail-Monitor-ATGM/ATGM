"""Compare an Agent B challenger against a trusted B1 champion artifact."""

import argparse
import json
import os
from pathlib import Path

from b1_classifier.adapters import dataset, model_store
from b1_classifier.domain.features import session_features
from b1_classifier.domain.training import CLASSES, make_model
from sklearn.metrics import f1_score


def compare(champion, training, holdout, kind):
    train_ids = {row[0] for row in training}
    holdout_ids = {row[0] for row in holdout}
    if len(train_ids) != len(training) or len(holdout_ids) != len(holdout):
        raise ValueError("Each input must contain unique session IDs")
    if train_ids & holdout_ids:
        raise ValueError("Training and holdout sessions overlap")
    train_x, train_y = [session_features(row[1]) for row in training], [row[2] for row in training]
    test_x, test_y = [session_features(row[1]) for row in holdout], [row[2] for row in holdout]
    if set(train_y) != set(CLASSES) or set(test_y) != set(CLASSES):
        raise ValueError("Training and holdout must each contain both B1 classes")

    challenger = make_model(kind).fit(train_x, train_y)
    incumbent_score = f1_score(test_y, champion.predict(test_x), labels=CLASSES, average="macro")
    challenger_score = f1_score(test_y, challenger.predict(test_x), labels=CLASSES, average="macro")
    return challenger, {
        "model": kind,
        "champion_macro_f1": incumbent_score,
        "challenger_macro_f1": challenger_score,
        "held_out_sessions": len(holdout),
        "eligible_for_promotion": challenger_score > incumbent_score,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--champion", required=True, type=Path, help="Trusted local folder containing model.joblib")
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--source", choices=("dataset", "db"), default="dataset",
                        help="Source of challenger training sessions")
    parser.add_argument("--training-scenarios", help="Training scenario file for dataset mode")
    parser.add_argument("--holdout-scenarios", required=True,
                        help="Independent labeled data never used to train or select the champion")
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--promote", action="store_true", help="Save the challenger if its macro F1 is higher")
    args = parser.parse_args()
    if args.source == "db":
        if args.training_scenarios:
            parser.error("--training-scenarios applies only to --source dataset")
        conninfo = os.environ.get("ANALYTICS_DB")
        if not conninfo:
            parser.error("ANALYTICS_DB is required with --source db")
        training = dataset.from_database(conninfo)
    else:
        if not args.training_scenarios:
            parser.error("--training-scenarios is required with --source dataset")
        training = dataset.from_dataset(args.dataset_dir, args.training_scenarios)
    holdout = dataset.from_dataset(args.dataset_dir, args.holdout_scenarios)
    challenger, report = compare(model_store.load(args.champion), training, holdout, "random_forest")
    report["champion_version"] = args.champion.name
    report["training_source"] = args.source
    if args.promote and report["eligible_for_promotion"]:
        report["saved_to"] = str(model_store.save(challenger, report, args.models_dir))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
