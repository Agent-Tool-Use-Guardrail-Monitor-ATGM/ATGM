from agent_b.domain.drafting_tools import *

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

@pytest.fixture
def fake_contacts(monkeypatch):
    fake = {
        "alice": {
            "name": "Alice",
            "email": "alice@example.com",
            "role": "CTO",
            "tone": "formal",
        }
    }
    monkeypatch.setattr(drafting_tools, "CONTACTS", fake)
    return fake


@pytest.fixture
def drafts_dir(monkeypatch, tmp_path):
    path = tmp_path / "email_drafts"
    monkeypatch.setattr(drafting_tools, "DRAFTS_DIR", path)
    return path

# ---------- find_contact ----------
def test_find_contact(monkeypatch):
    fake = {
        "alice": {
            "name": "Alice",
            "email": "alice@example.com",
            "role": "CTO",
            "tone": "formal",
        }
    }
    monkeypatch.setattr(drafting_tools, "CONTACTS", fake)

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
def test_save_draft(monkeypatch, tmp_path):
    drafts_dir = tmp_path / "email_drafts"
    monkeypatch.setattr(drafting_tools, "DRAFTS_DIR", drafts_dir)

    result = save_draft.invoke(
        {"to": "alice@example.com", "subject": "Hello", "body": "Hi Alice,\nSee you soon."}
    )

    files = list(drafts_dir.glob("draft_*.txt"))
    assert len(files) == 1
    assert result == f"Draft saved to {files[0]}"
    assert files[0].read_text(encoding="utf-8") == (
        "To: alice@example.com\nSubject: Hello\n\nHi Alice,\nSee you soon.\n"
    )