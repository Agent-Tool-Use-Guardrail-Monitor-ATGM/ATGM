"""Publish the current allowed tools per agent to `toolset-config` (for local runs and demos).

    python -m allow_list.publish_toolset_config                         # both agents, full default toolsets
    python -m allow_list.publish_toolset_config --agent B --tools find_contact,tone_checker
                                                                        # revoke the rest: later calls are flagged

One message per agent, keyed by agent id: {"agent_id": "B", "allowed_tools": [...]}. The newest wins.
"""
import argparse
import json
import os
from datetime import datetime, timezone

from confluent_kafka import Producer

DEFAULT_TOOLSETS = {
    "A": ["inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns", "finalize_statistics"],
    "B": ["find_contact", "get_current_datetime", "get_free_slots", "save_draft", "tone_checker",
          "sensitive_content_scan"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish toolset-config messages")
    parser.add_argument("--agent", choices=sorted(DEFAULT_TOOLSETS), help="only this agent (default: both)")
    parser.add_argument("--tools", help="comma-separated allowed tools (needs --agent)")
    args = parser.parse_args()
    if args.tools and not args.agent:
        parser.error("--tools needs --agent")

    toolsets = {args.agent: args.tools.split(",")} if args.tools else (
        {args.agent: DEFAULT_TOOLSETS[args.agent]} if args.agent else DEFAULT_TOOLSETS)
    producer = Producer({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")})
    topic = os.getenv("TOOLSET_TOPIC", "toolset-config")
    for agent, tools in toolsets.items():
        message = {"agent_id": agent, "allowed_tools": tools, "published_at": datetime.now(timezone.utc).isoformat()}
        producer.produce(topic, key=agent.encode("utf-8"), value=json.dumps(message).encode("utf-8"))
        print(f"{topic}: agent {agent} -> {tools}")
    producer.flush()


if __name__ == "__main__":
    main()
