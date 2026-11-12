"""Main entry point for running the email drafting agent."""
from __future__ import annotations

import argparse
import os
import uuid

from confluent_kafka import Producer

from agent_b.adapters.kafka_publisher import SessionEventPublisher
from agent_b.domain.agent import create_agent_b


def main() -> None:
    parser = argparse.ArgumentParser(description="Email drafting assistant agent")
    parser.add_argument("--model", default="qwen3:1.7b", help="Installed Ollama model") # qwen2.5:1.5b, qwen3:1.7b
    parser.add_argument("--prompt", help="One question; otherwise interactive mode")
    args = parser.parse_args()

    print(f"Model: {args.model}")

    agent = create_agent_b(args.model)

    print("\nThe email drafting assistant agent has started.")

    env = os.environ.get
    producer = Producer({"bootstrap.servers": env("KAFKA_BOOTSTRAP", "localhost:29092")})
    topic = env("TOPIC_B", "tool-calls.B")
    run_id = str(uuid.uuid4())

    def user_prompt(prompt: str) -> None:
        publisher = SessionEventPublisher(
            producer, topic, run_id=run_id, session_id=str(uuid.uuid4()), agent_id="B"
        )
        publisher.start()
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={"recursion_limit": 14, "callbacks": [publisher]},
            )
        except Exception as exc:
            print(f"Agent error: {type(exc).__name__}: {exc}")
            print("Check that Ollama is running and the requested model is installed.")
            return
        finally:
            publisher.end()

        print(f"\nAgent's answer > {result['messages'][-1].content}")

    try:
        if args.prompt:
            user_prompt(args.prompt)
        else:
            print("\nDescribe what email you'd like the agent to draft, or 'quit' to exit.")
            while True:
                try:
                    q = input("\nUser prompt > ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nThe email drafting assistant agent has stopped.")
                    break
                if q.lower() in {"quit", "exit", "q"}:
                    print("\nThe email drafting assistant agent has stopped.")
                    break
                if q:
                    user_prompt(q)
    finally:
        producer.flush(10)


if __name__ == "__main__":
    main()