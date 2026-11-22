from kswin.service import KSWINService


class FakeSink:
    def __init__(self):
        self.events = []

    def send(self, topic, key, value):
        self.events.append({
            "topic": topic,
            "key": key,
            "value": value,
        })


def make_tool_event(index, success=True, arguments=None):
    return {
        "schema_version": "1.0",
        "event_id": f"event-{index}",
        "event_type": "tool_call.completed" if success else "tool_call.failed",
        "occurred_at": "2026-11-23T00:00:00+00:00",
        "run_id": "run-1",
        "session_id": "session-1",
        "sequence": index,
        "request_id": f"request-{index}",
        "data": {
            "agent_id": "A",
            "arguments": arguments or {},
            "success": success,
        },
    }


def make_score_event(index, score):
    return {
        "event_id": f"score-{index}",
        "event_type": "anomaly.scored",
        "data": {
            "agent_id": "A",
            "score": score,
        },
    }


def test_service_creates_separate_detectors_per_agent_and_feature():
    sink = FakeSink()
    service = KSWINService(sink)

    service.process(make_tool_event(1), "tool-calls.A")
    service.process(make_score_event(1, 0.5), "scores")

    assert ("A", "argument_length") in service.detectors
    assert ("A", "failure_rate") in service.detectors
    assert ("A", "anomaly_score") in service.detectors


def test_service_keeps_agents_separate():
    sink = FakeSink()
    service = KSWINService(sink)

    event_a = make_tool_event(1)
    event_b = make_tool_event(2)
    event_b["data"]["agent_id"] = "B"

    service.process(event_a, "tool-calls.A")
    service.process(event_b, "tool-calls.B")

    assert ("A", "argument_length") in service.detectors
    assert ("B", "argument_length") in service.detectors
    assert service.detectors[("A", "argument_length")] is not (
        service.detectors[("B", "argument_length")]
    )


def test_service_publishes_drift_event_after_distribution_change():
    sink = FakeSink()
    service = KSWINService(
        sink,
        window_size=40,
        stat_size=10,
        alpha=0.005,
        random_state=42,
    )

    for index in range(40):
        service.process(
            make_score_event(index, 0.1),
            "scores",
        )

    for index in range(40, 55):
        service.process(
            make_score_event(index, 100.0),
            "scores",
        )

    assert sink.events, "Expected at least one drift event"

    published = sink.events[0]

    assert published["topic"] == "drift"
    assert published["key"] == "A"
    assert published["value"]["event_type"] == "drift.detected"
    assert published["value"]["data"]["detector"] == "kswin"
    assert published["value"]["data"]["monitored"] == "anomaly_score"
    assert published["value"]["data"]["p_value"] < 0.005
