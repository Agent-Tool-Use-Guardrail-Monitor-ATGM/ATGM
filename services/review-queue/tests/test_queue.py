import random

import pytest

from review_queue.adapters.events import label_event
from review_queue.domain.queue import Item, ReviewQueue, Truth, parse_item

TRUTH = {"s-attack": Truth("adversarial", "unauthorized_tool"), "s-normal": Truth("normal", None)}


def item(session, ref="e1", detector="mock_scorer"):
    return Item(ref, detector, session, "B", "run-1")


def alarm(session="s-attack", ref="e1"):
    return {"schema_version": "1.0", "event_type": "alarm.raised", "session_id": session, "run_id": "run-1",
            "data": {"scored_event_id": ref, "agent_id": "B", "detector": "mock_scorer", "score": 9.0}}


def test_items_are_answered_after_the_delay_with_the_ground_truth():
    q = ReviewQueue(TRUTH.get, delay=10)
    q.submit(item("s-attack", "e1"), now=0)
    q.submit(item("s-normal", "e2"), now=1)
    assert q.due(9.9) == []
    [first] = q.due(10)
    assert (first.verdict, first.violation_type, first.item.scored_event_id) == ("attack", "unauthorized_tool", "e1")
    [second] = q.due(11)
    assert (second.verdict, second.violation_type) == ("false_alarm", None)
    assert len(q) == 0


def test_a_session_is_judged_once_and_every_alarm_gets_the_same_verdict():
    calls = []
    def truth(s):
        calls.append(s)
        return TRUTH.get(s)
    q = ReviewQueue(truth, delay=0, error_rate=0.5, rng=random.Random(0))
    for ref in ("e1", "e2", "e3"):
        q.submit(item("s-normal", ref), now=0)
    labels = q.due(0)
    assert len(labels) == 3 and len({lab.verdict for lab in labels}) == 1
    assert calls == ["s-normal"]


def test_reviewer_error_rate():
    truth = {f"s{i}": Truth("normal", None) for i in range(2_000)}
    q = ReviewQueue(truth.get, delay=0, error_rate=0.1, rng=random.Random(1))
    for s in truth:
        q.submit(item(s), now=0)
    wrong = sum(lab.verdict == "attack" for lab in q.due(0))
    assert 150 < wrong < 250
    assert all(lab.violation_type == "unknown" for lab in q.due(0) if lab.verdict == "attack")


def test_missing_ground_truth_is_retried_then_dropped():
    store = {}
    q = ReviewQueue(store.get, delay=2, retries=2)
    q.submit(item("late"), now=0)
    assert q.due(2) == [] and len(q) == 1                 # retry 1
    store["late"] = Truth("normal", None)
    assert [lab.verdict for lab in q.due(4)] == ["false_alarm"]

    q.submit(item("never"), now=10)
    for t in (12, 14, 16, 18):
        q.due(t)
    assert len(q) == 0 and q.dropped == 1


def test_parse_item_accepts_alarms_and_review_decisions_only():
    assert parse_item(alarm()) == Item("e1", "mock_scorer", "s-attack", "B", "run-1")
    review = {**alarm(), "event_type": "decision.made", "data": {**alarm()["data"], "decision": "review"}}
    assert parse_item(review) is not None
    flag = {**review, "data": {**review["data"], "decision": "flag"}}
    assert parse_item(flag) is None
    assert parse_item({"event_type": "other", "data": {}}) is None
    with pytest.raises(ValueError):
        parse_item({"event_type": "alarm.raised", "data": {"detector": "x"}, "session_id": "s"})
    with pytest.raises(ValueError):
        parse_item({"event_type": "alarm.raised"})


def test_label_event_envelope():
    q = ReviewQueue(TRUTH.get, delay=0)
    q.submit(parse_item(alarm()), now=0)
    ev = label_event(q.due(0)[0])
    assert ev["schema_version"] == "1.0" and ev["event_type"] == "review.labelled"
    assert ev["session_id"] == "s-attack" and ev["run_id"] == "run-1"
    assert ev["data"] == {"scored_event_id": "e1", "detector": "mock_scorer", "verdict": "attack",
                          "violation_type": "unauthorized_tool", "agent_id": "B", "reviewer": "simulated"}


def test_validation():
    with pytest.raises(ValueError):
        ReviewQueue(TRUTH.get, delay=-1)
    with pytest.raises(ValueError):
        ReviewQueue(TRUTH.get, error_rate=1.5)
