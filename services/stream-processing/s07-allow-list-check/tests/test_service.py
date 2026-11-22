import json
from types import SimpleNamespace

from allow_list import consumer
from allow_list.consumer import ToolsetReader, run
from allow_list.detector import AllowListDetector
from allow_list.service import AllowListService

B_TOOLS = ["find_contact", "get_current_datetime", "get_free_slots", "save_draft", "tone_checker",
           "sensitive_content_scan"]
TEXT = "Subject: Hello\n\nHi"


def service():
    return AllowListService(AllowListDetector(), "toolset-config", "flags")


def raw(event):
    return json.dumps(event).encode("utf-8")


def tool_event(tool, args=None, session="s1", event_id="e1", seq=2):
    return {"schema_version": "1.0", "event_id": event_id, "event_type": "tool_call.completed",
            "occurred_at": "2026-11-15T12:00:00+00:00", "run_id": "r", "session_id": session, "sequence": seq,
            "data": {"agent_id": "B", "tool_name": tool, "arguments": args or {}, "success": True}}


def started(session="s1"):
    return {"event_type": "session.started", "session_id": session, "data": {"agent_id": "B"}}


# --- routing ---
def test_toolset_config_then_tool_calls_end_to_end():
    s = service()
    assert s.handle("toolset-config", b"B", raw({"agent_id": "B", "allowed_tools": B_TOOLS[:-1]})) == []
    assert s.handle("tool-calls.B", b"s1", raw(started())) == []
    (topic, key, flag), = s.handle("tool-calls.B", b"s1", raw(tool_event("sensitive_content_scan", {"text": TEXT})))
    assert (topic, key) == ("flags", "B")
    assert flag["data"]["rule"] == "tool_not_allowed" and flag["data"]["flagged_event_id"] == "e1"
    assert flag["data"]["detector"] == "allow_list" and flag["data"]["severity"] == "high"


def test_one_flag_event_per_broken_rule():
    s = service()
    s.handle("tool-calls.B", None, raw(started()))
    out = s.handle("tool-calls.B", None, raw(tool_event("save_draft", {"to": "x@evil.example", "subject": "s", "body": "b"})))
    assert sorted(f["data"]["rule"] for _, _, f in out) == ["precondition_missing", "recipient_not_allowed"]
    assert {f["sequence"] for _, _, f in out} == {2}


def test_session_end_and_other_events_publish_nothing():
    s = service()
    assert s.handle("tool-calls.B", None, raw({"event_type": "session.ended", "session_id": "s1"})) == []
    assert s.handle("tool-calls.B", None, raw({"event_type": "model_call.completed", "data": {}})) == []


def test_key_of_the_config_message_names_the_agent():
    s = service()
    s.handle("toolset-config", b"A", raw({"allowed_tools": ["inspect_dataset"]}))
    assert s.detector.toolsets == {"A": {"inspect_dataset"}}


def test_agent_comes_from_the_topic_when_the_event_has_none():
    s = service()
    event = tool_event("find_contact", {"name": "*"})
    del event["data"]["agent_id"]
    (_, key, flag), = s.handle("tool-calls.B", None, raw(event))
    assert key == "B" and flag["data"]["agent_id"] == "B"


def test_run_events_shape_is_judged_at_the_request_only():
    s = service()
    s.handle("toolset-config", b"A", raw({"agent_id": "A", "allowed_tools": ["aggregate_statistics"]}))
    s.handle("tool-calls.A", b"s1", raw(started()))
    request = {"schema_version": "1.0", "event_id": "r1", "event_type": "tool_call.requested", "run_id": "r",
               "session_id": "s1", "sequence": 2, "occurred_at": "2026-11-14T21:52:02.109813Z",
               "data": {"kind": "numerical", "name": "export_dataset", "tool_call_id": "c1",
                        "features": {"column_count": 0, "dataset_selection": "selected"},
                        "arguments_sha256": "ab", "session_call_index": 1}}
    ((topic, key, flag),) = s.handle("tool-calls.A", b"s1", raw(request))
    assert (topic, key) == ("flags", "A")                                  # agent from the topic: no agent_id in data
    assert (flag["data"]["rule"], flag["data"]["tool_name"], flag["data"]["flagged_event_id"]) == (
        "tool_not_allowed", "export_dataset", "r1")
    done = {"event_type": "tool_call.failed", "event_id": "d1", "session_id": "s1", "sequence": 4,
            "data": {"status": "failed", "reason": "unknown_tool", "tool_call_id": "c1"}}
    assert s.handle("tool-calls.A", b"s1", raw(done)) == []                # the outcome adds no second flag


def test_a_request_without_a_name_is_flagged_for_the_agent_of_its_topic():
    s = service()
    s.handle("toolset-config", b"A", raw({"agent_id": "A", "allowed_tools": ["aggregate_statistics"]}))
    s.handle("tool-calls.A", b"s1", raw(started()))
    event = {"event_type": "tool_call.requested", "event_id": "r1", "session_id": "s1", "sequence": 2,
             "data": {"kind": "unknown", "features": {"column_count": 0}, "tool_call_id": "c1"}}
    ((_, key, flag),) = s.handle("tool-calls.A", b"s1", raw(event))
    assert key == "A" and flag["data"]["tool_name"] is None and flag["data"]["rule"] == "tool_not_allowed"


