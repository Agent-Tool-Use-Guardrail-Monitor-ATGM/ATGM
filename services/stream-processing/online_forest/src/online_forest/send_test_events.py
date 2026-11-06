
import json
from confluent_kafka import Producer

producer = Producer({
    "bootstrap.servers": "localhost:29092"
})

topic = "tool-calls.A"

for i in range(1, 201):
    event = {
        "duration_ms": 120,
        "arguments": {"query": "test"},
        "session_call_index": i,
        "time_since_previous_call_ms": 1000,
        "success": True,
    }

    producer.produce(
        topic,
        key=f"test-session-{i}".encode("utf-8"),
        value=json.dumps(event).encode("utf-8"),
    )

producer.flush()

print("Successfully sent 200 normal events.")
