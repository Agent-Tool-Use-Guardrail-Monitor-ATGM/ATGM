from b1_classifier.domain.features import session_features

def call(tool, index, **arguments):
    return {"tool_name": tool, "arguments": arguments, "session_call_index": index,
            "duration_ms": 10, "success": True, "time_since_previous_call_ms": 5}


def test_normal_session():
    calls = [call("find_contact", 1, name="Tom"), call("tone_checker", 2, draft="Hi"),
             call("sensitive_content_scan", 3, text="Hi"), call("save_draft", 4, to="tom.berger@example.com")]
    features = session_features(calls)
    assert features["n_calls"] == 4 and features["count:save_draft"] == 1
    assert features["scanned_before_save"] == 1 and features["tone_checked_before_save"] == 1
    assert features["unknown_tool_used"] == 0 and features["secret_like_argument"] == 0
    assert features["first_tool=find_contact"] == 1 and features["pair:find_contact>tone_checker"] == 1


def test_attack_signals():
    calls = [call("save_draft", 1, body="card number 4111 1111 1111 1111"), call("send_email", 2, to="x@y.example")]
    features = session_features(calls)
    assert features["secret_like_argument"] == 1
    assert features["unknown_tool_used"] == 1
    assert features["scanned_before_save"] == 0


def test_empty_session():
    assert session_features([])["n_calls"] == 0