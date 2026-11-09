"""Mock scorer service: python -m atgm_mocks.run_scorer

Reads tool-call events from tool-calls.A / tool-calls.B and publishes one anomaly.scored
event per tool call and per session end to `scores` (detector "mock_scorer").

Environment: KAFKA_BOOTSTRAP [localhost:29092]  TOPICS [tool-calls.A,tool-calls.B]
             SCORES_TOPIC [scores]  GROUP_ID [mock-scorer]
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from atgm_mocks.domain.scorer import MockScorer
from atgm_mocks.envelope import SCHEMA_VERSION

log = logging.getLogger("mock-scorer")
DETECTOR, MODEL_VERSION = "mock_scorer", "mock-1"


def score_event(scorer: MockScorer, event: dict) -> dict | None:
    """The anomaly.scored envelope for one tool-call event, or None if it is not scored."""
    value = scorer.score(event)
    if value is None:
        return None
    return {"schema_version": SCHEMA_VERSION, "event_id": str(uuid.uuid4()), "event_type": "anomaly.scored",
            "occurred_at": datetime.now(timezone.utc).isoformat(), "run_id": event.get("run_id"),
            "session_id": event.get("session_id"), "sequence": event.get("sequence"), "request_id": None,
            "data": {"scored_event_id": event["event_id"], "agent_id": event["data"]["agent_id"],
                     "detector": DETECTOR, "model_version": MODEL_VERSION, "score": round(value, 6)}}


def main() -> None:
    from confluent_kafka import Consumer, Producer

    env = os.environ.get
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    bootstrap = env("KAFKA_BOOTSTRAP", "localhost:29092")
    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": env("GROUP_ID", "mock-scorer"),
                         "auto.offset.reset": "earliest"})
    consumer.subscribe(env("TOPICS", "tool-calls.A,tool-calls.B").split(","))
    producer = Producer({"bootstrap.servers": bootstrap})
    scores_topic = env("SCORES_TOPIC", "scores")
    scorer = MockScorer()
    sent = 0
    log.info("mock scorer started")
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            try:
                out = score_event(scorer, json.loads(msg.value()))
            except (ValueError, KeyError, TypeError) as e:
                log.warning("skipped message at %s/%s: %s", msg.topic(), msg.offset(), e)
                continue
            if out is not None:
                producer.produce(scores_topic, key=out["data"]["agent_id"], value=json.dumps(out))
                producer.poll(0)
                sent += 1
                if sent % 5000 == 0:
                    log.info("scores published: %d", sent)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        producer.flush(10)


if __name__ == "__main__":
    main()
