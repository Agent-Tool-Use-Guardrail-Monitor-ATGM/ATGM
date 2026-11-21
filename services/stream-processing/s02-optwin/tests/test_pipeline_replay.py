import json
from pathlib import Path

from optwin.detector import Optwin
from optwin.service import DriftService


def test_online_bls_errors_trigger_optwin_drift(monkeypatch, tmp_path):
    stages = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(stages / "s01-online-bls" / "src"))
    from online_bls.service import ClassifierService

    classifier = ClassifierService(tmp_path / "bls.db")
    detector = DriftService(tmp_path / "optwin.db", Optwin())
    try:
        for index in range(32):
            session = f"session-{index}"
            classifier.handle("tool-calls.A", {
                "event_type": "tool_call.completed", "event_id": session, "session_id": session,
                "data": {"session_call_index": 1, "tool_name": "inspect"},
            })
            score, = classifier.pending_scores()
            classifier.acknowledge_score(score["event_id"])
            classifier.handle("tool-calls.A", {
                "event_type": "session.ended", "session_id": session, "data": {},
            })

            # Warm up both output classes, then create 15 correct and 15 incorrect predictions.
            predicted = score["data"]["predicted_class"]
            label = index if index < 2 else predicted ^ int(index >= 17)
            review = {
                "event_type": "review.labelled", "session_id": session,
                "data": {"agent_id": "A", "verdict": "attack" if label else "false_alarm"},
            }
            classifier.handle("labels", review)
            classifier.handle("labels", review)
            errors = classifier.pending_scores()
            assert [event["data"]["error"] for event in errors] == (
                [] if index < 2 else [int(index >= 17)]
            )
            for error in errors:
                detector.handle(error)
                classifier.acknowledge_score(error["event_id"])
            assert len(detector.pending()) == int(index == 31)

        alert = json.loads(detector.pending()[0][1])
        assert alert["event_type"] == "drift.detected"
        assert alert["data"]["monitored"] == "online_bls_error"
        assert alert["data"]["details"]["history_error_rate"] == 0
        assert alert["data"]["details"]["recent_error_rate"] == 1
    finally:
        classifier.close()
        detector.db.close()
