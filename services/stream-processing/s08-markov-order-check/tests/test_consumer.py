import json

from conftest import model_message

from markov_order_check.config import Settings
from markov_order_check.consumer import run_loop
from markov_order_check.demo import DEMO_SESSIONS, DEMO_VOCABULARY, build_table, session_events
from markov_order_check.detector import MarkovOrderPipeline


class FakeError:
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code


class FakeKafkaError:
    _PARTITION_EOF = -191


class FakeMessage:
    def __init__(self, topic, key, value, offset=0, error=None):
        self._topic, self._key, self._value, self._offset, self._error = topic, key, value, offset, error

    def topic(self):
        return self._topic

    def key(self):
        return self._key

    def value(self):
        return self._value

    def offset(self):
        return self._offset

    def error(self):
        return self._error


class FakeConsumer:
    def __init__(self, messages, log, name):
        self.messages, self.log, self.name = list(messages), log, name
        self.subscribed, self.commits = None, []

    def subscribe(self, topics, **_):
        self.log.append((self.name, "subscribe"))
        self.subscribed = topics

    def poll(self, timeout):
        self.log.append((self.name, "poll"))
        return self.messages.pop(0) if self.messages else None

    def commit(self, message, asynchronous):
        self.log.append((self.name, "commit", message.offset()))
        self.commits.append(message.offset())


class FakeProducer:
    def __init__(self, log):
        self.log, self.produced = log, []

    def produce(self, topic, key, value):
        self.produced.append((topic, key, json.loads(value)))
        self.log.append(("producer", "produce"))

    def poll(self, timeout):
        pass

    def flush(self, timeout):
        self.log.append(("producer", "flush"))


def _run(tool_messages, settings=None):
    log = []
    table = build_table(DEMO_SESSIONS["B"], vocabulary=DEMO_VOCABULARY["B"])
    models = [FakeMessage("model-updates", b"b3-markov-chain.B", json.dumps(model_message("B", table)).encode()),
              FakeMessage("model-updates", None, None, error=FakeError(FakeKafkaError._PARTITION_EOF))]
    model_consumer = FakeConsumer(models, log, "models")
    tool_consumer = FakeConsumer(tool_messages, log, "tools")
    producer = FakeProducer(log)
    pipeline = MarkovOrderPipeline(settings or Settings())
    ticks = iter(range(10_000))
    run_loop(pipeline, model_consumer=model_consumer, tool_consumer=tool_consumer, producer=producer,
             settings=settings or Settings(), kafka_error_cls=FakeKafkaError, should_run=lambda: True,
             clock=lambda: float(next(ticks)), max_iterations=len(tool_messages) + 2)
    return log, tool_consumer, producer


def _messages(tools):
    events = session_events("B", tools)
    return [FakeMessage("tool-calls.B", e["session_id"].encode(), json.dumps(e).encode(), offset=i)
            for i, e in enumerate(events)]


def test_tool_calls_are_consumed_only_after_models_are_loaded():
    log, tools, _ = _run(_messages(["find_contact", "save_draft"]))
    first_tool = next(i for i, entry in enumerate(log) if entry[0] == "tools")
    assert all(entry[0] != "tools" for entry in log[:first_tool])
    assert ("models", "poll") in log[:first_tool]
    assert tools.subscribed == ["tool-calls.A", "tool-calls.B"]


def test_commit_comes_after_flush_and_outputs_use_both_detectors():
    log, tools, producer = _run(_messages(["find_contact", "save_draft", "save_draft"]))
    assert tools.commits == list(range(5))
    for i, entry in enumerate(log):
        if entry[:2] == ("producer", "produce"):
            later = log[i:]
            flush_at = later.index(("producer", "flush"))
            commit_at = next(j for j, e in enumerate(later) if e[:2] == ("tools", "commit"))
            assert flush_at < commit_at
    assert {key for _, key, _ in producer.produced} == {"B"}
    assert {topic for topic, _, _ in producer.produced} == {"scores"}
    assert {v["data"]["detector"] for _, _, v in producer.produced} == {"markov", "markov_order"}


def test_unpublished_agent_a_alerts_never_reach_kafka():
    events = session_events("A", ["finalize_statistics", "inspect_dataset"])
    log = []
    table = build_table(DEMO_SESSIONS["A"], vocabulary=DEMO_VOCABULARY["A"], orders=(1,))
    models = [FakeMessage("model-updates", b"b3-markov-chain.A", json.dumps(model_message("A", table)).encode())]
    producer = FakeProducer(log)
    msgs = [FakeMessage("tool-calls.A", None, json.dumps(e).encode(), offset=i) for i, e in enumerate(events)]
    run_loop(MarkovOrderPipeline(), model_consumer=FakeConsumer(models, log, "models"),
             tool_consumer=FakeConsumer(msgs, log, "tools"), producer=producer, settings=Settings(),
             kafka_error_cls=FakeKafkaError, should_run=lambda: True, clock=iter(range(10_000)).__next__,
             max_iterations=len(msgs) + 2)
    assert producer.produced and {v["data"]["detector"] for _, _, v in producer.produced} == {"markov"}
