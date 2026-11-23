"""Agent A adapter: python -m agent_a_adapter.main

Reads DataLens telemetry from `agent.events.v1` (transactional producer, so read_committed)
and publishes it in the ATGM tool-call format to `tool-calls.A`, keyed by session id.
Messages are handled in batches; Kafka offsets are committed only after the batch is
published, so nothing is lost on a crash (replays produce the same event ids).

Environment: KAFKA_BOOTSTRAP [localhost:29092]  SOURCE_TOPIC [agent.events.v1]
             TARGET_TOPIC [tool-calls.A]  GROUP_ID [agent-a-adapter]
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from agent_a_adapter.translate import Translator

log = logging.getLogger("agent-a-adapter")


def main() -> None:
    from confluent_kafka import Consumer, KafkaError, Producer, TopicPartition

    env = os.environ.get
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    bootstrap = env("KAFKA_BOOTSTRAP", "localhost:29092")
    source, target = env("SOURCE_TOPIC", "agent.events.v1"), env("TARGET_TOPIC", "tool-calls.A")
    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": env("GROUP_ID", "agent-a-adapter"),
                         "auto.offset.reset": "earliest", "enable.auto.commit": False,
                         "isolation.level": "read_committed"})       # skip aborted transactions
    producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True})
    state = Path(env("ADAPTER_STATE", "agent-a-adapter-state.sqlite3"))
    translator, forwarded = Translator(), 0
    translator.restore(state)
    consumer.subscribe([source])
    log.info("Agent A adapter started: %s -> %s", source, target)
    try:
        while True:
            handled, started = 0, time.monotonic()
            offsets = {}
            delivery_errors = []

            def on_delivery(error, _message):
                if error is not None:
                    delivery_errors.append(error)

            while handled < 500 and time.monotonic() - started < 1.0:
                msg = consumer.poll(0.2)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                        log.warning("kafka error: %s", msg.error())
                    continue
                handled += 1
                partition = msg.partition()
                offsets[partition] = msg.offset() + 1
                if msg.offset() < translator.offsets.get(str(partition), 0):
                    continue
                try:
                    out = translator.translate(json.loads(msg.value()))
                except ValueError as e:
                    log.warning("skipped message at offset %s: %s", msg.offset(), e)
                    continue
                if out is not None:
                    producer.produce(target, key=str(out["session_id"]), value=json.dumps(out),
                                     on_delivery=on_delivery)
                    producer.poll(0)
                    forwarded += 1
            if handled:
                if producer.flush(10) or delivery_errors:
                    raise RuntimeError(f"Could not deliver adapter batch: {delivery_errors}")
                for partition, offset in offsets.items():
                    key = str(partition)
                    translator.offsets[key] = max(offset, translator.offsets.get(key, 0))
                translator.checkpoint(state)
                committed = consumer.commit(
                    offsets=[TopicPartition(source, partition, offset) for partition, offset in offsets.items()],
                    asynchronous=False,
                )
                if any(partition.error for partition in committed):
                    raise RuntimeError(f"Could not commit adapter offsets: {committed}")
                log.info("forwarded so far: %d", forwarded)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        producer.flush(10)


if __name__ == "__main__":
    main()
