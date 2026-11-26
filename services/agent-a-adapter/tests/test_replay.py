import json

from agent_a_adapter.replay import load_sessions


def test_collector_lines_are_unwrapped_grouped_and_ordered():
    def ev(sid, seq):
        return {"event_id": f"{sid}-{seq}", "session_id": sid, "sequence": seq, "event_type": "x"}
    lines = [json.dumps({"source": "real", "event": ev("a", 2)}), json.dumps(ev("b", 1)), "",
             json.dumps({"source": "real", "event": ev("a", 1)})]
    sessions = load_sessions(lines)
    assert list(sessions) == ["a", "b"]
    assert [e["sequence"] for e in sessions["a"]] == [1, 2]
