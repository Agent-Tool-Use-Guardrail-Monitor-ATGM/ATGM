from spacesaving.service import SpaceSavingService


class FakeSink:
    def __init__(self):
        self.messages = []

    def send(self, topic, key, value):
        self.messages.append((topic, key, value))


def tool_call(event_id, tool_name="web_search", arguments=None):
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": "tool_call.completed",
        "occurred_at": "2026-11-19T10:00:00+00:00",
        "run_id": "run-1",
        "session_id": "session-1",
        "sequence": 1,
        "request_id": None,
        "data": {
            "agent_id": "A",
            "tool_name": tool_name,
            "arguments": arguments or {},
        },
    }


def review_label(event_id, verdict, violation_type=None):
    return {
        "schema_version": "1.0",
        "event_id": f"label-{event_id}",
        "event_type": "review.labelled",
        "occurred_at": "2026-11-19T10:00:10+00:00",
        "run_id": "run-1",
        "session_id": "session-1",
        "data": {
            "scored_event_id": event_id,
            "agent_id": "A",
            "verdict": verdict,
            "violation_type": violation_type,
        },
    }


def test_tool_call_creates_summary():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    service.handle(
        tool_call("call-1", "web_search", {"query": "weather"}),
        "tool-calls.A",
    )

    assert len(sink.messages) == 1

    topic, key, message = sink.messages[0]

    assert topic == "stats"
    assert key == "A"
    assert message["event_type"] == "counts.summary"
    assert message["data"]["detector"] == "spacesaving"

    items = message["data"]["top"]
    assert {"item": "tool:web_search", "count": 1} in items


def test_repeated_tool_calls_increase_count():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    service.handle(tool_call("call-1"), "tool-calls.A")
    service.handle(tool_call("call-2"), "tool-calls.A")

    sketch = service.sketches[("A", "tool", service.current_window)]

    assert sketch.estimate("tool:web_search") == 2


def test_false_alarm_withdraws_only_matching_call():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    service.handle(tool_call("call-1"), "tool-calls.A")
    service.handle(tool_call("call-2"), "tool-calls.A")

    service.handle(
        review_label("call-1", "false_alarm"),
        "labels",
    )

    sketch = service.sketches[("A", "tool", service.current_window)]

    assert sketch.estimate("tool:web_search") == 1


def test_attack_label_counts_violation_type():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    service.handle(tool_call("call-1"), "tool-calls.A")

    service.handle(
        review_label("call-1", "attack", "unsafe_args"),
        "labels",
    )

    sketch = service.sketches[("A", "violation", service.current_window)]

    assert sketch.estimate("violation:unsafe_args") == 1


def test_duplicate_tool_call_is_not_counted_twice():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    event = tool_call("call-1")

    service.handle(event, "tool-calls.A")
    service.handle(event, "tool-calls.A")

    sketch = service.sketches[("A", "tool", service.current_window)]

    assert sketch.estimate("tool:web_search") == 1


def test_duplicate_review_label_is_not_applied_twice():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    service.handle(tool_call("call-1"), "tool-calls.A")

    label = review_label("call-1", "false_alarm")

    service.handle(label, "labels")
    service.handle(label, "labels")

    sketch = service.sketches[("A", "tool", service.current_window)]

    assert sketch.estimate("tool:web_search") == 0


def test_different_agents_have_separate_counters():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    event_a = tool_call("call-a")
    event_b = tool_call("call-b")
    event_b["data"]["agent_id"] = "B"

    service.handle(event_a, "tool-calls.A")
    service.handle(event_b, "tool-calls.B")

    window = service.current_window

    assert service.sketches[("A", "tool", window)].estimate("tool:web_search") == 1
    assert service.sketches[("B", "tool", window)].estimate("tool:web_search") == 1


def test_argument_patterns_are_counted_separately():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    service.handle(
        tool_call("call-1", arguments={"query": "weather"}),
        "tool-calls.A",
    )
    service.handle(
        tool_call("call-2", arguments={"query": "news"}),
        "tool-calls.A",
    )

    sketch = service.sketches[("A", "arguments", service.current_window)]

    assert sketch.estimate('args:{"query":"weather"}') == 1
    assert sketch.estimate('args:{"query":"news"}') == 1

def test_zero_capacity_is_rejected():
    sink = FakeSink()

    try:
        SpaceSavingService(sink, capacity=0)
        assert False, "Expected ValueError for zero capacity"
    except ValueError:
        pass


def test_attack_without_matching_call_is_not_counted():
    sink = FakeSink()
    service = SpaceSavingService(sink)

    service.handle(tool_call("call-1"), "tool-calls.A")

    window = service.current_window

    service.handle(
        review_label("unknown-call", "attack", "unsafe_args"),
        "labels",
    )

    assert ("A", "violation", window) not in service.sketches

