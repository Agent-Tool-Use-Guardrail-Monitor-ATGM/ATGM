"""Entry point of the DSPOT service: python -m dspot.main

Configuration (environment variables, defaults in brackets):
    KAFKA_BOOTSTRAP [localhost:29092]   DSPOT_GROUP_ID [dspot]
    DSPOT_Q [0.001]  DSPOT_LEVEL [0.98]  DSPOT_DEPTH [20]  DSPOT_WARMUP [3000]
    SCORES_TOPIC [scores]  LABELS_TOPIC [labels]  ALARM_TOPICS [alerts,review-queue]

State lives in memory: after a restart every stream warms up again.
"""
from __future__ import annotations

import logging
import os

from dspot.domain.monitor import AlarmMonitor
from dspot.service import DSPOTService


def main() -> None:
    from dspot.adapters.kafka import KafkaSink, KafkaSource   # needs the "kafka" extra

    env = os.environ.get
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    bootstrap = env("KAFKA_BOOTSTRAP", "localhost:29092")
    monitor = AlarmMonitor(q=float(env("DSPOT_Q", "0.001")), level=float(env("DSPOT_LEVEL", "0.98")),
                           depth=int(env("DSPOT_DEPTH", "20")), warmup=int(env("DSPOT_WARMUP", "3000")))
    sink = KafkaSink(bootstrap)
    service = DSPOTService(monitor, sink, tuple(env("ALARM_TOPICS", "alerts,review-queue").split(",")))
    source = KafkaSource(bootstrap, env("DSPOT_GROUP_ID", "dspot"),
                         [env("SCORES_TOPIC", "scores"), env("LABELS_TOPIC", "labels")])
    logging.getLogger("dspot").info("DSPOT service started (q=%g, warm-up %d scores per stream)",
                                    monitor.q, monitor.warmup)
    try:
        for msg in source.messages():
            service.handle(msg)
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        sink.flush()


if __name__ == "__main__":
    main()
