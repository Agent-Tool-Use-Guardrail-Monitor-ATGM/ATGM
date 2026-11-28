import re
from datetime import datetime

import pytest

from agent_b.domain import drafting_tools
from agent_b.domain.drafting_tools import (
    find_contact,
    get_current_datetime,
    get_free_slots,
    save_draft,
)


class FakeStore:
    """In-memory stand-in for agent_b_db, so the tests need no database."""

    def __init__(self):
        self.contacts = {"alice": {"name": "Alice", "email": "alice@example.com",
                                   "role": "CTO", "tone": "formal"}}
        self.drafts = []

    def contact(self, key):
        return self.contacts.get(key)

    def contact_keys(self):
        return sorted(self.contacts)

    def slots(self, weekday):
        return ["09:30-10:30", "14:00-15:00"] if weekday % 2 == 0 else ["11:00-12:00", "16:00-17:00"]

    def save_draft(self, to, subject, body):
        self.drafts.append((to, subject, body))
        return len(self.drafts)


@pytest.fixture(autouse=True)
def fake_store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(drafting_tools, "STORE", fake)
    return fake


# ---------- find_contact ----------
def test_find_contact():
    # Found (case and whitespace insensitive)
    result = find_contact.invoke({"name": "  ALICE "})
    assert result == "Alice <alice@example.com>, role: CTO, preferred tone: formal"

    # Not found
    result = find_contact.invoke({"name": "bob"})
    assert "No contact found for 'bob'" in result
    assert "alice" in result  # known contacts are listed


# ---------- get_current_datetime ----------
def test_get_current_datetime():
    result = get_current_datetime.invoke({})

    # e.g. "Monday, 2026-11-09 14:30"
    assert re.fullmatch(r"[A-Z][a-z]+, \d{4}-\d{2}-\d{2} \d{2}:\d{2}", result)
    parsed = datetime.strptime(result, "%A, %Y-%m-%d %H:%M")
    assert abs((datetime.now() - parsed).total_seconds()) < 120


# ---------- get_free_slots ----------
def test_get_free_slots():
    # Monday (even weekday)
    assert get_free_slots.invoke({"date": "2026-11-09"}) == (
        "Free on 2026-11-09: 09:30-10:30, 14:00-15:00"
    )
    # Tuesday (odd weekday)
    assert get_free_slots.invoke({"date": "2026-11-10"}) == (
        "Free on 2026-11-10: 11:00-12:00, 16:00-17:00"
    )
    # Saturday
    assert get_free_slots.invoke({"date": "2026-11-14"}) == "No free slots: weekend."
    # Bad format
    assert get_free_slots.invoke({"date": "09/11/2026"}) == "Invalid date. Use YYYY-MM-DD."


# ---------- save_draft ----------
def test_save_draft(fake_store):
    result = save_draft.invoke(
        {"to": "alice@example.com", "subject": "Hello", "body": "Hi Alice,\nSee you soon."}
    )
    assert result == "Draft saved with id 1"
    assert fake_store.drafts == [("alice@example.com", "Hello", "Hi Alice,\nSee you soon.")]