import json

from b3_markov.adapters import model_store
from b3_markov.domain.scoring import Params
from b3_markov.domain.training import fit, fit_detector, to_table
from helpers import FULL, SHORT, sess

SESSIONS = [sess(FULL, "1"), sess(SHORT, "2")]
TABLE = to_table(fit(SESSIONS, [1], Params()), SESSIONS, {"primary_order": 1, "threshold": {"1": 1.5}},
                 label_filter="category == normal", seed=0)


class FakeProducer:
    def __init__(self):
        self.sent = []

    def produce(self, topic, key, value):
        self.sent.append((topic, key, json.loads(value)))

    def flush(self, timeout):
        pass


def test_save_and_load(tmp_path):
    folder = model_store.save(TABLE, {"model": "additive"}, tmp_path, "2026-01-01T00-00-00_additive")
    assert model_store.load(folder) == TABLE
    assert json.loads((folder / "metrics.json").read_text())["version"] == folder.name
    assert folder.parent.name == "B" and folder.parent.parent.name == "b3-markov-chain"
    assert model_store.latest(tmp_path, "B", "additive") == folder and model_store.latest(tmp_path, "B", "floor") is None
    assert model_store.latest(tmp_path, "A") is None


def test_announce_publishes_one_message_keyed_by_model_name_and_agent(tmp_path):
    folder = model_store.save(TABLE, {"m": 1}, tmp_path, "v1_additive", "A")
    producer = FakeProducer()
    model_store.announce(folder, {"m": 1}, TABLE, "unused", "A", producer=producer)
    (topic, key, event), = producer.sent
    assert topic == "model-updates" and key == "b3-markov-chain.A" and event["event_type"] == "model.trained"
    assert event["data"]["model"] == "b3-markov-chain" and event["data"]["agent"] == "A"
    assert event["data"]["transition_table"] == TABLE


def test_models_of_a_and_b_are_written_to_separate_folders(tmp_path):
    a = model_store.save(TABLE, {}, tmp_path, "v1_additive", "A")
    b = model_store.save(TABLE, {}, tmp_path, "v1_additive", "B")
    assert a != b and model_store.latest(tmp_path, "A") == a and model_store.latest(tmp_path, "B") == b
    assert json.loads((a / "metrics.json").read_text())["agent"] == "A"


def test_announced_table_carries_call_threshold_and_message_metrics_drop_per_session_lists(tmp_path):
    table = to_table(fit_detector(SESSIONS, [1], Params()), SESSIONS,
                     {"threshold": {"1": 1.5}, "call_threshold": {"1": -6.0}}, label_filter="x", seed=0)
    folder = model_store.save(table, {}, tmp_path, "v1_additive")
    event = model_store.announce_event(folder, {"r": {"call_level": {"heldout_min_log_p": [1, 2], "x": 1}}}, table)
    assert event["data"]["transition_table"]["calibration"]["call_threshold"] == {"1": -6.0}
    assert event["data"]["metrics"] == {"r": {"call_level": {"x": 1}}}


def test_v02_table_without_call_threshold_loads():
    from b3_markov.domain.training import from_table
    table = to_table(fit_detector(SESSIONS, [1], Params()), SESSIONS, {"threshold": {"1": 1.5}}, label_filter="x", seed=0)
    table["spec_version"] = "0.2"
    assert from_table(table).score(1, ["find_contact"])["n_calls"] == 1


def test_save_fold_tables_writes_one_file_per_fold(tmp_path):
    folder = model_store.save(TABLE, {}, tmp_path, "v1_additive")
    paths = model_store.save_fold_tables(folder, [TABLE, TABLE, TABLE])
    assert [p.name for p in paths] == ["fold_0.json", "fold_1.json", "fold_2.json"]
