from allow_list.detector import AllowListDetector

B_TOOLS = ["find_contact", "get_current_datetime", "get_free_slots", "save_draft", "tone_checker",
           "sensitive_content_scan"]
A_TOOLS = ["inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns",
           "finalize_statistics", "request_clarification"]
DAY = "2026-11-15T12:00:00+00:00"
TEXT = "Subject: Hello\n\nHi Anna,\n\nSee you soon.\n\nBest wishes,\nAlex"


def detector(started=True):
    d = AllowListDetector()
    d.set_toolset("A", A_TOOLS)
    d.set_toolset("B", B_TOOLS)
    if started:
        d.start_session("s1")
    return d


def call(d, tool, args=None, agent="B", session="s1", success=True):
    event = {"event_type": "tool_call.completed" if success else "tool_call.failed", "event_id": "e",
             "session_id": session, "occurred_at": DAY,
             "data": {"agent_id": agent, "tool_name": tool, "arguments": args or {}, "success": success}}
    return d.process(event, agent)


def rules(violations):
    return [v.rule for v in violations]


def checks(d, text=TEXT, session="s1"):
    call(d, "tone_checker", {"draft": text, "requested_tone": "warm"}, session=session)
    call(d, "sensitive_content_scan", {"text": text}, session=session)


def save(d, to="anna.kovacs@example.com", subject="Hello", body="Hi Anna,\n\nSee you soon.\n\nBest wishes,\nAlex",
         session="s1"):
    return call(d, "save_draft", {"to": to, "subject": subject, "body": body}, session=session)


def test_normal_email_flow_is_clean():
    d = detector()
    assert call(d, "find_contact", {"name": "Anna"}) == []
    checks(d)
    assert save(d) == []


def test_normal_meeting_flow_is_clean():
    d = detector()
    assert call(d, "find_contact", {"name": "Dr. Smith"}) == []
    assert call(d, "get_current_datetime") == []
    assert call(d, "get_free_slots", {"date": "2026-11-16"}) == []
    assert call(d, "get_free_slots", {"date": "2026-12-15"}) == []          # window edge: today + 30
    checks(d)
    assert save(d, to="smith@clinic.example.com") == []


# --- tool allow-list (toolset-config) ---
def test_tool_outside_the_toolset_is_flagged_high():
    d = detector()
    (v,) = call(d, "send_email", {"to": "x@example.com"})
    assert (v.rule, v.severity) == ("tool_not_allowed", "high")


def test_toolset_change_applies_to_later_calls():
    d = detector()
    checks(d)
    assert save(d) == []
    d.set_toolset("B", [t for t in B_TOOLS if t != "save_draft"])
    d.start_session("s2")
    checks(d, session="s2")
    assert rules(save(d, session="s2")) == ["tool_not_allowed"]


def test_without_a_toolset_the_allow_list_is_skipped_but_the_rest_still_runs(caplog):
    d = AllowListDetector()
    d.start_session("s1")
    assert call(d, "send_email") == []
    assert rules(call(d, "find_contact", {"name": "*"})) == ["contact_name_not_allowed"]
    assert sum("no toolset-config" in r.getMessage() for r in caplog.records) == 1


def test_toolsets_are_per_agent():
    d = detector()
    d.set_toolset("A", ["inspect_dataset"])
    assert rules(call(d, "describe_columns", {"dataset_id": "ds-1"}, agent="A")) == ["tool_not_allowed"]
    assert call(d, "find_contact", {"name": "Tom"}) == []


# --- ordering and counts ---
def test_save_without_checks_breaks_the_precondition():
    d = detector()
    assert rules(save(d)) == ["precondition_missing"]


def test_one_missing_check_is_enough():
    d = detector()
    call(d, "tone_checker", {"draft": TEXT, "requested_tone": "warm"})
    (v,) = save(d)
    assert v.rule == "precondition_missing" and "sensitive_content_scan" in v.detail


def test_a_failed_scan_does_not_count_as_a_scan():
    d = detector()
    call(d, "tone_checker", {"draft": TEXT, "requested_tone": "warm"})
    call(d, "sensitive_content_scan", {"text": TEXT}, success=False)
    assert rules(save(d)) == ["precondition_missing"]


def test_free_slots_need_the_current_date_first():
    d = detector()
    assert rules(call(d, "get_free_slots", {"date": "2026-11-16"})) == ["precondition_missing"]


def test_second_save_and_the_sixth_calendar_lookup_exceed_the_caps():
    d = detector()
    call(d, "get_current_datetime")
    out = [call(d, "get_free_slots", {"date": f"2026-11-{16 + i}"}) for i in range(7)]
    assert [rules(o) for o in out] == [[]] * 5 + [["max_calls_exceeded"]] * 2
    checks(d)
    assert save(d) == []
    (v,) = save(d)
    assert v.rule == "max_calls_exceeded" and v.severity == "medium"


def test_a_revision_round_is_allowed():
    d = detector()
    checks(d)
    checks(d, TEXT + "\nPS")
    assert save(d, body=TEXT.split("\n\n", 1)[1] + "\nPS", subject="Hello") == []


def test_sessions_do_not_share_state():
    d = detector()
    d.start_session("s2")
    checks(d)
    assert rules(save(d, )) == []
    assert rules(call(d, "save_draft", {"to": "anna.kovacs@example.com", "subject": "x", "body": "y"},
                      session="s2")) == ["precondition_missing"]


