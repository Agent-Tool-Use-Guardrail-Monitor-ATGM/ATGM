
from dotenv import load_dotenv

from agent_b.domain.agent import create_agent_b

import time
from pathlib import Path

LOG_FILE = Path("tool_calls.log")

def log(kind: str, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {kind:<7} {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def main() -> None:
    """Initialize Email Emilio and run a local interactive session."""
    load_dotenv()

    agent = create_agent_b()

    print("Email Emilio is ready. Type 'exit' to quit.")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEmail Emilio stopped.")
            break

        if user_input.lower() in {"exit", "quit"}:
            print("Email Emilio stopped.")
            break

        if not user_input:
            continue

        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": user_input}]}
            )
            last_message = result["messages"][-1]
            content = last_message.content
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            print(f"\nEmail Emilio: {content}")
        except Exception as exc:
            print(f"Request failed: {exc}")


if __name__ == "__main__":
    main()
