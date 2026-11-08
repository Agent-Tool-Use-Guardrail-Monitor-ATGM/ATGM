from agent_b.domain.tools import sensitive_content_scan, tone_checker


def test_scan_blocks_password_and_masks_it():
    result = sensitive_content_scan.invoke(
        {"text": "Subject: Login\n\nMy password: Hunter2024! for the portal."}
    )
    assert result["status"] == "blocked"
    assert "Hunter2024!" not in str(result["findings"])


def test_scan_blocks_card_number():
    result = sensitive_content_scan.invoke(
        {"text": "Subject: Payment\n\nCard 4111 1111 1111 1111 please."}
    )
    assert result["status"] == "blocked"


def test_scan_clear_for_plain_email():
    result = sensitive_content_scan.invoke(
        {"text": "Subject: Schedule\n\nHello, could we move the meeting to Friday?\nBest regards,\nSam"}
    )
    assert result["status"] == "clear"


def test_tone_checker_flags_slang_in_formal_email():
    result = tone_checker.invoke(
        {"draft": "Subject: Hey\n\nyo gonna be late lol", "requested_tone": "formal"}
    )
    assert result["matches_tone"] is False