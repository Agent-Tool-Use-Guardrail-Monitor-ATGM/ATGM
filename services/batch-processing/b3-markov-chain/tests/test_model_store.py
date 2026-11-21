import json

from b3_markov.adapters import model_store
from b3_markov.domain.scoring import Params
from b3_markov.domain.training import fit, to_table
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
    assert model_store.latest(tmp_path, "additive") == folder and model_store.latest(tmp_path, "floor") is None


def test_announce_publishes_one_message_keyed_by_model_name(tmp_path):
    folder = model_store.save(TABLE, {"m": 1}, tmp_path, "v1_additive")
    producer = FakeProducer()
    model_store.announce(folder, {"m": 1}, TABLE, "unused", producer=producer)
    (topic, key, event), = producer.sent
    assert topic == "model-updates" and key == "b3-markov-chain" and event["event_type"] == "model.trained"
    assert event["data"]["model"] == "b3-markov-chain" and event["data"]["transition_table"] == TABLE
