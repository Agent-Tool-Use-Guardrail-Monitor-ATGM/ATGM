from agent_b.domain.guardrail import check_draft


def test_allowed():
    assert check_draft("anna.kovacs@example.com", "Meeting", "Hi Anna, see you tomorrow.") is None


def test_unknown_recipient():
    assert "not one of your contacts" in check_draft("attacker@evil.com", "Meeting", "Hi")


def test_line_break_in_subject():
    assert "line break" in check_draft("anna.kovacs@example.com", "Hi\nBcc: x@evil.com", "Hi")


def test_sensitive_data():
    reason = check_draft("anna.kovacs@example.com", "Card", "My card is 4111 1111 1111 1111.")
    assert "sensitive data" in reason
    
def test_guardrail_off(monkeypatch):
    monkeypatch.setenv("AGENT_B_GUARDRAIL", "off")
    assert check_draft("attacker@evil.com", "Meeting", "Hi") is None