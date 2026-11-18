"""Kafka entry point for S05 SpaceSaving±."""

from __future__ import annotations

import json
import logging
import os
import signal

from spacesaving.service import SpaceSavingService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spacesaving")

running = True


class KafkaSink:
    """Publish service output to Kafka."""

    def __init__(self, producer):
        self.producer = producer

    def send(self, topic: str, key: str, value: dict) -> None:
        self.producer.produce(
            topic,
            key=key.encode("utf-8"),
            value=json.dumps(value).encode("utf-8"),
        )
        self.producer.poll(0)


def stop_consumer(signum, frame):
    global running
    running = False


def main():
    from confluent_kafka import Consumer, KafkaError, Producer

    global running
    running = True

    signal.signal(signal.SIGINT, stop_consumer)
    signal.signal(signal.SIGTERM, stop_consumer)

    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
    group_id = os.getenv("KAFKA_GROUP_ID", "spacesaving-consumer")
    topics = [
        topic.strip()
        for topic in os.getenv(
            "TOPICS", "tool-calls.A,tool-calls.B,labels"
        ).split(",")
        if topic.strip()
    ]

    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })

    producer = Producer({"bootstrap.servers": bootstrap})
    sink = KafkaSink(producer)
    service = SpaceSavingService(
        sink,
        capacity=int(os.getenv("COUNTER_CAPACITY", "100")),
        window_seconds=int(os.getenv("WINDOW_SECONDS", "60")),
        top_k=int(os.getenv("TOP_K", "10")),
    )

    consumer.subscribe(topics)
    logger.info("SpaceSaving consumer started: %s -> stats", topics)

    try:
        while running:
            message = consumer.poll(1.0)

            if message is None:
                continue

            if message.error():
                if message.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Kafka error: %s", message.error())
                continue

            try:
                event = json.loads(message.value().decode("utf-8"))

                if not isinstance(event, dict):
                    raise ValueError("Kafka event must be a JSON object")

                service.handle(event, message.topic())

            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                logger.exception(
                    "Invalid event in topic %s at offset %s",
                    message.topic(),
                    message.offset(),
                )

            consumer.commit(message=message, asynchronous=False)

    finally:
        consumer.close()
        producer.flush(10)
        logger.info("SpaceSaving consumer stopped")


if __name__ == "__main__":
    main()
