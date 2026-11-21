import json
from unittest.mock import Mock

import pytest
from optwin.detector import Optwin
from optwin.main import publish_pending
from optwin.service import DriftService


def reviewed(index, error, *, agent="A", model="bls-1"):
    return {
        "event_type": "classifier.error",
        "session_id": f"session-{index}",
        "data": {"agent_id": agent, "detector": "online_bls", "model_version": model, "error": error},
    }


def test_warmup_split_and_deterioration():
    detector = Optwin()
    assert detector.split(30)[0] == 15
    assert detector.split(512)[0] > 256
    assert detector.detect("0" * 29) is None
    assert detector.detect("0" * 30) is None
    assert detector.detect("1" * 15 + "0" * 15) is None
    assert detector.detect("0" * 15 + "1" * 15)["test"] == "t"
    assert detector.detect("0" * 15 + "01" * 7 + "1")["test"] == "f"


def test_review_replay_and_restart(tmp_path):
    path = tmp_path / "optwin.db"
    service = DriftService(path, Optwin())
    for index in range(29):
        event = reviewed(index, int(index >= 15))
        service.handle(event)
        service.handle(event)
        service.handle(reviewed(index, 0, agent="B"))
    assert service.pending() == []
    service.db.close()

    service = DriftService(path, Optwin())
    service.handle(reviewed(29, 1, model="bls-2"))
    assert service.pending() == []
    trigger = reviewed(29, 1)
    service.handle(trigger)
    service.handle(trigger)
    (event_id, payload), = service.pending()
    expected = json.loads(payload)
    assert expected["data"]["agent_id"] == "A"
    assert expected["data"]["model_version"] == "bls-1"
    assert expected["data"]["monitored"] == "online_bls_error"
    assert expected["data"]["details"]["history_error_rate"] == 0
    assert expected["data"]["details"]["recent_error_rate"] == 1
    producer = Mock()
    producer.flush.return_value = 1
    with pytest.raises(RuntimeError):
        publish_pending(service, producer)
    service.db.close()

    service = DriftService(path, Optwin())
    producer.flush.return_value = 0
    producer.produce.side_effect = lambda *args, on_delivery, **kwargs: on_delivery(None, None)
    publish_pending(service, producer)
    assert json.loads(producer.produce.call_args.kwargs["value"])["event_id"] == event_id
    assert service.pending() == []
    service.handle(trigger)
    assert service.pending() == []
    service.db.close()
