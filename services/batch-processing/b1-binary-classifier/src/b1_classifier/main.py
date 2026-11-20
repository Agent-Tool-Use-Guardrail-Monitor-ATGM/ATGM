"""B1: trains a session classifier (compliant vs. violating) and saves it with its metrics

    python -m b1_classifier.main                                # dataset files in the repo
    python -m b1_classifier.main --source db                    # analytics_db (reviewed labels)
    python -m b1_classifier.main --model logistic_regression --announce

Environment: ANALYTICS_DB (libpq connection string), KAFKA_BOOTSTRAP (localhost:29092), MODELS_DIR (./models).
"""
import argparse
import json
import os
from pathlib import Path

from b1_classifier.adapters import dataset, model_store
from b1_classifier.domain.features import session_features
from b1_classifier.domain.training import train_and_evaluate

REPO_DATASET = Path(__file__).resolve().parents[5] / "dataset" / "agent_b"


def main() -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(description="B1: binary session classifier")
    parser.add_argument("--source", choices=["dataset", "db"], default="dataset")
    parser.add_argument("--scenarios", default="scenario_01_500.jsonl", help="dataset file name (source=dataset)")
    parser.add_argument("--dataset-dir", default=env("DATASET_DIR", str(REPO_DATASET)))
    parser.add_argument("--model", choices=["random_forest", "logistic_regression"], default="random_forest")
    parser.add_argument("--models-dir", default=env("MODELS_DIR", "models"))
    parser.add_argument("--announce", action="store_true", help="publish the new model on model-updates")
    args = parser.parse_args()

    if args.source == "db":
        sessions = dataset.from_database(env("ANALYTICS_DB", "host=localhost dbname=analytics_db user=analytics_svc"))
    else:
        sessions = dataset.from_dataset(Path(args.dataset_dir), args.scenarios)
    features = [session_features(calls) for _, calls, _ in sessions]
    labels = [label for _, _, label in sessions]
    print(f"{len(sessions)} sessions: {labels.count('violating')} violating, {labels.count('compliant')} compliant")

    result = train_and_evaluate(features, labels, kind=args.model)
    folder = model_store.save(result.model, result.metrics, Path(args.models_dir))
    print(json.dumps(result.metrics, indent=2))
    print(f"Model saved to {folder}")
    if args.announce:
        model_store.announce(folder, result.metrics, env("KAFKA_BOOTSTRAP", "localhost:29092"))


if __name__ == "__main__":
    main()