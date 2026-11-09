"""Review queue service: python -m review_queue.main

Reads `review-queue`, answers each item after REVIEW_DELAY_SECONDS as a simulated reviewer
(ground truth from scenario_db), and publishes review.labelled events to `labels`.

Environment (defaults in brackets):
    KAFKA_BOOTSTRAP [localhost:29092]  REVIEW_TOPIC [review-queue]  LABELS_TOPIC [labels]
    REVIEW_DELAY_SECONDS [10]  REVIEWER_ERROR_RATE [0]  SEED [random]
    DB_HOST / DB_PORT / DB_NAME [scenario_db] / DB_USER / DB_PASSWORD
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from collections import Counter

from review_queue.adapters.events import label_event
from review_queue.domain.queue import ReviewQueue, parse_item

log = logging.getLogger("review-queue")


def main() -> None:
    from confluent_kafka import Consumer, Producer

    from review_queue.adapters.ground_truth import GroundTruthLookup

    env = os.environ.get
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    bootstrap = env("KAFKA_BOOTSTRAP", "localhost:29092")
    seed = env("SEED")
    queue = ReviewQueue(GroundTruthLookup(), delay=float(env("REVIEW_DELAY_SECONDS", "10")),
                        error_rate=float(env("REVIEWER_ERROR_RATE", "0")),
                        rng=random.Random(int(seed) if seed else None))
    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": env("GROUP_ID", "review-queue"),
                         "auto.offset.reset": "earliest"})
    consumer.subscribe([env("REVIEW_TOPIC", "review-queue")])
    producer = Producer({"bootstrap.servers": bootstrap})
    labels_topic = env("LABELS_TOPIC", "labels")
    verdicts: Counter[str] = Counter()
    log.info("review queue started (delay %.0fs, error rate %.2f)", queue.delay, queue.error_rate)
    try:
        while True:
            msg = consumer.poll(0.5)
            if msg is not None and not msg.error():
                try:
                    item = parse_item(json.loads(msg.value()))
                except ValueError as e:
                    log.warning("skipped message at offset %s: %s", msg.offset(), e)
                    item = None
                if item is not None:
                    queue.submit(item, time.monotonic())
            for label in queue.due(time.monotonic()):
                producer.produce(labels_topic, key=label.item.agent_id or "", value=json.dumps(label_event(label)))
                verdicts[label.verdict] += 1
                log.info("reviewed %s/%s session %s: %s%s", label.item.agent_id, label.item.detector,
                         label.item.session_id, label.verdict,
                         f" ({label.violation_type})" if label.violation_type else "")
                if sum(verdicts.values()) % 100 == 0:
                    log.info("totals: %s, waiting: %d, dropped: %d", dict(verdicts), len(queue), queue.dropped)
            producer.poll(0)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        producer.flush(10)


if __name__ == "__main__":
    main()
