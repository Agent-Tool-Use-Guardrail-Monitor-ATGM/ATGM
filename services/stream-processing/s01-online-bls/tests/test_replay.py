import json

import pytest
from online_bls.main import consume, publish_pending
from online_bls.service import ClassifierService


def call(session, index, agent="A", tool="inspect", failed=False):
    return {
        "event_type": "tool_call.failed" if failed else "tool_call.completed",
        "event_id": f"{agent}-{session}-{index}",
        "session_id": session,
        "run_id": f"run-{session}",
        "sequence": index + 1,
        "data": {"agent_id": agent, "tool_name": tool, "session_call_index": index},
    }


def end(session, agent="A"):
    return {"event_type": "session.ended", "session_id": session, "data": {"agent_id": agent}}


def review(session, verdict, agent="A", detector="aci"):
    return {
        "event_type": "review.labelled",
        "session_id": session,
        "data": {"agent_id": agent, "detector": detector, "verdict": verdict, "scored_event_id": "reviewed-by-aci"},
    }


class Replay:
    def __init__(self, *records):
        self.records = iter(records)
        self.commits = []

    def poll(self, _):
        return next(self.records)

    def commit(self, *, message, asynchronous):
        assert not asynchronous
        self.commits.append(message)


class Record:
    def __init__(self, topic, event):
        self.name = topic
        self.event = event

    def error(self):
        return None

    def value(self):
        return json.dumps(self.event)

    def topic(self):
        return self.name


class Producer:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def produce(self, topic, *, key, value, on_delivery):
        assert topic == "scores"
        event = json.loads(value)
        assert key == event["data"]["agent_id"]
        self.events.append(event)
        on_delivery("delivery failed" if self.fail else None, None)

    def flush(self, _):
        return 0


def replay(service, producer, *records):
    consumer = Replay(*(Record(topic, event) for topic, event in records))
    with pytest.raises(StopIteration):
        consume(service, consumer, producer)
    assert len(consumer.commits) == len(records)


def test_kafka_replay_scores_before_label_and_trains_final_prefix_once(tmp_path):
    path = tmp_path / "bls.db"
    service, producer = ClassifierService(path), Producer()
    replay(service, producer,
           ("tool-calls.A", call("normal", 1)),
           ("tool-calls.A", call("normal", 2)),
           ("tool-calls.A", end("normal")))
    initial = [event["data"] for event in producer.events]
    assert [score["session_call_index"] for score in initial] == [1, 2]
    assert all(score["score"] == 0.5 and not score["ready"] for score in initial)
    assert service.models["A"].class_counts == (0, 0)
    replay(service, producer,
           ("labels", review("normal", "false_alarm")),
           ("labels", review("normal", "false_alarm", detector="dspot")),
           ("tool-calls.A", call("attack", 1, tool="other", failed=True)),
           ("labels", review("attack", "attack")))
    assert service.models["A"].class_counts == (1, 0)
    replay(service, producer,
           ("tool-calls.A", call("attack", 2, tool="other", failed=True)),
           ("tool-calls.A", end("attack")),
           ("tool-calls.A", end("attack")),
           ("tool-calls.A", call("unreviewed", 1)),
           ("tool-calls.A", end("unreviewed")))
    assert producer.events[-2]["data"]["ready"] is False
    assert producer.events[-1]["data"]["ready"] is True
    assert service.models["A"].class_counts == (1, 1)
    assert service._load_session("A", "unreviewed").error is None
    prediction = producer.events[-1]["data"]["predicted_class"]
    service.close()

    restored = ClassifierService(path)
    replay(restored, producer,
           ("tool-calls.A", call("unreviewed", 1)),
           ("labels", review("unreviewed", "attack" if prediction == 0 else "false_alarm")),
           ("labels", review("normal", "false_alarm")),
           ("tool-calls.B", call("normal", 1, agent="B")))
    assert sum(restored.models["A"].class_counts) == 3
    assert restored._load_session("A", "unreviewed").error == 1
    assert restored.models["B"].class_counts == (0, 0)
    assert len(producer.events) == 6
    restored.close()


def test_broker_delivery_failure_keeps_score_for_restart(tmp_path):
    path = tmp_path / "bls.db"
    service = ClassifierService(path)
    event = call("one", 1)
    producer = Producer(fail=True)
    consumer = Replay(Record("tool-calls.A", event))
    with pytest.raises(RuntimeError, match="score delivery failed"):
        consume(service, consumer, producer)
    assert consumer.commits == []
    service.close()

    restored, successful = ClassifierService(path), Producer()
    publish_pending(restored, successful)
    replay(restored, successful, ("tool-calls.A", event))
    assert successful.events == producer.events
    assert restored.pending_scores() == []
    restored.close()


def test_parallel_tool_calls_score_in_index_order_across_restart(tmp_path):
    path = tmp_path / "bls.db"
    producer = Producer()
    service = ClassifierService(path)
    topic = "tool-calls.B"
    third = call("parallel", 3, "B", tool="check")
    replay(service, producer,
           (topic, call("parallel", 1, "B")),
           (topic, third),
           (topic, third))
    assert [event["data"]["session_call_index"] for event in producer.events] == [1]
    service.close()

    restored = ClassifierService(path)
    replay(restored, producer,
           (topic, call("parallel", 2, "B", tool="draft", failed=True)),
           (topic, end("parallel", "B")),
           ("labels", review("parallel", "false_alarm", "B")))
    assert [event["data"]["session_call_index"] for event in producer.events] == [1, 2, 3]
    checkpoint = restored._load_session("B", "parallel")
    assert (checkpoint.prefix.length, checkpoint.prefix.failures) == (3, 1)
    assert restored.models["B"].class_counts == (1, 0)
    restored.close()


def test_session_end_scores_available_calls_when_an_index_is_missing(tmp_path):
    service, producer = ClassifierService(tmp_path / "bls.db"), Producer()
    topic = "tool-calls.B"
    replay(service, producer,
           (topic, call("gap", 2, "B")),
           (topic, call("gap", 3, "B")),
           ("labels", review("gap", "attack", "B")),
           (topic, end("gap", "B")))
    assert [event["data"]["session_call_index"] for event in producer.events] == [2, 3]
    assert service.models["B"].class_counts == (0, 1)
    service.close()
