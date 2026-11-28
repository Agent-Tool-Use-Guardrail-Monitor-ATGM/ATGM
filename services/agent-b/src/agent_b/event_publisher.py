"""Replays events saved by the agent (JSONL) to Kafka.

Usage:
    python event_publisher.py events_for_scenario_01.jsonl
    python event_publisher.py events_for_scenario_01.jsonl --topic tool-calls.B --delay 0.1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from confluent_kafka import Producer

PROJECT_ROOT = Path(__file__).resolve().parents[4]
EVENTS_DIR = PROJECT_ROOT / "dataset" / "agent_b" / "events"


def main() -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(description="Publish saved events of Agent B to Kafka")
    parser.add_argument("file", help="Event file name in dataset/agent_b/events, e.g. 'events_for_scenario_01.jsonl'")
    parser.add_argument("--bootstrap", default=env("KAFKA_BOOTSTRAP", "127.0.0.1:29092"))
    parser.add_argument("--topic", default=env("TOPIC_B", "tool-calls.B"))
    parser.add_argument("--delay", type=float, default=0.0,
                        help="Seconds to wait between events (0 = as fast as possible)")
    args = parser.parse_args()

    path = EVENTS_DIR / args.file
    if not path.is_file():
        sys.exit(f"Event file not found: {path}")

    delivery_errors = 0

    def on_delivery(err, msg) -> None:
        nonlocal delivery_errors
        if err is not None:
            delivery_errors += 1
            print(f"Delivery failed: {err}", file=sys.stderr)

    producer = Producer({"bootstrap.servers": args.bootstrap})

    sent = skipped = 0
    print(f"Publishing {path} -> {args.topic} ({args.bootstrap})")
    try:
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    key = event["session_id"]
                except (json.JSONDecodeError, KeyError) as exc:
                    print(f"Skipping line {line_no}: {type(exc).__name__}: {exc}", file=sys.stderr)
                    skipped += 1
                    continue

                value = json.dumps(event, default=str)
                while True:
                    try:
                        producer.produce(args.topic, key=key, value=value, on_delivery=on_delivery)
                        break
                    except BufferError:  # local queue full: let it drain, then retry
                        producer.poll(0.5)
                producer.poll(0)
                sent += 1

                if args.delay:
                    time.sleep(args.delay)
    finally:
        remaining = producer.flush(10)
        if remaining:
            print(f"Warning: {remaining} message(s) were not delivered before the timeout", file=sys.stderr)

    print(f"Done: {sent} queued, {skipped} skipped, {delivery_errors} delivery error(s)")


if __name__ == "__main__":
    main()