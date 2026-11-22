"""Saves a trained transition table with its metrics, and announces it on model updates."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

MODEL_NAME = "b3-markov-chain"
TABLE_FILE = "transition_table.json"


def version_name(smoothing: str, now: datetime | None = None) -> str:
    return f"{(now or datetime.now(timezone.utc)):%Y-%m-%dT%H-%M-%S}_{smoothing}"


def save(table: dict, metrics: dict, models_dir: Path, version: str) -> Path:
    """models/b3-markov-chain/<version>/{transition_table.json, metrics.json}; returns the folder."""
    folder = models_dir / MODEL_NAME / version
    folder.mkdir(parents=True, exist_ok=True)
    (folder / TABLE_FILE).write_text(json.dumps(table, indent=2, sort_keys=False))
    (folder / "metrics.json").write_text(json.dumps({"version": version, **metrics}, indent=2))
    return folder


def announce_event(folder: Path, metrics: dict, table: dict) -> dict:
    """B1's message envelope; the table is embedded so a consumer needs no shared disk."""
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "event_type": "model.trained",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {"model": MODEL_NAME, "version": folder.name, "path": str(folder),
                 "metrics": metrics, "transition_table": table},
    }


def announce(folder: Path, metrics: dict, table: dict, bootstrap: str, topic: str = "model-updates",
             producer=None) -> None:
    if producer is None:
        from confluent_kafka import Producer
        producer = Producer({"bootstrap.servers": bootstrap})
    event = announce_event(folder, metrics, table)
    producer.produce(topic, key=MODEL_NAME, value=json.dumps(event))
    producer.flush(10)


def load(folder: Path) -> dict:
    return json.loads((folder / TABLE_FILE).read_text())


def latest(models_dir: Path, kind: str | None = None) -> Path | None:
    folders = [folder for folder in (models_dir / MODEL_NAME).glob("*")
               if (folder / TABLE_FILE).exists() and (kind is None or folder.name.endswith(kind))]
    return max(folders, key=lambda folder: folder.name, default=None)
