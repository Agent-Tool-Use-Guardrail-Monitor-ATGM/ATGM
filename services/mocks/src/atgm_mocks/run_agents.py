"""Mock agents service: python -m atgm_mocks.run_agents

Publishes tool-call sessions of Agent A and Agent B to Kafka and stores the ground truth.
The first WARMUP_SESSIONS sessions per agent are normal only (detectors calibrate on them),
then a fraction ATTACK_RATE of the sessions are attacks.

Environment (defaults in brackets):
    KAFKA_BOOTSTRAP [localhost:29092]   TOPIC_A [tool-calls.A]   TOPIC_B [tool-calls.B]
    SESSIONS_PER_SECOND [5]   WARMUP_SESSIONS [1000]   ATTACK_RATE [0.05]   MAX_SESSIONS [0 = forever]
    MOCK_AGENTS [A,B] (use B when the real Agent A publishes)   SEED [random]   GROUND_TRUTH [on]   DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD (scenario_db)
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid

from atgm_mocks.domain.sessions import SessionGenerator
from atgm_mocks.envelope import session_events

log = logging.getLogger("mock-agents")


def main() -> None:
    from confluent_kafka import Producer

    env = os.environ.get
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    seed = env("SEED")
    rng = random.Random(int(seed) if seed else None)
    generator = SessionGenerator(rng, attack_rate=float(env("ATTACK_RATE", "0.05")))
    topics = {"A": env("TOPIC_A", "tool-calls.A"), "B": env("TOPIC_B", "tool-calls.B")}
    agents = [a.strip() for a in env("MOCK_AGENTS", "A,B").split(",") if a.strip() in topics]
    if not agents:
        raise SystemExit("MOCK_AGENTS must name A and/or B")
    rate = float(env("SESSIONS_PER_SECOND", "5"))
    warmup = int(env("WARMUP_SESSIONS", "1000"))
    limit = int(env("MAX_SESSIONS", "0"))
    store = None
    if env("GROUND_TRUTH", "on") == "on":
        from atgm_mocks.adapters.ground_truth import GroundTruthStore
        store = GroundTruthStore()

    producer = Producer({"bootstrap.servers": env("KAFKA_BOOTSTRAP", "localhost:29092")})
    run_id = str(uuid.uuid4())
    counts = {"A": 0, "B": 0}
    attacks = 0
    log.info("mock agents %s started: run %s, %s sessions/s, warm-up %d sessions per agent",
             ",".join(agents), run_id, rate, warmup)
    try:
        while not limit or sum(counts.values()) < limit:
            agent = min(agents, key=counts.get)                 # alternate between the simulated agents
            session = generator.next(agent, allow_attacks=counts[agent] >= warmup)
            if store is not None:
                store.save(session)
            for event in session_events(session, run_id, rng=rng):
                producer.produce(topics[agent], key=session.session_id, value=json.dumps(event))
            producer.poll(0)
            counts[agent] += 1
            if session.attack_type:
                attacks += 1
                log.info("attack session %s: agent %s, %s", session.session_id, agent, session.attack_type)
            if sum(counts.values()) % 500 == 0:
                log.info("sessions sent: A=%d B=%d (attacks: %d)", counts["A"], counts["B"], attacks)
            if counts[agent] == warmup:
                log.info("agent %s: warm-up done, attacks start now", agent)
            time.sleep(1.0 / rate)
    except KeyboardInterrupt:
        pass
    finally:
        producer.flush(10)


if __name__ == "__main__":
    main()
