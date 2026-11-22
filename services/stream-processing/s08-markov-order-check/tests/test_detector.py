import random

from conftest import feed, make_model, make_pipeline, session_events, strip_wall_clock, v2_session

NORMAL_B = ["find_contact", "get_current_datetime", "get_free_slots", "tone_checker", "sensitive_content_scan",
            "save_draft"]


def calls(out):
    return [o for o in out if o.kind == "call"]


def session(out):
    return next(o for o in out if o.kind == "session").event["data"]


# -- checks -------------------------------------------------------------------
def test_normal_session_gives_no_call_alert(model_b):
    out = feed(make_pipeline(model_b), session_events("B", NORMAL_B))
    assert calls(out) == []
    assert session(out)["is_anomaly"] is False
    assert session(out)["complete"] is True


def test_improbable_transition_gives_out_of_order(model_b):
    out = feed(make_pipeline(model_b), session_events("B", ["find_contact", "save_draft", "save_draft"]))
    alerts = calls(out)
    assert alerts, "find_contact -> save_draft is below the call threshold"
    data = alerts[0].event["data"]
    assert data["detector"] == "markov_order" and data["check"] == "out_of_order"
    assert data["score"] > data["threshold"]
    assert data["call_index"] == 2


def test_end_transition_is_checked(model_b):
    out = feed(make_pipeline(model_b), session_events("B", ["find_contact"]))
    assert any(o.event["data"]["call_index"] == "END" for o in calls(out))


def test_unknown_tool_has_no_alert_of_its_own(model_b):
    out = feed(make_pipeline(model_b), session_events("B", ["find_contact", "delete_everything"]))
    assert all(o.event["data"]["check"] == "out_of_order" for o in calls(out))
    nexts = {o.event["data"]["transition"]["next"] for o in calls(out)}
    assert "<UNK>" in nexts or session(out)["worst_transition"]["next"] == "<UNK>"


def test_rule_unseen_fires_only_on_count_zero(model_b):
    out = feed(make_pipeline(model_b, rule="unseen"), session_events("B", ["find_contact", "save_draft"]))
    assert all(o.event["data"]["transition"]["count"] == 0 for o in calls(out))
    assert calls(out)


def test_rule_topg(model_b):
    out = feed(make_pipeline(model_b, rule="topg", top_g=1), session_events("B", NORMAL_B[:3] + ["get_free_slots"]))
    # the second get_free_slots is seen, but not the single most probable next symbol after get_free_slots
    assert any(o.event["data"]["rule"] == "topg" for o in calls(out))


def test_at_most_one_alert_per_call(model_b):
    out = feed(make_pipeline(model_b), session_events("B", ["save_draft"] * 5))
    indices = [o.event["data"]["call_index"] for o in calls(out)]
    assert len(indices) == len(set(indices))


# -- ordering and closing (Sec. 4.2, 4.4) ----------------------------------------
def test_shuffled_delivery_gives_same_result(model_b):
    events = session_events("B", ["find_contact", "save_draft", "get_free_slots", "save_draft"],
                            session_id="s1")
    clean = [strip_wall_clock(o.event) for o in feed(make_pipeline(model_b), events)]
    shuffled = events[:]
    random.Random(3).shuffle(shuffled)
    other = [strip_wall_clock(o.event) for o in feed(make_pipeline(model_b), shuffled)]
    assert sorted(map(str, clean)) == sorted(map(str, other))


def test_ended_with_earlier_timestamp_but_higher_sequence_waits_for_last_call(model_a):
    events = v2_session(["inspect_dataset", "finalize_statistics"], session_id="a1")
    assert events[-1]["occurred_at"] < events[-2]["occurred_at"]  # as in Agent A's recorded file
    clean = feed(make_pipeline(model_a), events, agent="A")
    # deliver session.ended before the last result event: the session must wait for it
    reordered = events[:-2] + [events[-1], events[-2]]
    pipeline = make_pipeline(model_a)
    early = feed(pipeline, reordered[:-1], agent="A", flush=False)
    assert not [o for o in early if o.kind == "session"], "closed before the last call arrived"
    rest = feed(pipeline, reordered[-1:], agent="A", start=1.0, flush=False)
    assert [strip_wall_clock(o.event) for o in rest] == [strip_wall_clock(o.event) for o in clean]


