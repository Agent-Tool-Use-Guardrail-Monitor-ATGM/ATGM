"""Demo for the running stack: python -m dspot.demo

1. Publishes synthetic anomaly.scored events to `scores` for one (agent, detector) stream:
   a normal warm-up, then a drifting stream with injected attacks.
2. Acts as a simulated reviewer: reads alarm.raised events from `review-queue` and answers
   each one on `labels` ("attack" if it was injected, otherwise "false_alarm").

Watch the topics in kafka-ui (http://localhost:8080) and the service log
(docker compose logs -f dspot).
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timezone

import numpy as np

from dspot.adapters import events


def envelope(event_type: str, data: dict, session_id: str, sequence: int) -> dict:
    return {"schema_version": events.SCHEMA_VERSION, "event_id": str(uuid.uuid4()),
            "event_type": event_type, "occurred_at": datetime.now(timezone.utc).isoformat(),
            "run_id": RUN_ID, "session_id": session_id, "sequence": sequence,
            "request_id": None, "data": data}


RUN_ID = str(uuid.uuid4())


def main(argv=None) -> None:
    from confluent_kafka import Consumer, Producer

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bootstrap", default="localhost:29092")
    p.add_argument("--warmup", type=int, default=3_000, help="must match DSPOT_WARMUP of the service")
    p.add_argument("--n", type=int, default=10_000, help="scores after the warm-up")
    p.add_argument("--attacks", type=int, default=20)
    p.add_argument("--agent", default="B")
    p.add_argument("--detector", default="demo_detector")
    p.add_argument("--review-seconds", type=float, default=30.0)
    args = p.parse_args(argv)

    rng = np.random.default_rng()
    scores = np.concatenate([rng.normal(size=args.warmup),
                             np.linspace(0.0, 4.0, args.n) + rng.normal(size=args.n)])
    attacks = set((args.warmup + rng.choice(args.n, size=args.attacks, replace=False)).tolist())
    for i in attacks:
        scores[i] += rng.uniform(6.0, 10.0)

    producer = Producer({"bootstrap.servers": args.bootstrap})
    session = str(uuid.uuid4())
    refs = {}
    for i, value in enumerate(scores):
        ref = str(uuid.uuid4())
        refs[ref] = i in attacks
        data = {"scored_event_id": ref, "agent_id": args.agent, "detector": args.detector,
                "model_version": "demo", "score": float(value)}
        producer.produce("scores", key=args.agent, value=json.dumps(envelope(events.SCORED, data, session, i + 1)))
        producer.poll(0)
    producer.flush(30)
    print(f"sent {len(scores)} scores ({args.warmup} warm-up, {len(attacks)} attacks)")

    consumer = Consumer({"bootstrap.servers": args.bootstrap, "group.id": f"demo-reviewer-{RUN_ID}",
                         "auto.offset.reset": "earliest"})
    consumer.subscribe(["review-queue"])
    caught = false_alarms = 0
    deadline = time.time() + args.review_seconds
    while time.time() < deadline:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        alarm = json.loads(msg.value())
        ref = alarm.get("data", {}).get("scored_event_id")
        if alarm.get("event_type") != events.ALARM or ref not in refs:
            continue                                   # alarms from other runs or detectors
        is_attack = refs[ref]
        caught += is_attack
        false_alarms += not is_attack
        verdict = {"scored_event_id": ref, "detector": args.detector,
                   "verdict": "attack" if is_attack else "false_alarm"}
        producer.produce("labels", key=args.agent, value=json.dumps(envelope(events.LABELLED, verdict, session, 1)))
        producer.poll(0)
    producer.flush(10)
    consumer.close()
    print(f"reviewed alarms: {caught}/{len(attacks)} attacks caught, {false_alarms} false alarms "
          f"({false_alarms / args.n:.3%} of the scored stream)")


if __name__ == "__main__":
    main()
