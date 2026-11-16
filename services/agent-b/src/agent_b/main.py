"""Main entry point for running the email drafting agent."""
from __future__ import annotations

import argparse
import os
import uuid
import json
from pathlib import Path

from confluent_kafka import Producer

from agent_b.adapters.session_event_processor import SessionEventPublisher, KafkaSink, JsonlSink
from agent_b.domain.agent import create_agent_b

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    parser = argparse.ArgumentParser(description="Email drafting assistant agent")
    parser.add_argument("--model", default="qwen3:1.7b", help="Installed Ollama model") # qwen2.5:1.5b, qwen3:1.7b
    parser.add_argument("--prompt", default="interactive", help="'interactive' or name of a scenario file, e.g. 'scenario_01.jsonl'")
    args = parser.parse_args()

    print(f"Model: {args.model}")

    agent = create_agent_b(args.model)

    print("\nThe email drafting assistant agent has started.")

    env = os.environ.get
    producer = Producer({"bootstrap.servers": env("KAFKA_BOOTSTRAP", "localhost:29092")})
    topic = env("TOPIC_B", "tool-calls.B")
    run_id = str(uuid.uuid4())

    def user_prompt(prompt: str) -> None:
        kafka_sink = KafkaSink(producer, topic)
        
        publisher = SessionEventPublisher(
            kafka_sink, run_id=run_id, session_id=str(uuid.uuid4()), agent_id="B"
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
        
    def scenario_prompt(prompt: str, sink: JsonlSink) -> None:
        publisher = SessionEventPublisher(
            sink, run_id=run_id, session_id=str(uuid.uuid4()), agent_id="B"
        )
        publisher.start()
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={"recursion_limit": 14, "callbacks": [publisher]},
            )
            print(f"Agent's answer > {result['messages'][-1].content}")
        except Exception as exc:
            print(f"Agent error: {type(exc).__name__}: {exc}")
            print("Check that Ollama is running and the requested model is installed.")
        finally:
            publisher.end()

    try:
        if args.prompt == 'interactive':
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
        
        else:
            scenario_path = Path(PROJECT_ROOT / "dataset" / "agent_b" / "scenarios") / args.prompt
            if not scenario_path.is_file():
                print(f"Scenario file not found: {scenario_path}")
                return

            prompts = []
            with open(scenario_path, encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        prompts.append(json.loads(line)["prompt"])
                    except (json.JSONDecodeError, KeyError) as exc:
                        print(f"Skipping line {line_no}: {type(exc).__name__}: {exc}")

            event_file_name = "events_for_" + args.prompt
            events_path = Path(PROJECT_ROOT / "dataset" / "agent_b" / "events") / event_file_name
            sink = JsonlSink(events_path)
            try:
                for i, prompt in enumerate(prompts, 1):                    
                    scenario_prompt(prompt, sink)
                    print(f"\nProcessed [{i}/{len(prompts)}] prompts")
            finally:
                sink.close()
            print(f"\nEvents saved to {events_path}")
    
    finally:
        producer.flush(10)


if __name__ == "__main__":
    main()