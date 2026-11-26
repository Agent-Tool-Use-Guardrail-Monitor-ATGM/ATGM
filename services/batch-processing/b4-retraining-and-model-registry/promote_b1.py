"""Compare an Agent B challenger against a trusted B1 champion artifact."""

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from b1_classifier.adapters import dataset, model_store
from b1_classifier.domain.features import session_features
from b1_classifier.domain.training import CLASSES, make_model
from publish_b1 import publish
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
    champion_group = parser.add_mutually_exclusive_group(required=True)
    champion_group.add_argument("--champion", type=Path, help="Trusted local folder containing model.joblib")
    champion_group.add_argument("--current-champion", action="store_true", help="Load latest registry random forest")
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--source", choices=("dataset", "db"), default="dataset",
                        help="Source of challenger training sessions")
    parser.add_argument("--training-scenarios", help="Training scenario file for dataset mode")
    parser.add_argument("--holdout-scenarios", required=True,
                        help="Independent labeled data never used to train or select the champion")
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--promote", action="store_true", help="Save the challenger if its macro F1 is higher")
    parser.add_argument("--announce", action="store_true", help="Publish promoted versions to Kafka")
    args = parser.parse_args()
    if args.announce and not (args.current_champion and args.promote):
        parser.error("--announce requires --current-champion and --promote")
    champion = args.champion if args.champion is not None else model_store.latest(args.models_dir, "random_forest")
    if champion is None:
        parser.error("No current random forest in the B1 registry")
    if args.announce:
        announce_if_pending(args.models_dir, champion)
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
    holdout_ids = sorted(row[0] for row in holdout)
    if args.current_champion and args.promote:
        for path in champion.parent.glob("*/metrics.json"):
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous.get("eligible_for_promotion") and set(previous.get("holdout_session_ids", ())).intersection(holdout_ids):
                print(json.dumps({"status": "holdout_already_used", "champion_version": champion.name}))
                return
    challenger, report = compare(model_store.load(champion), training, holdout, "random_forest")
    report["champion_version"] = champion.name
    report["training_source"] = args.source
    if args.promote and report["eligible_for_promotion"]:
        folder = model_store.save(challenger, {**report, "holdout_session_ids": holdout_ids}, args.models_dir)
        report["saved_to"] = str(folder)
        if args.announce:
            announce_if_pending(args.models_dir, folder)
    if args.announce:
        announce_evaluation(report, os.getenv("KAFKA_BOOTSTRAP", "localhost:29092"))
    print(json.dumps(report, indent=2))


def announce_evaluation(report, bootstrap):
    """Record each completed comparison on the analytics topic."""
    from confluent_kafka import Producer

    event = {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "event_type": "model.evaluated",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "run_id": None,
        "session_id": None,
        "sequence": None,
        "request_id": None,
        "data": {"agent_id": "B", "model": "b1-binary", "detector": "b4",
                 "metrics": report},
    }
    producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True})
    delivery = []
    producer.produce("stats", key="b1-binary", value=json.dumps(event),
                     on_delivery=lambda error, _: delivery.append(error))
    if producer.flush(10) or delivery != [None]:
        raise RuntimeError("Kafka did not acknowledge the B4 evaluation")


def announce_if_pending(models_dir, folder):
    marker = folder / "kafka-published"
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    if metrics.get("eligible_for_promotion") is True and not marker.exists():
        publish(models_dir, folder.name, os.getenv("KAFKA_BOOTSTRAP", "localhost:29092"))
        marker.touch()


if __name__ == "__main__":
    main()
