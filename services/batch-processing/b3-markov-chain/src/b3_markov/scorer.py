"""B3 session scorer: when an Agent B session ends, scores it with the newest Markov-chain table.

tool-calls.B ─> SessionBuffer (session.ended) ─> transition table ─> scores (detector b3_markov)
model-updates (model.trained, embedded table or path) ─> reload the table
"""
import json
import logging
import os
from pathlib import Path

from b3_markov.adapters import model_store
from b3_markov.domain.sessions import SessionBuffer
from b3_markov.domain.training import from_table
from b3_markov.events import score_event

log = logging.getLogger("b3-scorer")


class Scorer:
    def __init__(self, models_dir: Path, kind: str | None = None):
        self.models_dir = models_dir
        self.kind = kind                     # e.g. "additive": only models whose version ends so
        self.sessions = SessionBuffer()
        self.model = None
        self.version = None
        self.order = 1
        self.threshold = None
        folder = model_store.latest(models_dir, kind)
        if folder is None:
            log.warning("no B3 model in %s yet, sessions are not scored", models_dir)
        else:
            self.use(model_store.load(folder), folder.name)

    def use(self, table: dict, version: str) -> None:
        calibration = table.get("calibration") or {}
        self.model = from_table(table)
        self.version = version
        self.order = calibration.get("primary_order", self.model.orders[0])
        self.threshold = (calibration.get("threshold") or {}).get(str(self.order))
        log.info("B3 model loaded: %s (order %s)", version, self.order)

    def on_model_update(self, event: dict) -> None:
        data = event.get("data") or {}
        if data.get("model") != model_store.MODEL_NAME:
            return
        version = data.get("version", "")
        if self.kind and not version.endswith(self.kind):
            return
        if data.get("transition_table"):
            self.use(data["transition_table"], version)
        elif data.get("path") and (Path(data["path"]) / model_store.TABLE_FILE).exists():
            self.use(model_store.load(Path(data["path"])), version)
        else:
            log.warning("model update %s has no usable table", version)

    def handle(self, event: dict) -> dict | None:
        finished = self.sessions.add(event)
        if finished is None or self.model is None:
            return None
        result = self.model.score(self.order, finished.call_objects)
        return score_event(finished, result, self.version, self.threshold, run_id=event.get("run_id"))


def message_key(scored: dict) -> str | None:
    """Kafka key of an anomaly.scored message: the agent id (A or B), None if the event has none."""
    return scored["data"].get("agent_id") or None


def main() -> None:
    from confluent_kafka import Consumer, Producer

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
    input_topics = os.environ.get("B3_INPUT_TOPICS", "tool-calls.B").split(",")
    scorer = Scorer(Path(os.environ.get("B3_MODELS_DIR", "models")), os.environ.get("B3_MODEL_KIND") or None)

    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": "b3-scorer", "auto.offset.reset": "latest"})
    consumer.subscribe([*input_topics, "model-updates"])
    producer = Producer({"bootstrap.servers": bootstrap})
    log.info("B3 scorer started: %s -> scores", ", ".join(input_topics))

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
                producer.produce("scores", key=message_key(scored), value=json.dumps(scored))
                producer.poll(0)
                log.info("session %s scored %.3f", scored["session_id"], scored["data"]["score"])
    finally:
        producer.flush(10)
        consumer.close()


if __name__ == "__main__":
    main()