"""Main entry point for running the email drafting agent."""
from __future__ import annotations

import argparse

from agent_b.domain.agent import create_agent_b
from agent_b.adapters.tool_call_logger import log_tool_trace, TOOL_LOGS_DIR

def main() -> None:
    parser = argparse.ArgumentParser(description="Email drafting assistant agent")
    parser.add_argument("--model", default="qwen3:1.7b", help="Installed Ollama model") # qwen2.5:1.5b, qwen3:1.7b
    parser.add_argument("--prompt", help="One question; otherwise interactive mode")
    args = parser.parse_args()

    print(f"Model: {args.model}")

    agent = create_agent_b(args.model)
    
    TOOL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    session_id = 0
    
    print("\nThe email drafting assistant agent has started.")

    def user_prompt(session_id: int, prompt: str) -> None:
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={"recursion_limit": 14},
            )
        except Exception as exc:
            print(f"Agent error: {type(exc).__name__}: {exc}")
            print("Check that Ollama is running and the requested model is installed.")
            return
        
        log_tool_trace(session_id, result["messages"])
        
        print(f"\nAgent's answer > {result["messages"][-1].content}")    

    if args.prompt:
        user_prompt(session_id, args.prompt)
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
                user_prompt(session_id, q)
                session_id += 1


if __name__ == "__main__":
    main()
    