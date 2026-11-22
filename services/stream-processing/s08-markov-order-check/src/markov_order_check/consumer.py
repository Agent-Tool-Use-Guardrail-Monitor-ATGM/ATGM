"""Kafka loop: model-updates + tool-calls.A/B -> scores (spec Secs. 4.3, 8.1).

The only module that imports Kafka. Startup reads ``model-updates`` from the
beginning before any tool-call event is consumed, so tool-call events wait in
Kafka until the models are loaded (or the bootstrap timeout passes). Offsets
are committed only after the outputs of an event have been produced and flushed.
"""

from __future__ import annotations

import json
import logging
import signal
import time
import uuid
from typing import Callable

from .config import Settings
from .detector import MarkovOrderPipeline, Output

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

running = True


def stop_consumer(signum, frame):  # noqa: ARG001
    global running
    running = False


def _key(message) -> str | None:
    key = message.key()
    return key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else key


def _is_eof(message, kafka_error_cls) -> bool:
    err = message.error()
    return bool(err) and err.code() == kafka_error_cls._PARTITION_EOF


def bootstrap_models(pipeline: MarkovOrderPipeline, model_consumer, settings: Settings, kafka_error_cls,
                     clock: Callable[[], float] = time.monotonic) -> None:
    """Read model-updates to its end (or until the timeout) before tool calls are consumed."""
    deadline = clock() + settings.model_bootstrap_timeout_s
    saw_eof = False
    while clock() < deadline:
        message = model_consumer.poll(0.5)
        if message is None:
            if saw_eof:
                break
            continue
        if message.error():
            if _is_eof(message, kafka_error_cls):
                saw_eof = True
            else:
                logger.error("Kafka error on %s: %s", settings.model_topic, message.error())
            continue
        pipeline.handle_model(_key(message), message.value())
    loaded = pipeline.registry.agents()
    missing = [a for a in ("A", "B") if a not in loaded]
    logger.info("Model bootstrap done: loaded=%s missing=%s", loaded, missing)


def produce_outputs(producer, settings: Settings, outputs: list[Output]) -> int:
    produced = 0
    for out in outputs:
        if not out.publish:
            logger.debug("Computed, not published: %s", out.event["data"].get("check"))
            continue
        producer.produce(settings.scores_topic, key=out.agent, value=json.dumps(out.event))
        produced += 1
    if produced:
        producer.poll(0)
    return produced


def run_loop(pipeline: MarkovOrderPipeline, *, model_consumer, tool_consumer, producer, settings: Settings,
             kafka_error_cls, should_run: Callable[[], bool], clock: Callable[[], float] = time.monotonic,
             max_iterations: int | None = None) -> None:
    """Main loop, written against duck-typed consumer/producer objects so tests can use fakes."""
    bootstrap_models(pipeline, model_consumer, settings, kafka_error_cls, clock)
    tool_consumer.subscribe(list(settings.topics))
    logger.info("Markov order check started: %s -> %s", list(settings.topics), settings.scores_topic)
    iterations = 0
    last_metrics = clock()
    while should_run() and (max_iterations is None or iterations < max_iterations):
        iterations += 1
        model_message = model_consumer.poll(0)
        if model_message is not None and not model_message.error():
            pipeline.handle_model(_key(model_message), model_message.value())
        message = tool_consumer.poll(1.0)
        now = clock()
        if message is not None:
            if message.error():
                if not _is_eof(message, kafka_error_cls):
                    logger.error("Kafka error: %s", message.error())
            else:
                try:
                    outputs = pipeline.handle_event(message.topic(), message.value(), now)
                    if produce_outputs(producer, settings, outputs):
                        producer.flush(10)
                except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
                    logger.exception("Invalid event in topic %s at offset %s", message.topic(), message.offset())
                tool_consumer.commit(message=message, asynchronous=False)
        timed_out = pipeline.tick(now)
        if produce_outputs(producer, settings, timed_out):
            producer.flush(10)
        if now - last_metrics > 60:
            logger.info("metrics %s", json.dumps(pipeline.metrics.snapshot()))
            last_metrics = now


def main() -> None:
    from confluent_kafka import Consumer, KafkaError, Producer

    signal.signal(signal.SIGINT, stop_consumer)
    signal.signal(signal.SIGTERM, stop_consumer)
    settings = Settings.from_env()
    pipeline = MarkovOrderPipeline(settings)

    def assign_from_beginning(consumer, partitions):
        from confluent_kafka import OFFSET_BEGINNING

        for p in partitions:
            p.offset = OFFSET_BEGINNING
        consumer.assign(partitions)

    model_consumer = Consumer({
        "bootstrap.servers": settings.kafka_bootstrap,
        "group.id": f"{settings.kafka_group_id}-models-{uuid.uuid4()}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "enable.partition.eof": True,
    })
    model_consumer.subscribe([settings.model_topic], on_assign=assign_from_beginning)
    tool_consumer = Consumer({
        "bootstrap.servers": settings.kafka_bootstrap,
        "group.id": settings.kafka_group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    producer = Producer({"bootstrap.servers": settings.kafka_bootstrap})
    try:
        run_loop(pipeline, model_consumer=model_consumer, tool_consumer=tool_consumer, producer=producer,
                 settings=settings, kafka_error_cls=KafkaError, should_run=lambda: running)
    finally:
        tool_consumer.close()
        model_consumer.close()
        producer.flush(10)
        logger.info("Markov order check stopped")


if __name__ == "__main__":
    main()
