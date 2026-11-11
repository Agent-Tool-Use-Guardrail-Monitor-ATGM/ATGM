import os, json, time, random, uuid
from datetime import datetime
from confluent_kafka import Producer, Consumer
from confluent_kafka.admin import AdminClient, NewTopic

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
print("Kafka broker:", BOOTSTRAP)

producer = Producer({"bootstrap.servers": BOOTSTRAP})

admin = AdminClient({"bootstrap.servers": BOOTSTRAP})

def create_topic(name, partitions=3):
    if name in admin.list_topics(timeout=10).topics:
        print(f"Topic '{name}' already exists")
        return
    admin.create_topics([NewTopic(name, num_partitions=partitions, replication_factor=1)])[name].result()
    print(f"Topic '{name}' created with {partitions} partitions")


def read_topic(topic, group=None, wait_seconds=5, show=True):
    """Read all messages of a topic. Returns them as a list of (key, value) strings."""
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": group or f"reader-{uuid.uuid4().hex[:6]}",  # no group given -> new group -> read everything
        "auto.offset.reset": "earliest",                       
    })
    consumer.subscribe([topic])
    messages, started, last_message_time = [], time.time(), None
    while True:
        msg = consumer.poll(1.0)                                # wait up to 1 second for a message
        now = time.time()
        if msg is None or msg.error():
            if last_message_time is None and now - started > 10:            # nothing at all after 10 s
                break
            if last_message_time is not None and now - last_message_time > wait_seconds:
                break                                                       # no new message for 5 s
            continue
        last_message_time = now
        key = msg.key().decode() if msg.key() else None
        value = msg.value().decode()
        messages.append((key, value))
        if show:
            print(f"partition={msg.partition()} offset={msg.offset():<3} key={key}  value={value}")
    consumer.close()
    print(f"--> {len(messages)} messages read from '{topic}'")
    return messages

TOPIC_NAME = "tool-calls.B"

create_topic("text-messages")

for i in range(10):
    producer.produce("text-messages", value=f"SM {i}")

producer.flush()   # wait until Kafka has received everything
print("10 text messages sent")

messages = read_topic("text-messages")