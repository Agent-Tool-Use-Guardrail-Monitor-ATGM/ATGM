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

from agent_a_adapter.translate import Translator

log = logging.getLogger("agent-a-adapter")


def main() -> None:
    from confluent_kafka import Consumer, KafkaError, Producer

    env = os.environ.get
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    bootstrap = env("KAFKA_BOOTSTRAP", "localhost:29092")
    source, target = env("SOURCE_TOPIC", "agent.events.v1"), env("TARGET_TOPIC", "tool-calls.A")
    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": env("GROUP_ID", "agent-a-adapter"),
                         "auto.offset.reset": "earliest", "enable.auto.commit": False,
                         "isolation.level": "read_committed"})       # skip aborted transactions
    producer = Producer({"bootstrap.servers": bootstrap})
    consumer.subscribe([source])
    translator, forwarded = Translator(), 0
    log.info("Agent A adapter started: %s -> %s", source, target)
    try:
        while True:
            handled, started = 0, time.monotonic()
            while handled < 500 and time.monotonic() - started < 1.0:
                msg = consumer.poll(0.2)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                        log.warning("kafka error: %s", msg.error())
                    continue
                handled += 1
                try:
                    out = translator.translate(json.loads(msg.value()))
                except ValueError as e:
                    log.warning("skipped message at offset %s: %s", msg.offset(), e)
                    continue
                if out is not None:
                    producer.produce(target, key=str(out["session_id"]), value=json.dumps(out))
                    producer.poll(0)
                    forwarded += 1
            if handled:
                producer.flush(10)
                consumer.commit(asynchronous=False)                 # only after the batch is published
                log.info("forwarded so far: %d", forwarded)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        producer.flush(10)


if __name__ == "__main__":
    main()
