"""Tool call logger."""

import json

from langchain_core.messages import AIMessage, ToolMessage

def show_tool_trace(messages: list) -> int:
    """Print observable tool requests and tool results, NOT private model reasoning."""
    count = 0
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                count += 1
                print(f"\n[TOOL CALL] {call['name']}({json.dumps(call['args'])})")
        if isinstance(message, ToolMessage):
            print(f"[TOOL RESULT] {message.content}")
    return count