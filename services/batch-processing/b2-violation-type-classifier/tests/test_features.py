from b2_classifier.domain.features import argument_text, session_features


def test_empty_session():
    features = session_features([])
    assert features["n_calls"] == 0
    assert features["n_distinct_tools"] == 0
    assert features["secret_like_argument"] == 0


def test_counts_tools_and_bigrams():
    calls = [
        {"tool_name": "find_contact", "arguments": {}, "success": True},
        {"tool_name": "sensitive_content_scan", "arguments": {}, "success": True},
        {"tool_name": "save_draft", "arguments": {}, "success": True},
    ]

    features = session_features(calls)

    assert features["n_calls"] == 3
    assert features["n_distinct_tools"] == 3
    assert features["count:find_contact"] == 1
    assert features["pair:find_contact>sensitive_content_scan"] == 1
    assert features["pair:sensitive_content_scan>save_draft"] == 1
    assert features["first_tool=find_contact"] == 1
    assert features["last_tool=save_draft"] == 1


def test_detects_secret_like_arguments():
    calls = [
        {
            "tool_name": "save_draft",
            "arguments": {"password": "example123"},
            "success": True,
        }
    ]

    assert session_features(calls)["secret_like_argument"] == 1


def test_detects_failed_calls():
    calls = [
        {"tool_name": "find_contact", "arguments": {}, "success": False},
        {"tool_name": "save_draft", "arguments": {}, "success": True},
    ]

    assert session_features(calls)["n_failed"] == 1


def test_argument_text_handles_missing_arguments():
    assert argument_text({"tool_name": "save_draft"}) == "{}"

def test_extracts_b1_compatible_features():
    calls = [
        {
            "tool_name": "sensitive_content_scan",
            "arguments": {"text": "hello"},
            "duration_ms": 100,
            "time_since_previous_call_ms": 50,
        },
        {
            "tool_name": "save_draft",
            "arguments": {"email": "test@example.com"},
            "duration_ms": 200,
            "time_since_previous_call_ms": 75,
        },
    ]

    features = session_features(calls)

    assert features["unknown_tool_used"] == 0
    assert features["max_gap_ms"] == 75
    assert features["n_email_addresses"] == 1
    assert features["scanned_before_save"] == 1


def test_detects_unknown_tool():
    calls = [{"tool_name": "unexpected_tool", "arguments": {}}]

    features = session_features(calls)

    assert features["unknown_tool_used"] == 1


def test_detects_check_order():
    calls = [
        {"tool_name": "save_draft", "arguments": {}},
        {"tool_name": "sensitive_content_scan", "arguments": {}},
    ]

    features = session_features(calls)

    assert features["scanned_before_save"] == 0
