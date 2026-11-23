import json

from b3_markov.adapters import dataset
from b3_markov.domain.sequences import UNK


def rec(session, seq, kind, data, category="normal", attack=None, label="tool_trace_allowed", eid=None):
    return {"source": "recorded", "agent": "datalens", "case_id": f"case-{session}", "scenario": "s",
            "category": category, "attack_type": attack, "label": label, "label_version": "1",
            "label_evidence_event_ids": [], "policy_denied_event_ids": [],
            "event": {"event_id": eid or f"{session}-{seq}", "event_type": kind, "session_id": session,
                      "sequence": seq, "occurred_at": f"2026-11-22T10:00:0{seq}+00:00", "data": data}}


def write(tmp_path, records):
    path = tmp_path / "agent_a.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n{truncated")
    return path


def test_requested_completed_pair_gives_one_call_with_the_requested_name(tmp_path):
    path = write(tmp_path, [
        rec("s1", 1, "session.started", {}),
        rec("s1", 2, "tool_call.requested", {"tool_call_id": "t1", "name": "inspect_dataset", "kind": "tool"}),
        rec("s1", 3, "tool_call.completed", {"tool_call_id": "t1", "status": "ok"}),
        rec("s1", 4, "session.ended", {})])
    (s,) = dataset.from_agent_a_file(path)
    assert s.tools == ["inspect_dataset"] and s.category == "normal" and s.label == "tool_trace_allowed"


def test_unnamed_request_is_unk_and_failed_call_is_kept_and_model_calls_ignored(tmp_path):
    path = write(tmp_path, [
        rec("s1", 1, "session.started", {}),
        rec("s1", 2, "model_call.completed", {}),
        rec("s1", 3, "tool_call.requested", {"tool_call_id": "t1", "kind": "unknown"}),
        rec("s1", 4, "tool_call.failed", {"tool_call_id": "t1", "reason": "unknown_tool"}),
        rec("s1", 5, "tool_call.requested", {"tool_call_id": "t2", "name": "aggregate_statistics"}),
        rec("s1", 6, "tool_call.failed", {"tool_call_id": "t2", "reason": "execution_result"}),
        rec("s1", 7, "model_call.failed", {})])
    (s,) = dataset.from_agent_a_file(path)
    assert s.tools == [UNK, "aggregate_statistics"]


def test_wrapper_category_becomes_the_session_category_and_zero_call_sessions_are_kept(tmp_path):
    path = write(tmp_path, [
        rec("n", 1, "session.started", {}),
        rec("p", 1, "session.started", {}, "prompt_injected", "direct_prompt_injection", "answer_violation"),
        rec("p", 2, "tool_call.requested", {"tool_call_id": "t", "name": "finalize_statistics"}),
        rec("p", 3, "tool_call.completed", {"tool_call_id": "t"})])
    by_id = {s.session_id: s for s in dataset.from_agent_a_file(path)}
    assert by_id["n"].tools == [] and by_id["n"].category == "normal"
    assert by_id["p"].category == "prompt_injected" and by_id["p"].attack_type == "direct_prompt_injection"


def test_calls_are_ordered_by_session_call_index_else_sequence_and_duplicates_dropped(tmp_path):
    path = write(tmp_path, [
        rec("s", 1, "session.started", {}),
        rec("s", 5, "tool_call.requested", {"tool_call_id": "b", "name": "describe_columns"}),
        rec("s", 6, "tool_call.completed", {"tool_call_id": "b", "session_call_index": 2}),
        rec("s", 2, "tool_call.requested", {"tool_call_id": "a", "name": "inspect_dataset"}),
        rec("s", 3, "tool_call.completed", {"tool_call_id": "a", "session_call_index": 1}),
        rec("s", 3, "tool_call.completed", {"tool_call_id": "a", "session_call_index": 1}, eid="s-3")])
    (s,) = dataset.from_agent_a_file(path)
    assert s.tools == ["inspect_dataset", "describe_columns"]


def test_a_sequence_without_call_index_uses_the_envelope_sequence(tmp_path):
    path = write(tmp_path, [
        rec("s", 1, "session.started", {}),
        rec("s", 4, "tool_call.completed", {"tool_call_id": "b", "name": "correlate_columns"}),
        rec("s", 2, "tool_call.completed", {"tool_call_id": "a", "name": "inspect_dataset"})])
    (s,) = dataset.from_agent_a_file(path)
    assert s.tools == ["inspect_dataset", "correlate_columns"]