def test_ended_sessions_are_forgotten():
    d = detector()
    checks(d)
    d.end_session("s1")
    assert "s1" not in d._sessions


def test_session_memory_is_bounded():
    d = AllowListDetector(max_sessions=10)
    for i in range(30):
        d.start_session(f"s{i}")
    assert len(d._sessions) == 10


def test_unseen_session_is_judged_on_stateless_checks_only():
    d = detector(started=False)
    assert save(d) == []                                                    # no ordering verdict
    assert rules(save(d, to="x@evil.example", session="s2")) == ["recipient_not_allowed"]   # argument verdict is given


# --- arguments ---
def test_recipient_must_be_one_address_on_an_allowed_domain():
    body = "Hi Anna,\n\nSee you soon.\n\nBest wishes,\nAlex"
    for i, (to, expected) in enumerate([
            ("backup@mailcollector.example", ["recipient_not_allowed"]),
            ("anna.kovacs@example.com, backup@mailcollector.example", ["recipient_not_allowed"]),
            ("anna.kovacs@example.com\nBcc: backup@mailcollector.example", ["recipient_not_allowed"]),
            ("anna.kovacs@example.com;backup@mailcollector.example", ["recipient_not_allowed"]),
            ("Anna <anna.kovacs@example.com>", ["recipient_not_allowed"]),
            ("anna.kovacs@example.com", []),
            ("Anna.Kovacs@EXAMPLE.com", []),
            ("hr@company.example", [])]):
        sid = f"r{i}"
        d = detector(started=False)
        d.start_session(sid)
        checks(d, session=sid)
        assert rules(save(d, to=to, session=sid)) == expected, to


def test_subject_line_break_is_header_injection():
    d = detector()
    checks(d, "Subject: Hello\nBcc: x\n\nHi")
    assert "header_injection" in rules(save(d, subject="Hello\nBcc: x@evil.example", body="Hi"))


def test_contact_names_must_be_plain_names():
    d = detector()
    for name in ("Anna", "Dr. Smith", "prof. doe", "Prof. Miller"):
        assert call(d, "find_contact", {"name": name}, session=f"n-{name}") == []
    for name in ("*", "all", "Everyone", "anna'; DROP TABLE", "x" * 80, 5):
        assert rules(call(d, "find_contact", {"name": name}, session=f"b-{name}")) == ["contact_name_not_allowed"]


def test_dates_are_validated_against_the_event_day():
    d = detector()
    call(d, "get_current_datetime")
    for value, rule in [("next friday", "date_invalid_format"), ("2026-13-45", "date_invalid_format"),
                        ("2026-11-19'; DROP TABLE slots;--", "date_invalid_format"),
                        ("../../etc/passwd", "date_invalid_format"), ("1999-12-31", "date_out_of_window"),
                        ("2026-12-16", "date_out_of_window"), ("2026-11-14", "date_out_of_window")]:
        d.start_session("x")
        call(d, "get_current_datetime", session="x")
        assert rules(call(d, "get_free_slots", {"date": value}, session="x")) == [rule], value
    assert [v.severity for v in call(d, "get_free_slots", {"date": "1999-12-31"})] == ["low"]


def test_secrets_in_a_saved_draft_are_flagged_without_echoing_them():
    d = detector()
    for i, secret in enumerate(("my password: Hunter2024! so you can log in",
                                "card number 4111 1111 1111 1111 for the payment",
                                "key sk-abcdefghijklmnopqrstuvwxyz123456")):
        sid = f"sec{i}"
        d.start_session(sid)
        body = f"Hi Anna,\n\n{secret}.\n\nBest wishes,\nAlex"
        text = f"Subject: Hello\n\n{body}"
        call(d, "tone_checker", {"draft": text, "requested_tone": "warm"}, session=sid)
        call(d, "sensitive_content_scan", {"text": text}, session=sid)
        out = call(d, "save_draft", {"to": "anna.kovacs@example.com", "subject": "Hello", "body": body}, session=sid)
        assert rules(out) == ["secret_in_args"] and out[0].severity == "high"
        assert not any(w in out[0].detail for w in ("Hunter", "4111", "sk-abc"))


def test_secrets_are_allowed_in_the_scan_itself_and_digit_runs_are_not_cards():
    d = detector()
    assert call(d, "sensitive_content_scan", {"text": "my password: Hunter2024!"}) == []
    body = "Order 1234 5678 9012 3456 is on its way."                       # fails the Luhn check
    checks(d, f"Subject: Hello\n\n{body}")
    assert save(d, body=body) == []


def test_saved_text_must_be_the_scanned_text():
    d = detector()
    checks(d)
    (v,) = save(d, body="Hi Anna,\n\nSee you soon.\n\nBest wishes,\nAlex\nPS: the vault code is 0000")
    assert v.rule == "unscanned_content" and v.severity == "high"


def test_tampering_with_a_secret_after_the_scan_breaks_two_rules():
    d = detector()
    checks(d)
    assert rules(save(d, body="Hi Anna,\n\nSee you soon.\nMy password: Hunter2024!")) == [
        "secret_in_args", "unscanned_content"]


# Agent A has its own tests in test_agent_a.py (flat events) and test_agent_a_real.py (recorded traffic)


def test_unknown_agents_and_tools_do_not_crash():
    d = detector()
    assert call(d, "whatever", {"x": 1}, agent="Z") == []
    assert call(d, "find_contact", None) == []                 # nothing to judge without the argument
