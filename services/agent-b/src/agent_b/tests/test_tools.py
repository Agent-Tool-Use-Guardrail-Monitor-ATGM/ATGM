"""Unit / functional tests for Agent B's tools.

These tests are deterministic: they need neither Ollama nor network access.
Tools are called through ``.invoke({...})``, exactly as the agent runtime does,
so argument validation and the @tool wrapper are exercised too.

Run with:
    PYTHONPATH=src uv run pytest tests/test_tools.py -v
"""

import json

import pytest

from agent_b.domain.tools import sensitive_content_scan, tone_checker


# ---------------------------------------------------------------------------
# Helpers and sample drafts
# ---------------------------------------------------------------------------

def tone(draft, requested_tone="professional", profile=None):
    args = {"draft": draft, "requested_tone": requested_tone}
    if profile is not None:
        args["style_profile"] = profile
    return tone_checker.invoke(args)


def codes(result):
    return {issue["code"] for issue in result["issues"]}


def scan(text, extra=None):
    args = {"text": text}
    if extra is not None:
        args["extra_confidential_terms"] = extra
    return sensitive_content_scan.invoke(args)


def types(result):
    return [f["type"] for f in result["findings"]]


PROFESSIONAL = (
    "Subject: Project update\n\n"
    "Hello [Recipient],\n\n"
    "The report is ready for your review. Please let me know if you have questions.\n\n"
    "Best regards,\n[Sender]"
)
FORMAL = (
    "Dear [Recipient],\n\n"
    "I am writing to inform you that I am unwell and will not attend class today. "
    "I apologise for the inconvenience.\n\n"
    "Sincerely,\n[Sender]"
)
WARM = (
    "Hi [Recipient],\n\n"
    "Thank you so much for your help last week. I really appreciate it and "
    "hope we can catch up soon.\n\n"
    "Warm regards,\n[Sender]"
)
FIRM = (
    "Dear [Recipient],\n\n"
    "Please submit the signed contract by Friday. We need it to proceed with the audit.\n\n"
    "Sincerely,\n[Sender]"
)
CASUAL = "Hey [Recipient],\n\nCan't make lunch today, let's reschedule?\n\nCheers,\n[Sender]"


# ===========================================================================
# Tool registration / metadata
# ===========================================================================

def test_tool_names():
    assert tone_checker.name == "tone_checker"
    assert sensitive_content_scan.name == "sensitive_content_scan"


def test_tools_have_descriptions_for_the_llm():
    assert "tone" in tone_checker.description.lower()
    assert "sensitive" in sensitive_content_scan.description.lower() or \
        "credentials" in sensitive_content_scan.description.lower()


def test_tool_argument_schemas():
    assert set(tone_checker.args) == {"draft", "requested_tone", "style_profile"}
    assert set(sensitive_content_scan.args) == {"text", "extra_confidential_terms"}


def test_missing_required_argument_is_rejected():
    with pytest.raises(Exception):
        tone_checker.invoke({"requested_tone": "formal"})
    with pytest.raises(Exception):
        sensitive_content_scan.invoke({})


# ===========================================================================
# tone_checker: structure and basic behaviour
# ===========================================================================

def test_tone_result_structure():
    result = tone(PROFESSIONAL)

    assert set(result) >= {
        "requested_tone", "matches_tone", "score", "issues", "notes",
        "style_profile_checked", "metrics",
    }
    assert set(result["metrics"]) >= {
        "word_count", "sentence_count", "avg_words_per_sentence",
        "exclamation_marks", "contractions", "greeting", "sign_off", "subject_present",
    }
    assert 0 <= result["score"] <= 100


def test_clean_professional_draft_passes():
    result = tone(PROFESSIONAL)

    assert result["matches_tone"] is True
    assert result["score"] == 100
    assert result["issues"] == []


def test_every_issue_has_severity_code_message_and_suggestion():
    result = tone("Hey,\n\nPay NOW!!! As I said, obviously your fault.")

    assert result["issues"]
    for issue in result["issues"]:
        assert issue["severity"] in {"major", "minor"}
        assert issue["code"]
        assert issue["message"]
        assert issue["suggestion"]


@pytest.mark.parametrize("draft", ["", "   ", "\n\n"])
def test_empty_draft_fails(draft):
    result = tone(draft)

    assert result["matches_tone"] is False
    assert result["score"] == 0
    assert "empty_draft" in codes(result)


def test_subject_line_is_parsed_and_not_counted_as_body():
    draft = "Subject: One two three four five\n\nHello X,\n\nOk.\n\nBest"
    result = tone(draft)

    assert result["metrics"]["subject_present"] is True
    assert result["metrics"]["word_count"] == 4  # Hello, X, Ok, Best


