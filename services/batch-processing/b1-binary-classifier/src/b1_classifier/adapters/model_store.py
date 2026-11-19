"""Saves a trained model with its metrics, and announces it on model updates."""
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib

MODEL_NAME = "b1-binary"


def save(model, metrics: dict, models_dir: Path) -> Path:
    """models/b1-binary/<version>/{model.joblib, metrics.json}; returns the folder."""
    version = f"{datetime.now(timezone.utc):%Y-%m-%dT%H-%M-%S}_{metrics['model']}"
    folder = models_dir / MODEL_NAME / version
    folder.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, folder / "model.joblib")
    (folder / "metrics.json").write_text(json.dumps({"version": version, **metrics}, indent=2))
    return folder


def announce(folder: Path, metrics: dict, bootstrap: str, topic: str = "model-updates") -> None:
    """The message proposed in services/batch-processing/README.md (B4 may change it)."""
    import uuid

    from confluent_kafka import Producer

    event = {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "event_type": "model.trained",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {"model": MODEL_NAME, "version": folder.name, "path": str(folder), "metrics": metrics},
    }
    producer = Producer({"bootstrap.servers": bootstrap})
    producer.produce(topic, key=MODEL_NAME, value=json.dumps(event))
    producer.flush(10)