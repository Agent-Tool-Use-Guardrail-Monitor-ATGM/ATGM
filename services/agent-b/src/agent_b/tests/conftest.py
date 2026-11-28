"""Shared test setup: the tools use an in-memory store instead of agent_b_db, so no database is needed."""
import pytest

from agent_b.adapters.fake_data import CONTACTS
from agent_b.domain import drafting_tools


class MemoryStore:
    """Same data as agent_b_db, kept in memory."""

    def __init__(self):
        self.contacts = dict(CONTACTS)
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
def memory_store(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(drafting_tools, "STORE", store)
    return store