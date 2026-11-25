"""B2: classify observed violation types in Agent B sessions.

Run from the repository root:
    python -m b2_classifier.main
    python -m b2_classifier.main --model logistic_regression
    python -m b2_classifier.main --announce
"""
import argparse
import json
import os
from pathlib import Path

from b2_classifier.adapters import dataset, model_store
from b2_classifier.domain.features import session_features
from b2_classifier.domain.training import train_and_evaluate


def main() -> None:
    env = os.environ.get

    parser = argparse.ArgumentParser(
        description="B2: multilabel violation-type classifier"
    )
    parser.add_argument(
        "--model",
        choices=["random_forest", "logistic_regression"],
        default="random_forest",
    )
    parser.add_argument(
        "--dataset-dir",
        default="dataset/agent_b",
        help="Path to Agent B dataset directory",
    )
    parser.add_argument(
        "--scenario-file",
        default="scenario_01_500.jsonl",
        help="Scenario dataset filename",
    )
    parser.add_argument(
        "--models-dir",
        default=env("MODELS_DIR", "models"),
    )
    parser.add_argument(
        "--announce",
        action="store_true",
        help="Publish the trained model on model-updates",
    )
    args = parser.parse_args()

    sessions = dataset.from_files(
        Path(args.dataset_dir),
        args.scenario_file,
    )

    features = [
        session_features(calls)
        for _, calls, _ in sessions
    ]
    labels = [
        violation_labels
        for _, _, violation_labels in sessions
    ]

    print(f"\nTraining on {len(sessions)} sessions.")

    result = train_and_evaluate(
        features,
        labels,
        kind=args.model,
    )

    metrics = {
        **result.metrics,
        "dataset": args.scenario_file,
        "agent": "B",
    }

    folder = model_store.save(
        result.model,
        metrics,
        Path(args.models_dir),
    )

    print("\nEvaluation metrics:")
    print(json.dumps(metrics, indent=2))
    print(f"\nModel saved to {folder}")

    if args.announce:
        model_store.announce(
            folder,
            metrics,
            env("KAFKA_BOOTSTRAP", "localhost:29092"),
        )


if __name__ == "__main__":
    main()
