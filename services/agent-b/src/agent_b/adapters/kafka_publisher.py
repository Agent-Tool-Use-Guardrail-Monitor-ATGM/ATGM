import os, json
from confluent_kafka import Producer
from langchain_core.messages import AIMessage, ToolMessage

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "10.0.0.1:9092")
print("Kafka broker:", BOOTSTRAP)

producer = Producer({"bootstrap.servers": BOOTSTRAP})

TOPIC_NAME = "tool-calls.B"

def send_tool_calls_to_kafka(session_id: int, messages: list):
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                call = {
                    "type": "call",
                    "name": call['name'],
                    "args": json.dumps(call['args']),
                }
                producer.produce(TOPIC_NAME, key=session_id, value=json.dumps(call))
                
        if isinstance(message, ToolMessage):
            result = {
                "type": "result",
                "content": message.content,
            }
            producer.produce(TOPIC_NAME, key=session_id, value=json.dumps(result))    
    
    producer.flush()   # wait until Kafka has received everything
