"""Local, tool-using LLM agent for drafting emails."""

from langchain.agents import create_agent
from langchain_ollama import ChatOllama

from agent_b.domain.drafting_tools import DRAFTING_TOOLS
from agent_b.domain.verification_tools import VERIFICATION_TOOLS

SYSTEM_PROMPT = """You are an email-drafting assistant.
Use the provided tools for composing emails. 
If a request cannot be answered with the available tools, explain the limitation.
You are only composing email drafts, never send any email.
Make sure the content of the email matches the user input and you use an appropriate tone.
Always use tools for lookup contacts, scan draft for sensitive content, check for appropriate tone and finally save a draft. 
"""

TOOLS = DRAFTING_TOOLS + VERIFICATION_TOOLS

def create_agent_b(model: str):
    return create_agent(
        model=ChatOllama(model=model, temperature=0),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )
    