from b3_markov.domain.sessions import Session

FULL = ["find_contact", "get_current_datetime", "get_free_slots", "tone_checker", "sensitive_content_scan", "save_draft"]
SHORT = ["find_contact", "get_current_datetime", "get_free_slots", "save_draft"]


def sess(tools, sid="s", category="normal", attack_type=None, label=None):
    return Session(sid, list(tools), category, attack_type, label)


def events(sid, tools, category="normal", attack_type=None, ended=True, count=None, prefix=""):
    out = [{"event_id": f"{prefix}{sid}-start", "event_type": "session.started", "session_id": sid,
            "data": {"agent_id": "B", "category": category, "attack_type": attack_type}}]
    for i, t in enumerate(tools, 1):
        out.append({"event_id": f"{prefix}{sid}-{i}", "event_type": "tool_call.completed", "session_id": sid,
                    "data": {"agent_id": "B", "tool_name": t, "session_call_index": i}})
    if ended:
        out.append({"event_id": f"{prefix}{sid}-end", "event_type": "session.ended", "session_id": sid,
                    "data": {"agent_id": "B", "call_count": len(tools) if count is None else count}})
    return out


def call(tool, at="2026-11-19T10:00:00+00:00", **args):
    from b3_markov.domain.sessions import Call
    return Call(tool, args, at)


TEXT = "Dear Tom, lunch on Friday?"


def normal_calls(to="tom@example.com", name="Tom", date="2026-11-20", body=TEXT, terms=("[Your Name]",), scan_text=TEXT):
    return [call("find_contact", name=name), call("get_current_datetime"), call("get_free_slots", date=date),
            call("tone_checker", draft=TEXT, requested_tone="warm"),
            call("sensitive_content_scan", text=scan_text, extra_confidential_terms=list(terms)),
            call("save_draft", to=to, subject="Lunch", body=body)]


def call_session(calls, sid="s", category="normal", attack_type=None):
    return Session(sid, [c.tool for c in calls], category, attack_type, calls=calls)
