"""Settings, read from environment variables (defaults in the README)."""
import os

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "allow-list-consumer")
TOPICS = os.getenv("TOPICS", "tool-calls.A,tool-calls.B").split(",")     # tool calls to check
TOOLSET_TOPIC = os.getenv("TOOLSET_TOPIC", "toolset-config")              # current allowed tools per agent
FLAGS_TOPIC = os.getenv("FLAGS_TOPIC", "flags")                           # violation.flagged events

POLICY_FILE = os.getenv("POLICY_FILE")            # optional JSON file replacing the built-in policy
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "10000"))                    # sessions kept in memory
CONFIG_BOOTSTRAP_TIMEOUT_S = float(os.getenv("CONFIG_BOOTSTRAP_TIMEOUT_S", "15"))
