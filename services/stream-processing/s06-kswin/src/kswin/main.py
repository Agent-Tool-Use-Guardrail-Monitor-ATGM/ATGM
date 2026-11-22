"""Kafka entry point for S06 KSWIN drift detection."""

from __future__ import annotations

import json
import logging
import os
import signal
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer

from kswin.service import KSWINService


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("kswin")


class KafkaSink:
    """Publish JSON events to Kafka and track delivery failures."""

    def __init__(self, producer: Producer) -> None:
        self.producer = producer
        self.delivery_errors: list[str] = []

    def send(self, topic: str, key: str, value: dict[str, Any]) -> None:
        def on_delivery(error: Any, message: Any) -> None:
            if error is not None:
                self.delivery_errors.append(str(error))

        self.producer.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=json.dumps(value).encode("utf-8"),
            callback=on_delivery,
        )

    def check_delivery(self) -> None:
        if self.delivery_errors:
            errors = self.delivery_errors.copy()
            self.delivery_errors.clear()
            raise RuntimeError(f"Kafka delivery failed: {errors}")


def main() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
    group_id = os.getenv("KAFKA_GROUP_ID", "s06-kswin")

    topics = [
        topic.strip()
        for topic in os.getenv(
            "KAFKA_TOPICS",
            "tool-calls.A,tool-calls.B,scores",
        ).split(",")
        if topic.strip()
    ]

    if not topics:
        raise ValueError("KAFKA_TOPICS must contain at least one topic")

    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })

    producer = Producer({
        "bootstrap.servers": bootstrap,
    })

    sink = KafkaSink(producer)

    service = KSWINService(
        sink=sink,
        window_size=int(os.getenv("KSWIN_WINDOW_SIZE", "100")),
        stat_size=int(os.getenv("KSWIN_STAT_SIZE", "30")),
        alpha=float(os.getenv("KSWIN_ALPHA", "0.005")),
    )

    running = True

    def stop(signum: int, frame: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    consumer.subscribe(topics)

    logger.info("KSWIN subscribed to %s", topics)

    try:
        while running:
            message = consumer.poll(1.0)

            if message is None:
                producer.poll(0)
                continue

            if message.error():
                if message.error().code() == KafkaError._PARTITION_EOF:
                    continue

                raise KafkaException(message.error())

            try:
                event = json.loads(message.value().decode("utf-8"))

                if not isinstance(event, dict):
                    raise ValueError("Kafka message must contain a JSON object")

                service.process(event, message.topic())

                # Deliver output before committing the input message.
                remaining = producer.flush(10)

                if remaining:
                    raise RuntimeError(
                        f"{remaining} Kafka message(s) remain undelivered"
                    )

                sink.check_delivery()

                consumer.commit(message=message, asynchronous=False)

            except (ValueError, TypeError, json.JSONDecodeError):
                logger.exception(
                    "Invalid event on topic %s; committing malformed message",
                    message.topic(),
                )
                consumer.commit(message=message, asynchronous=False)

    finally:
        logger.info("Stopping KSWIN consumer")
        consumer.close()
        producer.flush(10)


if __name__ == "__main__":
    main()
