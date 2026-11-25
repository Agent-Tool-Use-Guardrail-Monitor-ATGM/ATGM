"""Save and load B2 models, metrics, and optional Kafka announcements."""
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib

MODEL_NAME = "b2-violation-type"


def save(model, metrics: dict, models_dir: Path, name: str = MODEL_NAME) -> Path:
    version = f"{datetime.now(timezone.utc):%Y-%m-%dT%H-%M-%S}_{metrics['model']}"
    folder = models_dir / name / version
    folder.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, folder / "model.joblib")
    (folder / "metrics.json").write_text(
        json.dumps({"version": version, **metrics}, indent=2),
        encoding="utf-8",
    )
    return folder


def announce(
    folder: Path,
    metrics: dict,
    bootstrap: str,
    topic: str = "model-updates",
) -> None:
    import uuid
    from confluent_kafka import Producer

    event = {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "event_type": "model.trained",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "model": MODEL_NAME,
            "version": folder.name,
            "path": str(folder),
            "metrics": metrics,
        },
    }

    producer = Producer({"bootstrap.servers": bootstrap})
    delivery = []
    producer.produce(
        topic,
        key=MODEL_NAME,
        value=json.dumps(event),
        on_delivery=lambda error, _: delivery.append(error),
    )

    if producer.flush(10) or delivery != [None]:
        raise RuntimeError(
            f"Kafka did not acknowledge model {folder.name}: {delivery}"
        )


def load(folder: Path):
    return joblib.load(folder / "model.joblib")


def latest(models_dir: Path, kind: str | None = None) -> Path | None:
    folders = [
        folder
        for folder in (models_dir / MODEL_NAME).glob("*")
        if (folder / "model.joblib").exists()
        and (kind is None or folder.name.endswith(kind))
    ]
    return max(folders, key=lambda folder: folder.name, default=None)
