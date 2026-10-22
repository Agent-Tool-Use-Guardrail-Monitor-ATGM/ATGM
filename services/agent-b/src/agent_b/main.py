
from dotenv import load_dotenv

from agent_b.domain.agent import create_agent_b


def main() -> None:
    """Initialize Agent B and run a local interactive session."""
    load_dotenv()

    agent = create_agent_b()

    print("Agent B is ready. Type 'exit' to quit.")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAgent B stopped.")
            break

        if user_input.lower() in {"exit", "quit"}:
            print("Agent B stopped.")
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
            print(f"\nAgent B: {content}")
        except Exception as exc:
            print(f"Request failed: {exc}")


if __name__ == "__main__":
    main()
