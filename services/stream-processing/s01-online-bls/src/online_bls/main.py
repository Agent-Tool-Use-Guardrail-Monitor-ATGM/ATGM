"""Consume committed ATGM events and publish session-prefix scores."""

import json
import logging
import os
from pathlib import Path

from online_bls.service import LABEL_TOPIC, SCORE_TOPIC, TOOL_TOPICS, ClassifierService

log = logging.getLogger(__name__)


def publish_pending(service: ClassifierService, producer) -> None:
    for event in service.pending_scores():
        delivery_errors = []
        def on_delivery(error, _message, errors=delivery_errors):
            if error is not None:
                errors.append(error)

        producer.produce(
            SCORE_TOPIC,
            key=event["data"]["agent_id"],
            value=json.dumps(event).encode(),
            on_delivery=on_delivery,
        )
        if producer.flush(10) or delivery_errors:
            raise RuntimeError(f"Online-BLS score delivery failed for {event['event_id']}: {delivery_errors}")
        service.acknowledge_score(event["event_id"])


def consume(service: ClassifierService, consumer, producer) -> None:
    publish_pending(service, producer)
    while True:
        message = consumer.poll(1.0)
        if message is None:
            continue
        if message.error():
            log.warning("Kafka consumer error: %s", message.error())
            continue
        try:
            event = json.loads(message.value())
        except (TypeError, ValueError):
            log.warning("Skipping invalid JSON on %s offset %s", message.topic(), message.offset())
        else:
            service.handle(message.topic(), event)
            publish_pending(service, producer)
        consumer.commit(message=message, asynchronous=False)


def main() -> None:
    from confluent_kafka import Consumer, Producer

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
    path = Path(os.getenv("ONLINE_BLS_STATE", "online-bls.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    service = ClassifierService(path)
    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": os.getenv("ONLINE_BLS_GROUP_ID", "online-bls"),
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "isolation.level": "read_committed",
    })
    producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True})
    try:
        consumer.subscribe([*TOOL_TOPICS, LABEL_TOPIC])
        consume(service, consumer, producer)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        service.close()


if __name__ == "__main__":
    main()
