from langchain.agents import create_agent
from agent_b.adapters.llm_client import create_llm
from agent_b.domain.tools import *

SYSTEM_PROMPT = """You are an email-drafting assistant. Use your tools; never guess.
Workflow:
1. Look up the recipient with find_contact and follow their preferred tone.
2. If the email mentions dates or scheduling, call get_current_datetime, then get_free_slots.
3. Write the email, then call save_draft exactly once.
4. Reply with a short summary of what you drafted.
You cannot send emails, only save drafts."""

TOOLS = [find_contact, find_contact, get_free_slots, save_draft]

def create_agent_b():
    """Create email-drafting agent"""    
    llm = create_llm()

    return create_agent(
      model=llm,
      tools=TOOLS,
      system_prompt=SYSTEM_PROMPT
    )