def test_draft_without_subject():
    assert tone(FORMAL, "formal")["metrics"]["subject_present"] is False


def test_greeting_and_sign_off_are_detected():
    metrics = tone(PROFESSIONAL)["metrics"]

    assert metrics["greeting"] == "hello"
    assert metrics["sign_off"] == "best regards"


# ===========================================================================
# tone_checker: tone names
# ===========================================================================

@pytest.mark.parametrize(
    "given, expected",
    [
        ("formal", "formal"),
        ("FORMAL", "formal"),
        ("  Professional ", "professional"),
        ("friendly", "warm"),
        ("polite", "warm"),
        ("assertive", "firm"),
        ("direct", "firm"),
        ("business", "professional"),
        ("informal", "casual"),
    ],
)
def test_tone_aliases(given, expected):
    assert tone(PROFESSIONAL, given)["requested_tone"] == expected


def test_unknown_tone_falls_back_to_professional_with_a_note():
    result = tone(PROFESSIONAL, "sarcastic")

    assert result["requested_tone"] == "professional"
    assert any("sarcastic" in note for note in result["notes"])


def test_default_tone_is_professional():
    result = tone_checker.invoke({"draft": PROFESSIONAL})

    assert result["requested_tone"] == "professional"


# ===========================================================================
# tone_checker: checks that apply to every tone
# ===========================================================================

def test_hostile_language_is_a_major_issue():
    result = tone("Hello,\n\nAs I said, this is obviously your fault.\n\nRegards")

    assert "hostile_language" in codes(result)
    assert result["matches_tone"] is False


def test_all_caps_words_are_flagged_but_common_acronyms_are_not():
    assert "all_caps" in codes(tone("Hello,\n\nThis is URGENT.\n\nBest"))
    assert "all_caps" not in codes(tone("Hello,\n\nPlease reply ASAP, FYI only.\n\nBest"))


def test_cliche_is_flagged():
    result = tone("Hello,\n\nI hope this email finds you well.\n\nBest")

    assert "cliche" in codes(result)


def test_missing_greeting_and_sign_off_are_flagged():
    result = tone("Please send the invoice.")

    assert {"missing_greeting", "missing_sign_off"} <= codes(result)


def test_minor_issues_alone_do_not_fail_the_check():
    result = tone("Hello [Recipient],\n\nThe report is ready.")

    assert codes(result) == {"missing_sign_off"}
    assert result["score"] == 92
    assert result["matches_tone"] is True


def test_one_major_issue_fails_even_when_score_is_above_threshold():
    result = tone(FORMAL + " \U0001F600", "formal")

    assert "emoji" in codes(result)
    assert result["score"] == 80
    assert result["matches_tone"] is False


def test_score_never_goes_below_zero():
    awful = (
        "Hey lol, I can't, gonna pay NOW!!! I hope this email finds you well. "
        "URGENT. Obviously your fault, ridiculous \U0001F600\n\nCheers"
    )
    result = tone(awful, "formal")

    assert result["score"] == 0
    assert result["matches_tone"] is False


def test_long_email_and_long_sentences_are_flagged():
    long_email = "Hello,\n\n" + " ".join(["This is a sentence."] * 80) + "\n\nBest"
    long_sentence = "Hello,\n\n" + " ".join(["word"] * 100) + "\n\nBest"

    assert "long_email" in codes(tone(long_email))
    assert "long_sentences" in codes(tone(long_sentence))


# ===========================================================================
# tone_checker: tone-specific rules
# ===========================================================================

def test_formal_draft_passes():
    result = tone(FORMAL, "formal")

    assert result["matches_tone"] is True
    assert result["issues"] == []


def test_formal_rejects_slang_contractions_and_informal_wording():
    result = tone("Hey John,\n\nI can't come, I'm sick lol!\n\nCheers", "formal")

    assert {"contractions", "slang", "informal_greeting", "informal_sign_off"} <= codes(result)
    assert result["matches_tone"] is False


def test_professional_rejects_slang_and_multiple_exclamations():
    result = tone("Hello,\n\nGonna send it tomorrow!!! Great!!!\n\nBest", "professional")

    assert {"slang", "exclamations"} <= codes(result)


def test_professional_allows_contractions():
    result = tone("Hello [Recipient],\n\nI can't attend, but I'll send notes.\n\nBest regards", "professional")

    assert "contractions" not in codes(result)


