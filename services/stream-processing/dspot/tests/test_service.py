import logging

import numpy as np
import pytest

from dspot.adapters import events
from dspot.domain.monitor import AlarmMonitor
from dspot.service import DSPOTService


class FakeSink:
    def __init__(self):
        self.sent = []

    def send(self, topic, key, value):
        self.sent.append((topic, key, value))


def scored(ref, value, agent="A", detector="iforest", **extra):
    return {"schema_version": "1.0", "event_id": f"id-{ref}", "event_type": events.SCORED,
            "occurred_at": "2026-11-01T12:00:00+00:00", "run_id": "run-1", "session_id": "s-1",
            "sequence": 3, "request_id": None,
            "data": {"scored_event_id": ref, "agent_id": agent, "detector": detector,
                     "model_version": "v2", "score": value, **extra}}


def labelled(ref, verdict, detector="iforest"):
    return {"schema_version": "1.0", "event_id": f"label-{ref}", "event_type": events.LABELLED,
            "data": {"scored_event_id": ref, "detector": detector, "verdict": verdict}}


@pytest.fixture
def service():
    svc = DSPOTService(AlarmMonitor(q=1e-3, warmup=3_000), FakeSink())
    for i, v in enumerate(np.random.default_rng(0).normal(size=3_000)):
        svc.handle(scored(f"w{i}", float(v)))
    return svc


def test_alarm_is_published_on_both_topics_in_the_envelope_format(service):
    service.handle(scored("e1", 0.1))
    assert service.sink.sent == []
    service.handle(scored("e2", 9.0))
    assert [(t, k) for t, k, _ in service.sink.sent] == [("alerts", "A"), ("review-queue", "A")]
    event = service.sink.sent[0][2]
    assert event["schema_version"] == "1.0" and event["event_type"] == "alarm.raised"
    assert (event["run_id"], event["session_id"], event["sequence"]) == ("run-1", "s-1", 3)
    d = event["data"]
    assert (d["scored_event_id"], d["agent_id"], d["detector"], d["model_version"]) == ("e2", "A", "iforest", "v2")
    assert d["score"] == 9.0 and d["threshold"] < 9.0 and d["q"] == 1e-3


def test_false_alarm_label_is_learned_and_attack_label_is_not(service):
    dspot = service.monitor.detectors[("A", "iforest")]
    service.handle(scored("e1", 9.0))
    service.handle(scored("e2", 11.0))
    peaks = dspot.spot.n_peaks
    service.handle(labelled("e2", "attack"))
    assert dspot.spot.n_peaks == peaks
    service.handle(labelled("e1", "false_alarm"))
    assert dspot.spot.n_peaks == peaks + 1


@pytest.mark.parametrize("bad", [
    "not a dict",
    {"event_type": "anomaly.scored", "schema_version": "2.0", "data": {}},
    {"event_type": "anomaly.scored", "schema_version": "1.0"},
    scored("e", "high"),                          # score is not a number
    scored("e", float("nan")),
    {**scored("e", 1.0), "data": {"score": 1.0}},  # missing fields
    labelled("e", "maybe"),
])
def test_bad_messages_are_skipped_with_a_warning(service, bad, caplog):
    with caplog.at_level(logging.WARNING, logger="dspot"):
        service.handle(bad)
    assert service.sink.sent == []
    if isinstance(bad, dict):
        assert "skipped message" in caplog.text


def test_other_event_types_are_ignored(service):
    service.handle({"schema_version": "1.0", "event_type": "tool_call.completed", "data": {}})
    assert service.sink.sent == []
