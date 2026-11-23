"""Publish sample sessions of Agent A and B for local runs (like S04's send_test_events).

    PYTHONPATH=src python -m markov_order_check.send_test_events --with-demo-model

``--with-demo-model`` first publishes small demo models to ``model-updates``
(keys ``b3-markov-chain.A`` / ``.B``) so the pipeline can run before B3 has
announced real models. Do not use it on a shared broker where B3 publishes.
"""

from __future__ import annotations

import argparse
import json
import os

from .demo import DEMO_ATTACKS, DEMO_SESSIONS, DEMO_VOCABULARY, build_table, model_message, session_events


def main(argv: list[str] | None = None) -> None:
    from confluent_kafka import Producer

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-demo-model", action="store_true")
    parser.add_argument("--models-only", action="store_true", help="publish only the demo models")
    parser.add_argument("--repeat", type=int, default=5, help="copies of each normal session per agent")
    args = parser.parse_args(argv)

    producer = Producer({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")})
    if args.with_demo_model:
        for agent in ("A", "B"):
            table = build_table(DEMO_SESSIONS[agent], vocabulary=DEMO_VOCABULARY[agent],
                                orders=(1,) if agent == "A" else (1, 2))
            producer.produce(os.getenv("MODEL_TOPIC", "model-updates"), key=f"b3-markov-chain.{agent}",
                             value=json.dumps(model_message(agent, table)))
        producer.flush(10)
        print("Published demo models for A and B")
    if args.models_only:
        return
    sent = 0
    for agent in ("A", "B"):
        topic = f"tool-calls.{agent}"
        sessions = DEMO_SESSIONS[agent] * args.repeat + DEMO_ATTACKS[agent]
        for tools in sessions:
            events = session_events(agent, tools)
            for event in events:
                producer.produce(topic, key=event["session_id"], value=json.dumps(event))
            sent += 1
    producer.flush(10)
    print(f"Published {sent} sessions to tool-calls.A and tool-calls.B (last ones per agent are out of order)")


if __name__ == "__main__":
    main()
