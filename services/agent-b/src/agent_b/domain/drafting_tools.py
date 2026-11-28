"""Four simple email drafting tools exposed to the LLM.

The model selects the tools for each task. Contacts, free slots and drafts
are stored in agent_b_db.
"""

from datetime import date, datetime

from langchain.tools import tool

from agent_b.adapters.agent_b_db import AgentBStore

STORE = None


def store():
    global STORE
    if STORE is None:
        STORE = AgentBStore()
    return STORE


@tool
def find_contact(name: str) -> str:
    """Look up a contact by name. Returns their email, role and preferred tone.

    Args:
        name: name of a contact.
    """
    c = store().contact(name.strip().lower())
    if not c:
        return f"No contact found for '{name}'. Known: {', '.join(store().contact_keys())}"
    return f"{c['name']} <{c['email']}>, role: {c['role']}, preferred tone: {c['tone']}"


# The scenario runner sets the date the scenario was written for
# None means the real date
_today: date | None = None


def set_today(day: date | None) -> None:
    global _today
    _today = day


def today() -> date:
    return _today or date.today()


@tool
def get_current_datetime() -> str:
    """Get today's date, weekday and time. Takes no arguments. Call it before get_free_slots."""
    return f"{today():%A, %Y-%m-%d} {datetime.now():%H:%M}"


@tool
def get_free_slots(date: str) -> str:
    """Get the user's free meeting slots for a date given as YYYY-MM-DD.

    Args:
        date: a date given as YYYY-MM-DD.
    """
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return "Invalid date. Use YYYY-MM-DD."
    if d.weekday() >= 5:
        return "No free slots: weekend."
    slots = store().slots(d.weekday())
    return f"Free on {date}: " + ", ".join(slots)


@tool
def save_draft(to: str, subject: str, body: str) -> str:
    """Save the finished email as a draft. Call this once, when the email is final.

    Args:
        to: the email address of the recipient.
        subject: the subject of the email.
        body: the content of the email.
    """
    draft_id = store().save_draft(to, subject, body)
    return f"Draft saved with id {draft_id}"


DRAFTING_TOOLS = [find_contact, get_current_datetime, get_free_slots, save_draft]