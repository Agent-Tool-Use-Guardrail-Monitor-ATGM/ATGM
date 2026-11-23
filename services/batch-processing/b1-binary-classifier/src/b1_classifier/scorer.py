"""B1 session scorer: when an Agent B session ends, scores it with the newest B1 model.

tool-calls.B ─> SessionBuffer (session.ended) ─> model ─> scores (detector b1_classifier)
model-updates (model.trained) ─> reload the model
"""
import json
import logging
import os
from pathlib import Path

from b1_classifier.adapters import model_store
from b1_classifier.domain.scoring import violating_probability
from b1_classifier.domain.sessions import SessionBuffer
from b1_classifier.events import score_event

log = logging.getLogger("b1-scorer")


class Scorer:
    def __init__(self, models_dir: Path, kind: str | None = "random_forest"):
        self.models_dir = models_dir
        self.kind = kind
        self.sessions = SessionBuffer()
        self.model = None
        self.version = None
        self.reload(model_store.latest(models_dir, kind))

    def reload(self, folder: Path | None) -> None:
        if folder is None or not (folder / "model.joblib").exists():
            log.warning("no B1 model in %s yet, sessions are not scored", self.models_dir)
            return
        self.model = model_store.load(folder)
        self.version = folder.name
        log.info("B1 model loaded: %s", self.version)

    def on_model_update(self, event: dict) -> None:
        data = event.get("data") or {}
        if data.get("model") != model_store.MODEL_NAME:
            return
        if self.kind and not data.get("version", "").endswith(self.kind):
            return
        self.reload(self.models_dir / model_store.MODEL_NAME / data["version"])

    def handle(self, event: dict) -> dict | None:
        finished = self.sessions.add(event)
        if finished is None or self.model is None:
            return None
        score = violating_probability(self.model, finished.calls)
        return score_event(finished, score, self.version, run_id=event.get("run_id"))


def main() -> None:
    from confluent_kafka import Consumer, Producer

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
    input_topics = os.environ.get("B1_INPUT_TOPICS", "tool-calls.B").split(",")
    scorer = Scorer(Path(os.environ.get("B1_MODELS_DIR", "models")),
                    os.environ.get("B1_MODEL_KIND", "random_forest") or None)

    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": "b1-scorer",
                         "auto.offset.reset": "latest"})
    consumer.subscribe([*input_topics, "model-updates"])
    producer = Producer({"bootstrap.servers": bootstrap})
    log.info("B1 scorer started: %s -> scores", ", ".join(input_topics))

    try:
        while True:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                log.warning("kafka error: %s", message.error())
                continue
            try:
                event = json.loads(message.value())
            except (json.JSONDecodeError, TypeError):
                log.warning("skipping a message that is not JSON on %s", message.topic())
                continue

            if message.topic() == "model-updates":
                scorer.on_model_update(event)
                continue
            scored = scorer.handle(event)
            if scored:
                producer.produce("scores", key=scored["session_id"], value=json.dumps(scored))
                producer.poll(0)
                log.info("session %s scored %.3f", scored["session_id"], scored["data"]["score"])
    finally:
        producer.flush(10)
        consumer.close()


if __name__ == "__main__":
    main()
