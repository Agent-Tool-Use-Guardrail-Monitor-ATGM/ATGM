from b3_markov.adapters import model_store
from b3_markov.scorer import Scorer
from helpers import FULL, SHORT, events
from test_model_store import SESSIONS, TABLE


def run(scorer, ev):
    return [r for r in map(scorer.handle, ev) if r]


def test_scores_when_model_is_loaded_from_disk(tmp_path):
    model_store.save(TABLE, {}, tmp_path, "v1_additive")
    (scored,) = run(Scorer(tmp_path), events("a", FULL))
    data = scored["data"]
    assert scored["event_type"] == "anomaly.scored" and data["detector"] == "b3_markov"
    assert data["model_version"] == "v1_additive" and data["threshold"] == 1.5 and data["n_calls"] == 6
    assert data["score"] > 0 and data["n_unseen"] == 0


def test_without_model_nothing_is_scored(tmp_path):
    assert run(Scorer(tmp_path), events("a", FULL)) == []


def test_model_update_with_embedded_table_is_used(tmp_path):
    scorer = Scorer(tmp_path)
    scorer.on_model_update({"data": {"model": "b3-markov-chain", "version": "v2_additive", "transition_table": TABLE}})
    (scored,) = run(scorer, events("a", SHORT))
    assert scored["data"]["model_version"] == "v2_additive"


def test_update_for_other_model_or_kind_is_ignored(tmp_path):
    scorer = Scorer(tmp_path, kind="floor")
    scorer.on_model_update({"data": {"model": "b1-binary", "version": "x_floor", "transition_table": TABLE}})
    scorer.on_model_update({"data": {"model": "b3-markov-chain", "version": "x_additive", "transition_table": TABLE}})
    assert scorer.model is None
