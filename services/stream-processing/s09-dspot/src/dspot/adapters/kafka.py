"""Thin confluent-kafka wrappers: JSON messages in and out."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from confluent_kafka import Consumer, Producer

log = logging.getLogger("dspot.kafka")


class KafkaSource:
    def __init__(self, bootstrap: str, group_id: str, topics: list[str]) -> None:
        self._consumer = Consumer({
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "auto.offset.reset": "earliest",   # a new group starts from the first message
        })
        self._consumer.subscribe(topics)

    def messages(self) -> Iterator[dict]:
        while True:
            msg = self._consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                log.warning("kafka error: %s", msg.error())
                continue
            try:
                yield json.loads(msg.value())
            except (TypeError, ValueError):
                log.warning("skipped non-JSON message on %s at offset %s", msg.topic(), msg.offset())

    def close(self) -> None:
        self._consumer.close()


class KafkaSink:
    def __init__(self, bootstrap: str) -> None:
        self._producer = Producer({"bootstrap.servers": bootstrap})

    def send(self, topic: str, key: str, value: dict) -> None:
        self._producer.produce(topic, key=key, value=json.dumps(value).encode())
        self._producer.poll(0)                 # serve delivery callbacks

    def flush(self) -> None:
        self._producer.flush(10)
