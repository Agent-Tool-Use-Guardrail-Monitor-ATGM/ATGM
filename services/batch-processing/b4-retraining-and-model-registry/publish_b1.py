"""Publish the current promoted B1 version to the scorer."""

import argparse
import json
import os
from pathlib import Path

from b1_classifier.adapters import model_store


def publish(models_dir, version, bootstrap):
    folder = model_store.latest(models_dir, "random_forest")
    if folder is None or folder.name != version:
        raise ValueError("Version must be the current random forest in the B1 registry")
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    if metrics.get("eligible_for_promotion") is not True or not metrics.get("champion_version"):
        raise ValueError("Version must come from a successful B4 promotion")
    model_store.announce(folder, metrics, bootstrap)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Version directory name printed by B4 promotion")
    parser.add_argument("--models-dir", type=Path, default=Path(os.getenv("MODELS_DIR", "models")))
    args = parser.parse_args()
    publish(args.models_dir, args.version, os.getenv("KAFKA_BOOTSTRAP", "localhost:29092"))
    print(f"Published {args.version}")


if __name__ == "__main__":
    main()
