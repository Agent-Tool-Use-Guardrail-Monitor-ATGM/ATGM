import json

from b1_classifier.adapters.dataset import from_collector
from b1_classifier.domain.features import KNOWN_TOOLS_A, session_features


def row(category, event_type, sequence, at, data, session="s1"):
    return {"category": category, "label": "tool_trace_allowed",
            "event": {"session_id": session, "event_type": event_type, "sequence": sequence,
                      "occurred_at": f"2026-11-14T22:52:{at}Z", "data": data}}


def write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return path


def test_pairs_requested_with_outcome(tmp_path):
    rows = [
        row("normal", "session.started", 1, "00.000", {}),
        row("normal", "tool_call.requested", 2, "01.000",
            {"name": "inspect_dataset", "tool_call_id": "t1", "session_call_index": 1, "features": {"column_count": 0}}),
        row("normal", "tool_call.completed", 3, "01.500", {"tool_call_id": "t1", "status": "completed"}),
        row("normal", "tool_call.requested", 4, "03.000",
            {"tool_call_id": "t2", "session_call_index": 2, "features": {}}),
        row("normal", "tool_call.failed", 5, "03.100", {"tool_call_id": "t2", "status": "failed"}),
        row("normal", "session.ended", 6, "04.000", {}),
    ]
    [(session, calls, label)] = from_collector(write(tmp_path / "a.jsonl", rows))

    assert (session, label) == ("s1", "compliant")
    assert [c["tool_name"] for c in calls] == ["inspect_dataset", "unknown"]
    assert [c["success"] for c in calls] == [True, False]
    assert calls[0]["duration_ms"] == 500
    assert calls[1]["time_since_previous_call_ms"] == 2000


def test_injected_is_violating_and_unknown_tool_is_flagged(tmp_path):
    rows = [row("prompt_injected", "tool_call.requested", 1, "01.000",
                {"tool_call_id": "t1", "session_call_index": 1})]
    [(_, calls, label)] = from_collector(write(tmp_path / "a.jsonl", rows))

    assert label == "violating"
    assert session_features(calls, KNOWN_TOOLS_A)["unknown_tool_used"] == 1