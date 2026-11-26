"""Saves a trained transition table with its metrics (one model per agent) and announces it on model updates."""
import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

MODEL_NAME = "b3-markov-chain"
TABLE_FILE = "transition_table.json"


def message_key(agent: str) -> str:
    """Kafka key of the model.trained message: b3-markov-chain.<agent>, so a compacted topic keeps one per agent."""
    return f"{MODEL_NAME}.{agent}"


def version_name(smoothing: str, now: datetime | None = None) -> str:
    return f"{(now or datetime.now(timezone.utc)):%Y-%m-%dT%H-%M-%S}_{smoothing}"


def save(table: dict, metrics: dict, models_dir: Path, version: str, agent: str = "B") -> Path:
    """models/b3-markov-chain/<agent>/<version>/{transition_table.json, metrics.json}; returns the folder."""
    folder = models_dir / MODEL_NAME / agent / version
    folder.mkdir(parents=True, exist_ok=True)
    (folder / TABLE_FILE).write_text(json.dumps(table, indent=2))
    (folder / "metrics.json").write_text(json.dumps({"version": version, "agent": agent, **metrics}, indent=2))
    return folder


def save_fold_tables(folder: Path, tables: list[dict]) -> list[Path]:
    """<folder>/folds/fold_<i>.json: the CV fold models, for replaying with models that never saw the session."""
    (folder / "folds").mkdir(exist_ok=True)
    paths = []
    for i, table in enumerate(tables):
        path = folder / "folds" / f"fold_{i}.json"
        path.write_text(json.dumps(table, indent=2))
        paths.append(path)
    return paths


def compact_metrics(metrics: dict) -> dict:
    """The metrics for the Kafka message: without the per-session lists (those stay in metrics.json)."""
    metrics = copy.deepcopy(metrics)

    def strip(node):
        if isinstance(node, dict):
            node.pop("heldout_min_log_p", None)
            for value in node.values():
                strip(value)
    strip(metrics)
    return metrics


def announce_event(folder: Path, metrics: dict, table: dict, agent: str = "B") -> dict:
    """B1's message envelope; the table is embedded so a consumer needs no shared disk."""
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "event_type": "model.trained",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {"model": MODEL_NAME, "agent": agent, "version": folder.name, "path": str(folder),
                 "metrics": compact_metrics(metrics), "transition_table": table},
    }


def announce(folder: Path, metrics: dict, table: dict, bootstrap: str, agent: str = "B",
             topic: str = "model-updates", producer=None) -> None:
    """One message, key b3-markov-chain.<agent>."""
    if producer is None:
        from confluent_kafka import Producer
        producer = Producer({"bootstrap.servers": bootstrap})
    event = announce_event(folder, metrics, table, agent)
    producer.produce(topic, key=message_key(agent), value=json.dumps(event))
    producer.flush(10)


def load(folder: Path) -> dict:
    return json.loads((folder / TABLE_FILE).read_text())


def latest(models_dir: Path, agent: str = "B", kind: str | None = None) -> Path | None:
    folders = [folder for folder in (models_dir / MODEL_NAME / agent).glob("*")
               if (folder / TABLE_FILE).exists() and (kind is None or folder.name.endswith(kind))]
    return max(folders, key=lambda folder: folder.name, default=None)
