"""S03 service: python -m sliding_window.main

Environment variables (default):
    KAFKA_BOOTSTRAP (localhost:29092), KAFKA_GROUP_ID (sliding-top-k)
    TOPK_K (3), TOPK_NODES (3), TOPK_SLOT_SECONDS (30), TOPK_UNITS (20), TOPK_EPSILON (5)
"""
import json
import logging
import os
import signal
import time

from confluent_kafka import Consumer, Producer

from sliding_window.domain.violations import ToolCallMemory, ViolationReader
from sliding_window.service import Settings, TopKService

INPUT_TOPICS = ["tool-calls.A", "tool-calls.B", "alerts", "flags"]


def setting(name, default):
    return os.environ.get(name, default)


def stop(signal_number, frame):
    raise KeyboardInterrupt        # docker stop sends SIGTERM: shut down cleanly


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    log = logging.getLogger("sliding_window")
    signal.signal(signal.SIGTERM, stop)

    settings = Settings(
        k=int(setting("TOPK_K", "3")),
        nodes=int(setting("TOPK_NODES", "3")),
        slot_seconds=float(setting("TOPK_SLOT_SECONDS", "30")),
        units=int(setting("TOPK_UNITS", "20")),
        epsilon=float(setting("TOPK_EPSILON", "5")),
    )
    service = TopKService(settings, ViolationReader(ToolCallMemory()))

    bootstrap = setting("KAFKA_BOOTSTRAP", "localhost:29092")
    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": setting("KAFKA_GROUP_ID", "sliding-top-k"),
        "auto.offset.reset": "latest",       # live monitor: start from now, not from old events
    })
    producer = Producer({"bootstrap.servers": bootstrap})
    consumer.subscribe(INPUT_TOPICS)
    log.info("S03 sliding top-k started: %s -> scores, stats", INPUT_TOPICS)

    try:
        while True:
            message = consumer.poll(1.0)
            output = []
            if message is not None and not message.error():
                try:
                    event = json.loads(message.value())
                    if isinstance(event, dict):
                        output = service.handle(message.topic(), message.partition(), event, time.time())
                except ValueError:
                    log.warning("Skipped invalid event in %s at offset %s", message.topic(), message.offset())
            output += service.tick(time.time())
            for topic, key, event in output:
                producer.produce(topic, key=key, value=json.dumps(event))
            producer.poll(0)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        producer.flush(10)


if __name__ == "__main__":
    main()