def test_warm_draft_passes():
    result = tone(WARM, "warm")

    assert result["matches_tone"] is True


def test_warm_requires_friendly_wording():
    cold = "Hello,\n\nSend the file.\n\nRegards"
    result = tone(cold, "warm")

    assert "not_warm" in codes(result)
    assert result["matches_tone"] is False


def test_warm_exclamation_limit():
    base = "Hello, thank you! "
    assert "exclamations" not in codes(tone(base + "Great! Nice!\n\nBest", "warm"))
    assert "exclamations" in codes(tone(base + "Great! Nice! Wow! Yes!\n\nBest", "warm"))


def test_firm_draft_passes():
    result = tone(FIRM, "firm")

    assert result["matches_tone"] is True
    assert result["issues"] == []


def test_firm_flags_hedging_and_missing_demand():
    soft = (
        "Hi [Recipient],\n\nMaybe you could perhaps send the contract when you get a chance, "
        "if possible. Sorry to bother you.\n\nThanks"
    )
    result = tone(soft, "firm")

    assert {"hedging", "no_clear_demand"} <= codes(result)
    assert result["matches_tone"] is False


def test_firm_flags_exclamation_marks():
    result = tone(FIRM.replace("audit.", "audit!"), "firm")

    assert "exclamations" in codes(result)


def test_casual_draft_passes():
    result = tone(CASUAL, "casual")

    assert result["matches_tone"] is True
    assert result["issues"] == []


def test_casual_flags_stiff_wording():
    result = tone("Dear [Recipient],\n\nPursuant to our call, see the attachment.\n\nBest", "casual")

    assert {"stiff_wording", "stiff_greeting"} <= codes(result)


def test_same_draft_gets_different_verdicts_for_different_tones():
    assert tone(CASUAL, "casual")["matches_tone"] is True
    assert tone(CASUAL, "formal")["matches_tone"] is False


# ===========================================================================
# tone_checker: user style profile
# ===========================================================================

def test_style_profile_not_checked_without_profile():
    assert tone(PROFESSIONAL)["style_profile_checked"] is False
    assert tone(PROFESSIONAL, profile={})["style_profile_checked"] is False


def test_matching_style_profile_produces_no_style_issues():
    profile = {"greeting": "Hello", "sign_off": "Best regards", "max_words": 100}
    result = tone(PROFESSIONAL, profile=profile)

    assert result["style_profile_checked"] is True
    assert not any(c.startswith("style_") for c in codes(result))


def test_style_greeting_and_sign_off_mismatch():
    result = tone(PROFESSIONAL, profile={"greeting": "Hi", "sign_off": "Cheers"})

    assert {"style_greeting", "style_sign_off"} <= codes(result)


def test_style_max_words():
    assert "style_length" in codes(tone(PROFESSIONAL, profile={"max_words": 5}))
    assert "style_length" not in codes(tone(PROFESSIONAL, profile={"max_words": 500}))


def test_style_avoid_phrases():
    result = tone(PROFESSIONAL, profile={"avoid_phrases": ["let me know"]})

    assert "style_avoid_phrases" in codes(result)


def test_style_no_contractions():
    draft = "Hello [Recipient],\n\nI can't attend today.\n\nBest regards"
    result = tone(draft, profile={"uses_contractions": False})

    assert "style_contractions" in codes(result)


def test_style_sentence_length_tolerance():
    # PROFESSIONAL averages 4 words per sentence/line.
    assert "style_sentence_length" in codes(tone(PROFESSIONAL, profile={"avg_words_per_sentence": 20}))
    assert "style_sentence_length" not in codes(tone(PROFESSIONAL, profile={"avg_words_per_sentence": 4}))


def test_malformed_style_profile_values_do_not_crash():
    profile = {"max_words": "lots", "avoid_phrases": "not a list", "avg_words_per_sentence": "x"}

    result = tone(PROFESSIONAL, profile=profile)

    assert result["style_profile_checked"] is True


# ===========================================================================
# sensitive_content_scan: structure and clean input
# ===========================================================================

def test_scan_result_structure():
    result = scan("Hi Bob, lunch at noon?")

    assert set(result) >= {"status", "safe_to_send", "summary", "counts", "findings", "redacted_text"}


def test_clean_text_is_clear():
    result = scan("Hi Bob, lunch at noon? See the agenda for Monday.")

    assert result["status"] == "clear"
    assert result["safe_to_send"] is True
    assert result["findings"] == []
    assert result["summary"] == "No sensitive content detected."


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_is_clear(text):
    result = scan(text)

    assert result["status"] == "clear"
    assert result["safe_to_send"] is True
    assert result["findings"] == []


