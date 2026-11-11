"""Storage sink service: python -m storage_sink.main

Reads the ATGM topics and stores every event in analytics_db. Messages are written in
batches (up to BATCH_SIZE or BATCH_SECONDS); Kafka offsets are committed only after the
database commit, so nothing is lost on a crash and duplicates are ignored.

Environment (defaults in brackets):
    KAFKA_BOOTSTRAP [localhost:29092]  GROUP_ID [storage-sink]
    TOPICS [tool-calls.A,tool-calls.B,agent.events.v1,scores,alerts,labels,flags,drift,stats,toolset-config]
    BATCH_SIZE [500]  BATCH_SECONDS [1]
    DB_HOST / DB_PORT / DB_NAME [analytics_db] / DB_USER [analytics_svc] / DB_PASSWORD
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter

from storage_sink.domain.rows import Row, to_row

log = logging.getLogger("storage-sink")
DEFAULT_TOPICS = "tool-calls.A,tool-calls.B,agent.events.v1,scores,alerts,labels,flags,drift,stats,toolset-config"


def decode(topic: str, raw: bytes) -> Row | None:
    try:
        return to_row(topic, json.loads(raw))
    except (TypeError, ValueError) as e:
        log.warning("skipped message on %s: %s", topic, e)
        return None


def main() -> None:
    from confluent_kafka import Consumer, KafkaError

    from storage_sink.adapters.postgres import PostgresWriter

    env = os.environ.get
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    writer = PostgresWriter(host=env("DB_HOST", "localhost"), port=int(env("DB_PORT", "5432")),
                            dbname=env("DB_NAME", "analytics_db"), user=env("DB_USER", "analytics_svc"),
                            password=env("DB_PASSWORD", ""))
    consumer = Consumer({"bootstrap.servers": env("KAFKA_BOOTSTRAP", "localhost:29092"),
                         "group.id": env("GROUP_ID", "storage-sink"), "auto.offset.reset": "earliest",
                         "enable.auto.commit": False})
    topics = env("TOPICS", DEFAULT_TOPICS).split(",")
    consumer.subscribe(topics)
    batch_size, batch_seconds = int(env("BATCH_SIZE", "500")), float(env("BATCH_SECONDS", "1"))
    stored: Counter[str] = Counter()
    log.info("storage sink started: %s", ", ".join(topics))
    try:
        while True:
            rows, started = [], time.monotonic()
            while len(rows) < batch_size and time.monotonic() - started < batch_seconds:
                msg = consumer.poll(0.2)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                        log.warning("kafka error: %s", msg.error())
                    continue
                row = decode(msg.topic(), msg.value())
                if row is not None:
                    rows.append(row)
                    stored[row.table] += 1
            if rows:
                writer.write(rows)
                consumer.commit(asynchronous=False)        # only after the rows are safely stored
                if sum(stored.values()) // 5000 != (sum(stored.values()) - len(rows)) // 5000:
                    log.info("stored so far: %s", dict(stored))
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        writer.close()


if __name__ == "__main__":
    main()