# --- Kafka loop with fakes ---
def msg(topic, value, key=None, offset=0, error=None, partition=0):
    return SimpleNamespace(topic=lambda: topic, key=lambda: key, value=lambda: value, offset=lambda: offset,
                           partition=lambda: partition, error=lambda: error)


class FakeConsumer:
    def __init__(self, messages, partitions=None):
        self.messages, self.committed, self.assigned = list(messages), [], None
        self._partitions = partitions

    def poll(self, timeout=0):
        return self.messages.pop(0) if self.messages else None

    def commit(self, message=None, asynchronous=False):
        self.committed.append(message)

    def list_topics(self, topic, timeout=None):
        meta = None if self._partitions is None else SimpleNamespace(partitions={p: None for p in self._partitions},
                                                                     error=None)
        return SimpleNamespace(topics={topic: meta} if meta else {})

    def assign(self, partitions):
        self.assigned = partitions


class FakeProducer:
    def __init__(self):
        self.sent = []

    def produce(self, topic, key=None, value=None, on_delivery=None):
        self.sent.append((topic, key, json.loads(value)))

    def poll(self, timeout=0):
        pass

    def flush(self, timeout=0):
        pass


EOF_ERR = "EOF"


def is_eof(error):
    return error == EOF_ERR


def make(config_messages, call_messages, partitions=(0,)):
    svc = service()
    reader = ToolsetReader(FakeConsumer(config_messages, partitions), svc, is_eof, lambda t, p: (t, p))
    calls = FakeConsumer(call_messages)
    return svc, reader, calls, FakeProducer()


def test_run_loads_toolsets_first_then_flags_and_commits_every_message():
    cfg = [msg("toolset-config", raw({"agent_id": "B", "allowed_tools": ["find_contact"]}), b"B", 0),
           msg("toolset-config", None, error=EOF_ERR)]
    calls = [msg("tool-calls.B", raw(started()), offset=0),
             msg("tool-calls.B", raw(tool_event("find_contact", {"name": "Anna"})), offset=1),      # fine
             msg("tool-calls.B", raw(tool_event("send_email", {}, event_id="e2", seq=3)), offset=2),  # not allowed
             msg("tool-calls.B", b"{not json", offset=3),                                           # skipped
             msg("tool-calls.A", raw({"event_type": "tool_call.completed", "event_id": "e9", "session_id": "a1",
                                      "data": {"agent_id": "A", "tool_name": "inspect_dataset",
                                               "arguments": {"dataset_id": "../x"}, "success": True}}), offset=4)]
    svc, reader, consumer_, producer = make(cfg, calls)
    n = run(consumer_, reader, producer, svc, is_eof, keep_running=lambda: bool(consumer_.messages))
    assert reader.consumer.assigned == [("toolset-config", 0)]
    assert [(t, k, e["data"]["rule"]) for t, k, e in producer.sent] == [
        ("flags", "B", "tool_not_allowed"), ("flags", "A", "dataset_id_not_allowed")]
    assert n == 2 and len(consumer_.committed) == 5                                       # bad message committed too


def test_a_toolset_change_while_running_applies_to_the_next_calls():
    cfg = [msg("toolset-config", None, error=EOF_ERR)]
    svc, reader, calls, producer = make(cfg, [])
    calls.messages = [msg("tool-calls.B", raw(started())),
                      msg("tool-calls.B", raw(tool_event("save_draft", {}, event_id="e1")))]

    def keep_running():
        if len(calls.messages) == 1:                     # revoke save_draft between the two messages
            reader.consumer.messages.append(msg("toolset-config", raw(
                {"agent_id": "B", "allowed_tools": [t for t in B_TOOLS if t != "save_draft"]}), b"B"))
        return bool(calls.messages)

    run(calls, reader, producer, svc, is_eof, keep_running)
    assert "tool_not_allowed" in [e["data"]["rule"] for _, _, e in producer.sent]


def test_missing_toolset_topic_does_not_stop_the_checks(caplog):
    svc, reader, calls, producer = make([], [msg("tool-calls.B", raw(started())),
                                             msg("tool-calls.B", raw(tool_event("find_contact", {"name": "*"})))],
                                        partitions=None)
    run(calls, reader, producer, svc, is_eof, keep_running=lambda: bool(calls.messages))
    assert [e["data"]["rule"] for _, _, e in producer.sent] == ["contact_name_not_allowed"]
    assert reader.partitions == 0


def test_bad_toolset_message_is_ignored():
    cfg = [msg("toolset-config", b"[1]", b"B"), msg("toolset-config", raw({"agent_id": "B", "allowed_tools": 5}), b"B"),
           msg("toolset-config", raw({"agent_id": "B", "allowed_tools": ["find_contact"]}), b"B"),
           msg("toolset-config", None, error=EOF_ERR)]
    svc, reader, calls, producer = make(cfg, [])
    reader.connect(2)
    assert svc.detector.toolsets == {"B": {"find_contact"}}
