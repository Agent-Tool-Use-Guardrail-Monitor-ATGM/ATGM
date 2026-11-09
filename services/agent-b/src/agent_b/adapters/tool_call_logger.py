"""Tool call logger."""

import json
from datetime import datetime
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

TOOL_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs" / "tool_calls"

def log_tool_trace(session_id: int, messages: list) -> int:
    """Print observable tool requests and tool results, NOT private model reasoning."""
    count = 0
    path = TOOL_LOGS_DIR / f"logs_{datetime.now():%Y%m%d_%H%M%S}_session_{session_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for message in messages:
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    count += 1
                    line = f"[TOOL CALL] {call['name']}({json.dumps(call['args'])})"
                    print(f"\n{line}")                
                    f.write(line + "\n")
            if isinstance(message, ToolMessage):
                line = f"[TOOL RESULT] {message.content}"
                print(line)
                f.write(line + "\n")
    return count
