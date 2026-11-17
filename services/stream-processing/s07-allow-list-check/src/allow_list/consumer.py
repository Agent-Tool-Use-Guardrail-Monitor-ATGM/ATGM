"""Kafka glue: tool-calls.A / tool-calls.B + toolset-config  ->  allow-list check  ->  flags.

Two consumers: one reads `toolset-config` from the beginning (it is a "current state" topic) and is polled
without blocking between tool-call messages, so a changed toolset applies within a second; the other
reads the tool calls in a consumer group and commits after the flags were handed to the producer.
Kafka classes are only imported in main(), so run() can be tested with fakes.
"""
from __future__ import annotations

import json
import logging
import signal
import time

from allow_list import config
from allow_list.detector import AllowListDetector
from allow_list.policy import load_policy
from allow_list.service import AllowListService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_BAD_MESSAGE = (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError)
running = True


def stop_consumer(signum, frame):
    global running
    running = False


class ToolsetReader:
    """Keeps the detector's toolsets current from the `toolset-config` topic."""

    def __init__(self, consumer, service: AllowListService, is_eof, topic_partition=None) -> None:
        self.consumer, self.service, self.is_eof = consumer, service, is_eof
        self.topic = service.toolset_topic
        self._tp = topic_partition
        self.partitions = 0
        self._last_try = 0.0

    def connect(self, timeout_s: float) -> None:
        """Assign all partitions from the beginning and read until the end (the current toolsets)."""
        self._last_try = time.monotonic()
        if self._tp is None:
            from confluent_kafka import OFFSET_BEGINNING, TopicPartition
            self._tp = lambda topic, partition: TopicPartition(topic, partition, OFFSET_BEGINNING)
        meta = self.consumer.list_topics(self.topic, timeout=10).topics.get(self.topic)
        parts = sorted(meta.partitions) if meta is not None and meta.error is None else []
        if not parts:
            logger.warning("topic %s not found: tool allow-list is not checked until it exists", self.topic)
            return
        self.consumer.assign([self._tp(self.topic, p) for p in parts])
        self.partitions = len(parts)
        at_end, deadline = set(), time.monotonic() + timeout_s
        while len(at_end) < self.partitions and time.monotonic() < deadline:
            self._apply(self.consumer.poll(0.5), at_end)
        logger.info("toolsets loaded for agents %s", sorted(self.service.detector.toolsets))

    def poll(self, limit: int = 100) -> None:
        if not self.partitions:
            if time.monotonic() - self._last_try > 30:
                self.connect(config.CONFIG_BOOTSTRAP_TIMEOUT_S)
            return
        for _ in range(limit):
            message = self.consumer.poll(0)
            if message is None:
                return
            self._apply(message)

    def _apply(self, message, at_end: set | None = None) -> None:
        if message is None:
            return
        if message.error():
            if self.is_eof(message.error()):
                if at_end is not None:
                    at_end.add(message.partition())
            else:
                logger.error("Kafka error on %s: %s", self.topic, message.error())
            return
        try:
            self.service.handle(self.topic, message.key(), message.value())
            logger.info("toolset update at offset %s: %s", message.offset(), sorted(self.service.detector.toolsets))
        except _BAD_MESSAGE:
            logger.exception("Invalid toolset-config message at offset %s", message.offset())


def run(calls_consumer, toolsets: ToolsetReader, producer, service: AllowListService, is_eof,
        keep_running=lambda: running) -> int:
    """Main loop; returns the number of flags published."""
    flagged = 0

    def delivered(err, msg):
        if err is not None:
            logger.error("flag not delivered: %s", err)

    toolsets.connect(config.CONFIG_BOOTSTRAP_TIMEOUT_S)
    while keep_running():
        toolsets.poll()
        message = calls_consumer.poll(1.0)
        if message is None:
            continue
        if message.error():
            if not is_eof(message.error()):
                logger.error("Kafka error: %s", message.error())
            continue

        try:
            for topic, key, event in service.handle(message.topic(), message.key(), message.value()):
                try:
                    producer.produce(topic, key=key, value=json.dumps(event), on_delivery=delivered)
                except BufferError:
                    producer.poll(1.0)
                    producer.produce(topic, key=key, value=json.dumps(event), on_delivery=delivered)
                producer.poll(0)
                flagged += 1
                data = event["data"]
                logger.debug("agent=%s session=%s tool=%s rule=%s severity=%s", data["agent_id"],
                             event["session_id"], data["tool_name"], data["rule"], data["severity"])
                if flagged % 100 == 0:
                    logger.info("flags published: %d", flagged)
        except _BAD_MESSAGE:
            logger.exception("Invalid event in topic %s at offset %s", message.topic(), message.offset())

        calls_consumer.commit(message=message, asynchronous=True)
    return flagged


def main() -> None:
    from confluent_kafka import Consumer, KafkaError, Producer

    signal.signal(signal.SIGINT, stop_consumer)
    signal.signal(signal.SIGTERM, stop_consumer)

    def is_eof(error) -> bool:
        return error.code() == KafkaError._PARTITION_EOF

    detector = AllowListDetector(load_policy(config.POLICY_FILE), max_sessions=config.MAX_SESSIONS)
    service = AllowListService(detector, config.TOOLSET_TOPIC, config.FLAGS_TOPIC)

    toolset_consumer = Consumer({
        "bootstrap.servers": config.KAFKA_BOOTSTRAP,
        "group.id": f"{config.KAFKA_GROUP_ID}-toolsets",       # unused: partitions are assigned, not committed
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "enable.partition.eof": True,
    })
    calls_consumer = Consumer({
        "bootstrap.servers": config.KAFKA_BOOTSTRAP,
        "group.id": config.KAFKA_GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    producer = Producer({"bootstrap.servers": config.KAFKA_BOOTSTRAP})

    calls_consumer.subscribe(config.TOPICS)
    logger.info("Allow-list consumer started: %s + %s -> %s (policy %s)", config.TOPICS, config.TOOLSET_TOPIC,
                config.FLAGS_TOPIC, detector.version)
    try:
        run(calls_consumer, ToolsetReader(toolset_consumer, service, is_eof), producer, service, is_eof)
    finally:
        calls_consumer.close()
        toolset_consumer.close()
        producer.flush(10)
        logger.info("Allow-list consumer stopped")


if __name__ == "__main__":
    main()