def test_missing_sequence_closes_incomplete_after_timeout(model_b):
    events = session_events("B", NORMAL_B)
    del events[3]  # a call is lost; session.ended arrives
    pipeline = make_pipeline(model_b, reorder_timeout_s=5)
    out = feed(pipeline, events, flush=False)
    assert not [o for o in out if o.kind == "session"]
    out = pipeline.tick(100.0)
    data = session(out)
    assert data["complete"] is False
    assert pipeline.metrics.get("B", "gap") >= 1


def test_lost_call_does_not_cause_false_alert(model_b):
    events = session_events("B", NORMAL_B)
    del events[3]
    pipeline = make_pipeline(model_b, reorder_timeout_s=5)
    out = feed(pipeline, events, flush=False) + pipeline.tick(100.0)
    assert calls(out) == []


def test_session_without_start_skips_first_k_transitions():
    model = make_model("B", orders=(1, 2))
    events = session_events("B", ["find_contact", "save_draft", "find_contact"])[1:]  # no session.started
    out = feed(make_pipeline(model), events)  # order 2 for B
    data = session(out)
    assert data["complete"] is False
    assert all(o.event["data"]["call_index"] not in (1, 2) for o in calls(out))


def test_event_for_closed_session_is_late(model_b):
    events = session_events("B", NORMAL_B)
    pipeline = make_pipeline(model_b)
    feed(pipeline, events, flush=False)
    feed(pipeline, [dict(events[2], event_id="new-id")], flush=False)
    assert pipeline.metrics.get("B", "late_event") == 1


def test_duplicates_are_ignored(model_b):
    events = session_events("B", NORMAL_B, session_id="d1")
    clean = [strip_wall_clock(o.event) for o in feed(make_pipeline(model_b), events)]
    doubled = [e for ev in events for e in (ev, ev)]
    assert [strip_wall_clock(o.event) for o in feed(make_pipeline(model_b), doubled)] == clean


def test_idle_session_is_closed_incomplete(model_b):
    pipeline = make_pipeline(model_b, idle_timeout_s=60)
    feed(pipeline, session_events("B", NORMAL_B)[:-1], flush=False)
    out = pipeline.tick(1000.0)
    assert session(out)["complete"] is False
    assert not any(o.event["data"].get("call_index") == "END" for o in calls(out))


# -- agent policies (Secs. 5.2, 6) ----------------------------------------------------
def test_empty_session_policies(model_a, model_b):
    empty_a = session_events("A", [])
    out = feed(make_pipeline(model_a, call_alerts={"A": True, "B": True}), empty_a, agent="A")
    assert any(o.event["data"]["call_index"] == "END" for o in calls(out))  # alert

    out = feed(make_pipeline(model_b), session_events("B", []))  # tag (default for B)
    assert calls(out) == []
    data = session(out)
    assert data["empty_session"] is True and data["is_anomaly"] is False

    out = feed(make_pipeline(model_b, empty_session={"A": "alert", "B": "drop"}), session_events("B", []))
    assert out == []


def test_agent_a_call_alerts_are_computed_but_not_published(model_a):
    out = feed(make_pipeline(model_a), session_events("A", ["finalize_statistics", "inspect_dataset"]), agent="A")
    alerts = calls(out)
    assert alerts and all(not o.publish for o in alerts)
    assert all(o.publish for o in out if o.kind == "session")


def test_session_score_for_agent_a_is_seq_without_argument_fields(model_a):
    out = feed(make_pipeline(model_a), session_events("A", ["inspect_dataset", "finalize_statistics"]), agent="A")
    data = session(out)
    assert data["score_kind"] == "seq"
    assert data["arg_score"] is None and data["worst_arg"] is None