# ===========================================================================
# sensitive_content_scan: credentials and secrets (high severity)
# ===========================================================================

SECRETS = [
    ("aws_access_key", "AKIAIOSFODNN7EXAMPLE"),
    ("github_token", "ghp_" + "a1" * 18),
    ("slack_token", "xoxb-1234567890-abcdefghij"),
    ("api_key", "sk-" + "abcdefghij" * 3),
    ("google_api_key", "AIza" + "A" * 35),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk123"),
    ("private_key", "-----BEGIN RSA PRIVATE KEY-----"),
    ("connection_string", "postgres://admin:s3cretpw@db.example.com/prod"),
    ("credit_card_number", "4111 1111 1111 1111"),
    ("credit_card_number", "4111-1111-1111-1111"),
    ("us_ssn", "123-45-6789"),
]


@pytest.mark.parametrize("expected_type, secret", SECRETS)
def test_secret_is_detected_blocked_and_never_echoed(expected_type, secret):
    text = f"Please use this: {secret} thanks"
    result = scan(text)

    assert expected_type in types(result)
    assert result["status"] == "blocked"
    assert result["safe_to_send"] is False
    # The raw secret must not appear anywhere in findings or the redacted text.
    assert secret not in json.dumps(result["findings"])
    assert secret not in result["redacted_text"]


@pytest.mark.parametrize(
    "text, expected_type",
    [
        ("My password is Hunter2!", "credential (password)"),
        ("pwd: abc12345", "credential (pwd)"),
        ("API key = abcd1234efgh", "credential (api key)"),
        ("The PIN is 4821", "credential (pin)"),
        ("Passcode: opensesame", "credential (passcode)"),
    ],
)
def test_credential_assignments_are_detected(text, expected_type):
    result = scan(text)

    assert expected_type in types(result)
    assert result["status"] == "blocked"


@pytest.mark.parametrize(
    "text",
    [
        "The token is expired.",
        "Password: [your password]",
        "Password: <password>",
        "password: xxxxxxxx",
        "password: changeme",
        "Please reset your password tomorrow.",
    ],
)
def test_placeholders_and_plain_prose_are_not_credentials(text):
    result = scan(text)

    assert not any(t.startswith("credential") for t in types(result))
    assert result["status"] == "clear"


def test_trailing_sentence_punctuation_is_not_part_of_the_value():
    result = scan("The code is: password: Hunter2.")

    assert result["redacted_text"].endswith("[REDACTED_CREDENTIAL_PASSWORD].")


def test_short_secret_preview_is_fully_masked():
    result = scan("The PIN is 4821")

    assert result["findings"][0]["preview"] == "****"


def test_overlapping_matches_produce_a_single_finding():
    # Matches both the credential rule and the sk- token rule on the same span.
    result = scan("api key: sk-" + "abcdefghij" * 3)

    assert len(result["findings"]) == 1
    assert result["findings"][0]["severity"] == "high"


def test_email_inside_connection_string_is_not_reported_separately():
    result = scan("postgres://admin:s3cretpw@db.example.com/prod")

    assert "email_address" not in types(result)


# ===========================================================================
# sensitive_content_scan: validated identifiers (checksums)
# ===========================================================================

def test_card_number_failing_luhn_is_ignored():
    assert "credit_card_number" not in types(scan("Card 4111 1111 1111 1112"))


@pytest.mark.parametrize("iban", ["HU42 1177 3016 1111 1018 0000 0000", "GB82 WEST 1234 5698 7654 32"])
def test_valid_iban_needs_review_and_is_redacted(iban):
    result = scan(f"Transfer to {iban} please")

    assert "iban" in types(result)
    assert result["status"] == "review"
    assert iban not in result["redacted_text"]
    assert "[REDACTED_IBAN]" in result["redacted_text"]


def test_iban_failing_checksum_is_ignored():
    assert "iban" not in types(scan("Transfer to HU43 1177 3016 1111 1018 0000 0000"))


@pytest.mark.parametrize("ssn", ["000-12-3456", "666-12-3456", "900-12-3456", "123-00-6789", "123-45-0000"])
def test_invalid_ssn_patterns_are_ignored(ssn):
    assert "us_ssn" not in types(scan(f"Reference {ssn}"))


@pytest.mark.parametrize("text", ["Date 2024-01-15 10:30", "Order number 12345678", "Meeting at 10:30-11:30"])
def test_dates_and_plain_numbers_are_not_flagged(text):
    assert scan(text)["findings"] == []


