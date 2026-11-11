import json
import logging
import os
import signal
import time

from confluent_kafka import Consumer, Producer

from sliding_window.domain.violations import ToolCallMemory, ViolationReader
from sliding_window.service import Settings, TopKService


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
        epsilon=float(setting("TOPK_EPSILON", "1")),
        stats_every=float(setting("STATS_EVERY", "60")),
    )
    sources = setting("SOURCES", "alarms").split(",")
    flag_types = setting("FLAG_TYPES", "violation.flagged").split(",") if "flags" in sources else []
    service = TopKService(settings, ViolationReader(ToolCallMemory(), flag_types))

    topics = ["tool-calls.A", "tool-calls.B"]
    if "alarms" in sources:
        topics.append(settings.alert_topic)
    if "flags" in sources:
        topics.append(settings.flag_topic)

    bootstrap = setting("KAFKA_BOOTSTRAP", "localhost:29092")
    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": setting("KAFKA_GROUP_ID", "sliding-window-topk"),
        "auto.offset.reset": setting("OFFSET_RESET", "latest"),   # live monitor: start from now
    })
    producer = Producer({"bootstrap.servers": bootstrap})
    consumer.subscribe(topics)
    log.info("P4 top-k service started: %s", topics)

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