from b1_classifier.domain.sessions import SessionBuffer


def event(event_type, session="s1", data=None, event_id="e"):
    return {"event_type": event_type, "session_id": session, "event_id": event_id,
            "data": data or {"agent_id": "B"}}


def call(index, tool):
    return event("tool_call.completed", data={"agent_id": "B", "tool_name": tool,
                                             "session_call_index": index})


def test_returns_calls_in_order_on_session_end():
    buffer = SessionBuffer()
    buffer.add(event("session.started"))
    buffer.add(call(2, "save_draft"))
    buffer.add(call(1, "find_contact"))
    finished = buffer.add(event("session.ended", event_id="end-1"))

    assert finished.session_id == "s1"
    assert finished.agent_id == "B"
    assert finished.ended_event_id == "end-1"
    assert [c["tool_name"] for c in finished.calls] == ["find_contact", "save_draft"]
    assert buffer.open_sessions == 0


def test_skips_session_without_start():
    buffer = SessionBuffer()
    buffer.add(call(1, "find_contact"))
    assert buffer.add(event("session.ended")) is None


def test_session_without_calls_is_still_scored():
    buffer = SessionBuffer()
    buffer.add(event("session.started"))
    finished = buffer.add(event("session.ended"))
    assert finished.calls == []


def test_forgets_oldest_when_too_many_open():
    buffer = SessionBuffer(max_open=2)
    for session in ["a", "b", "c"]:
        buffer.add(event("session.started", session=session))
    assert buffer.open_sessions == 2
    assert buffer.add(event("session.ended", session="a")) is None