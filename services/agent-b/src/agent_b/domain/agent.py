"""Local, tool-using LLM agent for drafting emails."""

from datetime import date

from langchain.agents import create_agent
from langchain_ollama import ChatOllama

from agent_b.domain.drafting_tools import DRAFTING_TOOLS, set_today
from agent_b.domain.verification_tools import VERIFICATION_TOOLS

SYSTEM_PROMPT = """You are an email-drafting assistant.
Use the provided tools for composing emails. 
If a request cannot be answered with the available tools, explain the limitation.
You are only composing email drafts, never send any email.
Make sure the content of the email matches the user input and you use an appropriate tone.
Always use tools for lookup contacts, scan draft for sensitive content, check for appropriate tone and finally save a draft. 
Follow these steps in this order:
1. If the task gives an email address, use it and do not call find_contact. Otherwise call find_contact once with the person's name and use exactly the email it returns.
2. Only if you need meeting times: call get_current_datetime once, then get_free_slots.
3. Write the draft and call tone_checker on it. Fix the draft if needed.
4. Call sensitive_content_scan on the final text, including the subject line.
5. Call save_draft once, with exactly the subject and body you scanned.
"""

TOOLS = DRAFTING_TOOLS + VERIFICATION_TOOLS

def system_prompt(day: date) -> str:
    return SYSTEM_PROMPT + (
        f"Today is {day:%A, %Y-%m-%d}. Work out dates like 'this coming Friday' from today.\n"
        "Call get_current_datetime (it takes no arguments) before get_free_slots.\n"
    )


def create_agent_b(model: str, today: date | None = None):
    """`today` fixes the agent's date (for scenarios); None uses the real date."""
    set_today(today)
    return create_agent(
        model=ChatOllama(model=model, temperature=0, num_predict=2048, num_ctx=8192,
                         client_kwargs={"timeout": 300}),
        tools=TOOLS,
        system_prompt=system_prompt(today or date.today()),
    )