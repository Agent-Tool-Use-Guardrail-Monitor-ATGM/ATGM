"""B1: trains a session classifier (compliant vs. violating) and saves it with its metrics

    python -m b1_classifier.main                                # Agent B, dataset files in the repo
    python -m b1_classifier.main --source db                    # Agent B, analytics_db (reviewed labels)
    python -m b1_classifier.main --model logistic_regression --announce
    python -m b1_classifier.main --agent A                      # Agent A (collector export)

Agent A labels come from the collector export (`label`); model_failure runs are left out.
Most violating Agent A labels were assigned to balance the dataset, not from evidence (see README).

Environment: ANALYTICS_DB (libpq connection string), KAFKA_BOOTSTRAP (localhost:29092), MODELS_DIR (./models).
"""
import argparse
import json
import os
from pathlib import Path

from b1_classifier.adapters import dataset, model_store
from b1_classifier.domain.features import KNOWN_TOOLS, KNOWN_TOOLS_A, session_features
from b1_classifier.domain.training import train_and_evaluate

REPO_ROOT = Path(__file__).resolve().parents[5]
REPO_DATASET = REPO_ROOT / "dataset" / "agent_b"
AGENT_A_EXPORT = REPO_ROOT / "dataset" / "agent_a" / "all-events.jsonl"


def main() -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(description="B1: binary session classifier")
    parser.add_argument("--agent", choices=["A", "B"], default="B")
    parser.add_argument("--source", choices=["dataset", "db"], default="dataset")
    parser.add_argument("--scenarios", default="scenario_01_500.jsonl", help="dataset file name (agent B, source=dataset)")
    parser.add_argument("--dataset-dir", default=env("DATASET_DIR", str(REPO_DATASET)))
    parser.add_argument("--collector-file", default=str(AGENT_A_EXPORT), help="datalens-collector export (agent A)")
    parser.add_argument("--model", choices=["random_forest", "logistic_regression"], default="random_forest")
    parser.add_argument("--models-dir", default=env("MODELS_DIR", "models"))
    parser.add_argument("--announce", action="store_true", help="publish the new model on model-updates (agent B)")
    args = parser.parse_args()

    if args.agent == "A":
        if args.announce or args.source == "db":
            parser.error("agent A is an offline model: no --announce, no --source db")
        sessions = dataset.from_collector(Path(args.collector_file))
        known_tools, name = KNOWN_TOOLS_A, f"{model_store.MODEL_NAME}-a"
    elif args.source == "db":
        sessions = dataset.from_database(env("ANALYTICS_DB", "host=localhost dbname=analytics_db user=analytics_svc"))
        known_tools, name = KNOWN_TOOLS, model_store.MODEL_NAME
    else:
        sessions = dataset.from_dataset(Path(args.dataset_dir), args.scenarios)
        known_tools, name = KNOWN_TOOLS, model_store.MODEL_NAME

    features = [session_features(calls, known_tools) for _, calls, _ in sessions]
    labels = [label for _, _, label in sessions]
    print(f"Agent {args.agent}, {len(sessions)} sessions: "
          f"{labels.count('violating')} violating, {labels.count('compliant')} compliant")

    result = train_and_evaluate(features, labels, kind=args.model)
    metrics = {**result.metrics, "agent": args.agent}
    folder = model_store.save(result.model, metrics, Path(args.models_dir), name=name)
    print(json.dumps(metrics, indent=2))
    print(f"Model saved to {folder}")
    if args.announce:
        model_store.announce(folder, metrics, env("KAFKA_BOOTSTRAP", "localhost:29092"))


if __name__ == "__main__":
    main()