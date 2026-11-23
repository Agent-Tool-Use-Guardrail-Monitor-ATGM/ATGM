"""Replay recorded DataLens telemetry into agent.events.v1, like the real publisher does.

    python -m agent_a_adapter.replay all-events.jsonl [--delay 0.5] [--max-sessions 10]

Reads JSONL files exported by datalens-collector (each line wraps the original event in
"event") or plain DataLens events. Each session is sent in one Kafka transaction, keyed by
session_id, so it tests the same path as the DataLens publisher (read_committed consumers).
Event ids are kept, so the adapter drops sessions it has already seen.

Environment: KAFKA_BOOTSTRAP [127.0.0.1:29092]  TOPIC [agent.events.v1]
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import OrderedDict


def load_sessions(lines) -> "OrderedDict[str, list[dict]]":
    """Events grouped by session (in first-seen order), each session sorted by sequence."""
    sessions: OrderedDict[str, list[dict]] = OrderedDict()
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        event = row.get("event", row)                       # collector wrapper or plain event
        sessions.setdefault(str(event["session_id"]), []).append(event)
    for events in sessions.values():
        events.sort(key=lambda e: e.get("sequence") or 0)
    return sessions


def main() -> None:
    from confluent_kafka import Producer

    env = os.environ.get
    parser = argparse.ArgumentParser(description="Replay recorded DataLens events to Kafka")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--bootstrap", default=env("KAFKA_BOOTSTRAP", "127.0.0.1:29092"))
    parser.add_argument("--topic", default=env("TOPIC", "agent.events.v1"))
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between sessions")
    parser.add_argument("--max-sessions", type=int, default=0, help="0 = all")
    args = parser.parse_args()

    sessions: OrderedDict[str, list[dict]] = OrderedDict()
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            for sid, events in load_sessions(f).items():
                sessions.setdefault(sid, []).extend(events)
    items = list(sessions.items())[: args.max_sessions or None]

    producer = Producer({"bootstrap.servers": args.bootstrap, "transactional.id": "atgm-replay",
                         "enable.idempotence": True, "acks": "all"})
    producer.init_transactions(30)
    sent = 0
    for i, (sid, events) in enumerate(items, 1):
        producer.begin_transaction()
        for event in events:
            producer.produce(args.topic, key=sid, value=json.dumps(event))
        producer.commit_transaction(30)
        sent += len(events)
        print(f"session {i}/{len(items)}: {len(events)} events")
        if args.delay:
            time.sleep(args.delay)
    print(f"done: {sent} events from {len(items)} sessions -> {args.topic} ({args.bootstrap})")


if __name__ == "__main__":
    main()
