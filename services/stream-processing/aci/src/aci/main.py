"""ACI service: python -m aci.main

Environment (defaults in brackets):
    KAFKA_BOOTSTRAP [localhost:29092]  GROUP_ID [aci]
    TOPICS [tool-calls.A,tool-calls.B,agent.events.v1,scores,labels]
    DETECTORS [mock_scorer]        comma-separated; "*" = all detectors (only if they share a scale)
    ALPHA_NORMAL [0.05]            share of normal sessions that may be flagged or reviewed
    ALPHA_ATTACK [0.1]             share of attack sessions that may be passed or reviewed
    SCORE_BOUND [20]               session scores are clipped to [0, SCORE_BOUND]
    STEP [decaying]  STEP_SCALE [SCORE_BOUND / 10]  STEP_EPS [0.1]
    AUDIT_RATE [0.1]  GRACE_SECONDS [2]  SEED [random]
"""
from __future__ import annotations

import json
import logging
import os
import random
import time

from aci.domain.triage import ConformalTriage
from aci.service import ACIService

log = logging.getLogger("aci")


def main() -> None:
    from confluent_kafka import Consumer, KafkaError, Producer

    env = os.environ.get
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    bootstrap = env("KAFKA_BOOTSTRAP", "localhost:29092")
    scale = env("STEP_SCALE")
    triage = ConformalTriage(alpha_normal=float(env("ALPHA_NORMAL", "0.05")),
                             alpha_attack=float(env("ALPHA_ATTACK", "0.1")),
                             bound=float(env("SCORE_BOUND", "20")), scale=float(scale) if scale else None,
                             eps=float(env("STEP_EPS", "0.1")), step=env("STEP", "decaying"))
    detectors = env("DETECTORS", "mock_scorer")
    producer = Producer({"bootstrap.servers": bootstrap})

    class KafkaSink:
        def send(self, topic, key, value):
            producer.produce(topic, key=key, value=json.dumps(value))
            producer.poll(0)

    seed = env("SEED")
    service = ACIService(triage, KafkaSink(), None if detectors == "*" else set(detectors.split(",")),
                         audit_rate=float(env("AUDIT_RATE", "0.1")), grace=float(env("GRACE_SECONDS", "2")),
                         rng=random.Random(int(seed) if seed else None))
    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": env("GROUP_ID", "aci"),
                         "auto.offset.reset": "earliest"})
    consumer.subscribe(env("TOPICS", "tool-calls.A,tool-calls.B,agent.events.v1,scores,labels").split(","))
    log.info("ACI started: alpha_normal=%s alpha_attack=%s step=%s detectors=%s", triage.alpha_normal,
             triage.alpha_attack, env("STEP", "decaying"), detectors)
    last_report = time.monotonic()
    try:
        while True:
            msg = consumer.poll(0.5)
            if msg is not None:
                if msg.error():
                    if msg.error().code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                        log.warning("kafka error: %s", msg.error())
                else:
                    try:
                        service.handle(json.loads(msg.value()), time.monotonic(), msg.topic())
                    except ValueError:
                        log.warning("skipped non-JSON message on %s", msg.topic())
            service.tick(time.monotonic())
            if time.monotonic() - last_report > 60:
                last_report = time.monotonic()
                log.info("decisions %s, audits %d, learned %d, thresholds %s", service.counts.decisions,
                         service.counts.audits, service.counts.learned, triage.status())
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        producer.flush(10)


if __name__ == "__main__":
    main()
