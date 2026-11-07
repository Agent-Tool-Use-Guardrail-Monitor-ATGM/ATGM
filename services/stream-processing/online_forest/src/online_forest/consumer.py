
import json
import logging
import os
import signal

from confluent_kafka import Consumer, KafkaError

from online_forest.detector import OnlineForestDetector


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
KAFKA_GROUP_ID = os.getenv(
    "KAFKA_GROUP_ID",
    "online-forest-consumer",
)

TOPICS = ["tool-calls.A", "tool-calls.B"]

running = True


def stop_consumer(signum, frame):
    global running
    running = False


def main():
    global running

    signal.signal(signal.SIGINT, stop_consumer)
    signal.signal(signal.SIGTERM, stop_consumer)

    consumer = Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": KAFKA_GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })

    detectors = {
        "tool-calls.A": OnlineForestDetector(),
        "tool-calls.B": OnlineForestDetector(),
    }

    consumer.subscribe(TOPICS)

    logger.info("Online Forest consumer started")
    logger.info("Kafka broker: %s", KAFKA_BOOTSTRAP)
    logger.info("Subscribed topics: %s", TOPICS)

    try:
        while running:
            message = consumer.poll(1.0)

            if message is None:
                continue

            if message.error():
                if message.error().code() == KafkaError._PARTITION_EOF:
                    continue

                logger.error("Kafka error: %s", message.error())
                continue

            topic = message.topic()

            try:
                event = json.loads(message.value().decode("utf-8"))

                if not isinstance(event, dict):
                    raise ValueError("Kafka event must be a JSON object")

                detector = detectors[topic]
                result = detector.process(event)

                logger.info(
                    "Topic=%s partition=%s offset=%s "
                    "samples_seen=%s score=%.6f anomaly=%s",
                    topic,
                    message.partition(),
                    message.offset(),
                    result["samples_seen"],
                    result["anomaly_score"],
                    result["is_anomaly"],
                )

                consumer.commit(message=message, asynchronous=False)

            except (json.JSONDecodeError, UnicodeDecodeError,
                    KeyError, TypeError, ValueError):
                logger.exception(
                    "Invalid event in topic %s at offset %s",
                    topic,
                    message.offset(),
                )

    finally:
        consumer.close()
        logger.info("Online Forest consumer stopped")


if __name__ == "__main__":
    main()
