
import json
import logging
import os
import signal

from confluent_kafka import Consumer, KafkaError, Producer

from online_forest.detector import OnlineForestDetector
from online_forest.events import agent_id, is_tool_call, scored_event


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "online-forest-consumer")
TOPICS = os.getenv("TOPICS", "tool-calls.A,tool-calls.B").split(",")
SCORES_TOPIC = os.getenv("SCORES_TOPIC", "scores")

running = True


def stop_consumer(signum, frame):
    global running
    running = False


def main():
    signal.signal(signal.SIGINT, stop_consumer)
    signal.signal(signal.SIGTERM, stop_consumer)

    consumer = Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": KAFKA_GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})

    detectors: dict[str, OnlineForestDetector] = {}   # one per agent, created on first event

    consumer.subscribe(TOPICS)
    logger.info("Online Forest consumer started: %s -> %s", TOPICS, SCORES_TOPIC)

    try:
        while running:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                if message.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Kafka error: %s", message.error())
                continue

            topic = message.topic()
            try:
                event = json.loads(message.value().decode("utf-8"))
                if not isinstance(event, dict):
                    raise ValueError("Kafka event must be a JSON object")

                if is_tool_call(event):
                    agent = agent_id(event, topic)
                    detector = detectors.setdefault(agent, OnlineForestDetector())
                    result = detector.process(event)

                    out = scored_event(event, agent, result["anomaly_score"])
                    producer.produce(SCORES_TOPIC, key=agent, value=json.dumps(out))
                    producer.poll(0)

                    logger.debug("agent=%s samples=%s score=%.6f",
                                 agent, result["samples_seen"], result["anomaly_score"])

            except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
                logger.exception("Invalid event in topic %s at offset %s", topic, message.offset())

            consumer.commit(message=message, asynchronous=False)

    finally:
        consumer.close()
        producer.flush(10)
        logger.info("Online Forest consumer stopped")


if __name__ == "__main__":
    main()