# ===========================================================================
# sensitive_content_scan: personal data (low severity)
# ===========================================================================

@pytest.mark.parametrize("phone", ["+36 20 123 4567", "(555) 123-4567", "555-123-4567"])
def test_phone_numbers_are_low_severity(phone):
    result = scan(f"Call me on {phone}.")

    assert "phone_number" in types(result)
    assert result["status"] == "clear"
    assert result["safe_to_send"] is True
    assert "low-risk" in result["summary"]
    assert phone in result["redacted_text"]  # low severity is reported, not redacted


def test_email_address_is_low_severity():
    result = scan("Write to anna@example.com")

    assert types(result) == ["email_address"]
    assert result["findings"][0]["severity"] == "low"
    assert result["status"] == "clear"


# ===========================================================================
# sensitive_content_scan: confidential wording (medium severity)
# ===========================================================================

@pytest.mark.parametrize(
    "text",
    [
        "This is CONFIDENTIAL.",
        "Please do not forward this message.",
        "Internal use only.",
        "Covered by our NDA.",
        "Contains trade secret material.",
    ],
)
def test_confidential_terms_need_review(text):
    result = scan(text)

    assert "confidential_term" in types(result)
    assert result["status"] == "review"
    assert result["safe_to_send"] is False


def test_confidential_terms_are_kept_in_redacted_text():
    result = scan("This is CONFIDENTIAL.")

    assert result["redacted_text"] == "This is CONFIDENTIAL."
    assert result["findings"][0]["preview"] == "CONFIDENTIAL"


def test_longest_confidential_term_wins_without_duplicate_finding():
    result = scan("This is strictly confidential.")

    terms = [f for f in result["findings"] if f["type"] == "confidential_term"]
    assert len(terms) == 1
    assert terms[0]["preview"] == "strictly confidential"


def test_confidential_terms_respect_word_boundaries():
    assert scan("See the agenda.")["findings"] == []
    assert scan("Our confidentiality policy applies.")["findings"] == []


def test_extra_confidential_terms():
    text = "The Project Falcon launch is next week."

    assert scan(text)["status"] == "clear"
    result = scan(text, extra=["project falcon"])
    assert result["status"] == "review"
    assert "confidential_term" in types(result)


def test_blank_extra_terms_are_ignored():
    assert scan("Hello there.", extra=[" "])["status"] == "clear"


# ===========================================================================
# sensitive_content_scan: status, counts, ordering, redaction
# ===========================================================================

def test_highest_severity_decides_status():
    assert scan("CONFIDENTIAL. Mail anna@example.com")["status"] == "review"
    assert scan("CONFIDENTIAL. password: Hunter2!")["status"] == "blocked"


def test_counts_by_severity():
    result = scan("CONFIDENTIAL. password: Hunter2! Mail anna@example.com")

    assert result["counts"] == {"high": 1, "medium": 1, "low": 1}


def test_findings_are_sorted_by_position_and_report_it():
    key = "AKIAIOSFODNN7EXAMPLE"
    text = f"Mail anna@example.com then use {key}"
    result = scan(text)

    positions = [f["position"] for f in result["findings"]]
    assert positions == sorted(positions)
    aws = next(f for f in result["findings"] if f["type"] == "aws_access_key")
    assert aws["position"] == text.index(key)


def test_redaction_replaces_secrets_and_preserves_surrounding_text():
    text = "Hi Anna, my password is Hunter2! and the card is 4111 1111 1111 1111. Thanks, Bob"
    result = scan(text)

    assert result["redacted_text"] == (
        "Hi Anna, my password is [REDACTED_CREDENTIAL_PASSWORD] and the card is "
        "[REDACTED_CREDIT_CARD_NUMBER]. Thanks, Bob"
    )


def test_redacted_text_no_longer_triggers_a_block():
    text = (
        "Password: Hunter2! Card 4111 1111 1111 1111, SSN 123-45-6789, "
        "key AKIAIOSFODNN7EXAMPLE, IBAN HU42 1177 3016 1111 1018 0000 0000"
    )
    first = scan(text)
    second = scan(first["redacted_text"])

    assert first["status"] == "blocked"
    assert second["status"] != "blocked"
    assert not [f for f in second["findings"] if f["severity"] == "high"]


def test_findings_are_json_serialisable():
    result = scan("password: Hunter2! CONFIDENTIAL anna@example.com")

    json.dumps(result)  # must not raise


def test_findings_contain_recommendations():
    result = scan("password: Hunter2! CONFIDENTIAL anna@example.com")

    assert all(f["recommendation"] for f in result["findings"])