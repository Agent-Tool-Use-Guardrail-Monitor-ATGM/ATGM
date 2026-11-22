import json

from conftest import feed, make_pipeline, make_model, model_message, session_events

from markov_order_check.demo import DEMO_SESSIONS, DEMO_VOCABULARY, build_table
from markov_order_check.detector import MarkovOrderPipeline


def _table(agent="B"):
    return build_table(DEMO_SESSIONS[agent], vocabulary=DEMO_VOCABULARY[agent], orders=(1, 2))


def test_models_of_a_and_b_are_kept_apart():
    p = MarkovOrderPipeline()
    assert p.handle_model("b3-markov-chain.A", json.dumps(model_message("A", _table("A")))).accepted
    assert p.handle_model("b3-markov-chain.B", json.dumps(model_message("B", _table("B"), version="b1"))).accepted
    assert p.registry.get("A").vocabulary != p.registry.get("B").vocabulary
    assert p.registry.get("B").version == "b1"


def test_legacy_key_is_agent_b():
    p = MarkovOrderPipeline()
    message = model_message("B", _table())
    del message["data"]["agent"]
    assert p.handle_model(b"b3-markov-chain", json.dumps(message)).agent == "B"


def test_other_models_on_the_topic_are_ignored():
    p = MarkovOrderPipeline()
    assert p.handle_model("b1-binary-classifier", json.dumps({"event_type": "model.trained", "data": {}})) is None


def test_agent_mismatch_and_invalid_table_are_rejected_old_model_stays():
    p = MarkovOrderPipeline()
    p.handle_model("b3-markov-chain.B", json.dumps(model_message("B", _table(), version="good")))
    assert not p.handle_model("b3-markov-chain.B", json.dumps(model_message("A", _table()))).accepted
    broken = _table()
    broken["vocabulary"] = ["bad>name"]
    assert not p.handle_model("b3-markov-chain.B", json.dumps(model_message("B", broken))).accepted
    bad_version = _table()
    bad_version["spec_version"] = "9.9"
    assert not p.handle_model("b3-markov-chain.B", json.dumps(model_message("B", bad_version))).accepted
    backoff_without_order0 = _table()
    backoff_without_order0["model"]["smoothing"]["method"] = "backoff"
    assert not p.handle_model("b3-markov-chain.B", json.dumps(model_message("B", backoff_without_order0))).accepted
    assert p.registry.get("B").version == "good"


def test_agent_without_model_is_not_scored():
    p = MarkovOrderPipeline()
    assert feed(p, session_events("A", ["inspect_dataset"]), agent="A") == []
    assert p.metrics.get("A", "unscored_no_model") > 0


def test_table_without_call_threshold_falls_back_to_unseen():
    table = _table()
    del table["calibration"]["call_threshold"]
    p = MarkovOrderPipeline()
    p.handle_model("b3-markov-chain.B", json.dumps(model_message("B", table)))
    out = feed(p, session_events("B", ["find_contact", "save_draft"]))
    alerts = [o for o in out if o.kind == "call"]
    assert alerts and all(o.event["data"]["rule"] == "unseen" for o in alerts)


def test_session_keeps_its_model_after_a_swap():
    old, new = make_model("B", version="old"), make_model("B", version="new")
    p = make_pipeline(old)
    events = session_events("B", ["find_contact", "get_current_datetime", "get_free_slots"])
    feed(p, events[:2], flush=False)
    p.add_model(new)  # swap while the session is in flight
    out = feed(p, events[2:], start=1.0)
    assert {o.event["data"]["model_version"] for o in out} == {"old"}
    out = feed(p, session_events("B", ["find_contact"]), start=2.0)
    assert {o.event["data"]["model_version"] for o in out} == {"new"}
