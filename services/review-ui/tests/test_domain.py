import pytest

from review_ui.domain import item_from_decision, label_event, without_ground_truth

ROW = {"event_id": "d1", "occurred_at": "2026-11-28T10:00:00Z", "session_id": "s1", "run_id": "r1",
       "data": {"agent_id": "B", "detector": "aci", "scored_event_id": "e9", "decision": "review",
                "audit": False, "session_score": 0.61, "pass_up_to": 0.4, "flag_from": 0.8}}


def test_item_keeps_what_the_label_needs():
    item = item_from_decision(ROW)
    assert (item["session_id"], item["scored_event_id"], item["detector"], item["agent_id"]) == ("s1", "e9", "aci", "B")
    assert item["decision"] == "review" and item["audit"] is False


def test_label_has_the_simulated_reviewers_shape():
    ev = label_event(item_from_decision(ROW), "attack", "out_of_order", "  Áron  ")
    assert ev["event_type"] == "review.labelled" and ev["schema_version"] == "1.0"
    assert ev["session_id"] == "s1" and ev["run_id"] == "r1"
    assert ev["data"] == {"scored_event_id": "e9", "detector": "aci", "verdict": "attack",
                          "violation_type": "out_of_order", "agent_id": "B", "reviewer": "human:Áron"}


def test_normal_verdict_drops_the_violation_type():
    ev = label_event(item_from_decision(ROW), "false_alarm", "unsafe_args", "")
    assert ev["data"]["violation_type"] is None and ev["data"]["reviewer"] == "human:anonymous"


@pytest.mark.parametrize("verdict,vtype", [("maybe", None), ("attack", None), ("attack", "made_up")])
def test_invalid_verdicts_are_rejected(verdict, vtype):
    with pytest.raises(ValueError):
        label_event(item_from_decision(ROW), verdict, vtype, "x")


def test_sessions_with_ground_truth_are_left_to_the_simulated_reviewer():
    items = [item_from_decision(ROW), item_from_decision({**ROW, "session_id": "s2"})]
    assert [i["session_id"] for i in without_ground_truth(items, {"s1"})] == ["s2"]
