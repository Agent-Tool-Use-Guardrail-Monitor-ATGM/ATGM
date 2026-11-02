"""Deterministic email drafting tools"""

import time
from datetime import datetime, timedelta
from pathlib import Path

from langchain.tools import tool

from fake_data import CONTACTS
DRAFTS_DIR = Path("drafts")

@tool
def find_contact(name: str) -> str:
    """Look up a contact by name. Returns their email, role and preferred tone."""
    c = CONTACTS.get(name.strip().lower())
    if not c:
        return f"No contact found for '{name}'. Known: {', '.join(CONTACTS)}"
    return f"{c['name']} <{c['email']}>, role: {c['role']}, preferred tone: {c['tone']}"
 
 
@tool
def get_current_datetime() -> str:
    """Get the current date, time and weekday. Use before mentioning any dates."""
    return datetime.now().strftime("%A, %Y-%m-%d %H:%M")
 
 
@tool
def get_free_slots(date: str) -> str:
    """Get the user's free meeting slots for a date given as YYYY-MM-DD."""
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return "Invalid date. Use YYYY-MM-DD."
    if d.weekday() >= 5:
        return "No free slots: weekend."
    # Fake calendar: slots vary by weekday so results look real
    slots = ["09:30-10:30", "14:00-15:00"] if d.weekday() % 2 == 0 else ["11:00-12:00", "16:00-17:00"]
    return f"Free on {date}: " + ", ".join(slots)
 
 
@tool
def save_draft(to: str, subject: str, body: str) -> str:
    """Save the finished email as a draft file. Call this once, when the email is final."""
    DRAFTS_DIR.mkdir(exist_ok=True)
    path = DRAFTS_DIR / f"draft_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    return f"Draft saved to {path}"