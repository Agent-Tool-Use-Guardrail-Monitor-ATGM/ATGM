import json
import logging
import os
from pathlib import Path

from optwin.detector import Optwin
from optwin.service import DRIFT_TOPIC, ERROR_TOPIC, DriftService

log = logging.getLogger(__name__)


def publish_pending(service, producer):
    for event_id, payload in service.pending():
        delivered = []

        def on_delivery(error, _message, result=delivered):
            result.append(error)

        producer.produce(DRIFT_TOPIC, key=json.loads(payload)["data"]["agent_id"], value=payload,
                         on_delivery=on_delivery)
        if producer.flush(10) or delivered != [None]:
            raise RuntimeError(f"OPTWIN drift delivery failed for {event_id}: {delivered}")
        service.acknowledge(event_id)


def consume(service, consumer, producer):
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
            log.warning("Skipping invalid JSON at offset %s", message.offset())
        else:
            service.handle(event)
            publish_pending(service, producer)
        consumer.commit(message=message, asynchronous=False)


def main():
    from confluent_kafka import Consumer, Producer

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
    path = Path(os.getenv("OPTWIN_STATE", "optwin.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    service = DriftService(path, Optwin())
    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": os.getenv("OPTWIN_GROUP_ID", "optwin"),
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "isolation.level": "read_committed",
    })
    producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True})
    try:
        consumer.subscribe([ERROR_TOPIC])
        consume(service, consumer, producer)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        service.db.close()


if __name__ == "__main__":
    main()
