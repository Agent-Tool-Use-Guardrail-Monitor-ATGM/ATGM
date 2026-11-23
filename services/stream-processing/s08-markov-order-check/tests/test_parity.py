"""Parity (spec Sec. 10.4): the stream's running scores equal B3's whole-session ``Detector.score``.

S08 scores one event at a time through ``b3_markov``'s ``step`` and per-call featurizer;
B3 scores whole sessions in batch. Both must agree within 1e-9 on every session.
"""

import copy

import pytest
from conftest import feed, make_pipeline, session_events

from markov_order_check.demo import build_table, demo_session_with_arguments
from markov_order_check.scoring import MarkovModel

from b3_markov.domain.sessions import Session
from b3_markov.domain.training import from_table

# B3 Sec. 8 worked example: the two normal sample sessions, and the adversarial one
S1 = ["find_contact", "get_current_datetime", "get_free_slots", "tone_checker", "sensitive_content_scan", "save_draft"]
S2 = ["find_contact", "get_current_datetime", "get_free_slots", "save_draft"]
ADV = ["find_contact", "get_current_datetime", "get_free_slots", "get_free_slots", "tone_checker",
       "sensitive_content_scan", "save_draft"]
OTHERS = [["find_contact", "save_draft"], ["save_draft"] * 4, ["find_contact", "delete_everything"], []]


def _stream_session(model: MarkovModel, events, order: int):
    out = feed(make_pipeline(model, order={"A": order, "B": order}, empty_session={"A": "alert", "B": "alert"}),
               events, agent=model.agent)
    return next(o for o in out if o.kind == "session").event["data"]


def test_worked_example_counts():
    table = build_table([S1, S2], orders=(1,))
    rows = table["orders"]["1"]["transitions"]
    assert table["orders"]["1"]["n_transitions"] == 12
    assert rows["<START>"]["next"]["find_contact"]["count"] == 2
    assert rows["get_free_slots"]["next"]["tone_checker"]["p_mle"] == 0.5


@pytest.mark.parametrize("smoothing", ["additive", "floor", "backoff"])
@pytest.mark.parametrize("order", [1, 2])
def test_sequence_scores_equal_b3(smoothing, order):
    table = build_table([S1, S2, S1], orders=(1, 2), smoothing=smoothing)
    model = MarkovModel(table, version="t", agent="B")
    batch = from_table(table)
    for tools in [S1, S2, ADV, *OTHERS]:
        stream = _stream_session(model, session_events("B", tools), order)
        expected = batch.score(order, Session("x", tools))
        assert stream["seq_score"] == pytest.approx(expected["mean_nll"], abs=1e-9)
        assert stream["score"] == pytest.approx(round(expected["score"], 6), abs=1e-9)
        assert stream["n_unseen"] == expected["n_unseen"]
        assert stream["min_p"] == pytest.approx(expected["min_p"], abs=1e-9)


def test_stream_step_is_b3_step():
    table = build_table([S1, S2], orders=(2,))
    model = MarkovModel(table, version="t", agent="B")
    batch = from_table(table).chain
    from b3_markov.domain.scoring import step

    ctx = ("<START>", "find_contact")
    for sym in model.next_symbols:
        assert model.step(2, ctx, sym).lp == step(batch, 2, ctx, sym)[0]


NORMAL_ARGS = [
    [("find_contact", {"name": "Bob Smith"}), ("get_free_slots", {"date": "2026-11-16"}),
     ("tone_checker", {"draft": "Hi Bob, can we meet?"}),
     ("sensitive_content_scan", {"text": "Hi Bob, can we meet?", "extra_confidential_terms": []}),
     ("save_draft", {"to": "bob@example.com", "subject": "Meeting", "body": "Hi Bob, can we meet?"})],
    [("find_contact", {"name": "Ann Lee"}), ("get_free_slots", {"date": "2026-11-18"}),
     ("save_draft", {"to": "ann@example.com", "subject": "Lunch", "body": "Lunch on Tuesday?"})],
]
TAMPERED = [("find_contact", {"name": "Bob Smith"}), ("get_free_slots", {"date": "2026-11-16"}),
            ("tone_checker", {"draft": "Hi Bob"}),
            ("sensitive_content_scan", {"text": "Hi Bob", "extra_confidential_terms": []}),
            ("save_draft", {"to": "x@mailcollector.example", "subject": "Hi",
                            "body": "Hi Bob, card number 4111 1111 1111 1111"})]


def test_joint_scores_with_arguments_equal_b3():
    sessions = [demo_session_with_arguments(c, f"n{i}") for i, c in enumerate(NORMAL_ARGS * 3)]
    table = build_table(sessions, orders=(1, 2), with_arguments=True)
    assert table["scoring"]["score"] == "joint" and "arguments" in table
    model = MarkovModel(copy.deepcopy(table), version="t", agent="B")
    batch = from_table(table)
    for calls in NORMAL_ARGS + [TAMPERED]:
        tools = [t for t, _ in calls]
        events = session_events("B", tools, arguments=[a for _, a in calls],
                                start=__import__("datetime").datetime.fromisoformat("2026-11-14T10:00:00+00:00"))
        stream = _stream_session(model, events, 2)
        b3_session = Session("x", tools, calls=[c for c in demo_session_with_arguments(calls, "x").calls])
        for call, event in zip(b3_session.calls, [e for e in events if e["event_type"] == "tool_call.completed"]):
            call.occurred_at = event["occurred_at"]
        expected = batch.score(2, b3_session)
        assert stream["score"] == pytest.approx(round(expected["joint"], 6), abs=1e-9)
        assert stream["arg_score"] == pytest.approx(expected["arg_total"], abs=1e-9)
        assert stream["arg_max"] == pytest.approx(expected["arg_max"], abs=1e-9)
        assert stream["worst_arg"] == (expected["worst_arg"] or None)
    tampered = _stream_session(model, session_events("B", [t for t, _ in TAMPERED],
                                                     arguments=[a for _, a in TAMPERED]), 2)
    assert tampered["worst_arg"].startswith("save_draft:")
