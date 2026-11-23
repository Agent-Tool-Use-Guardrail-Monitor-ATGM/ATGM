"""The anomaly.scored event publishes to the scores topic"""
import uuid
from datetime import datetime, timezone

from b1_classifier.domain.sessions import FinishedSession

DETECTOR = "b1_classifier"


def score_event(session: FinishedSession, score: float, model_version: str, run_id: str | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "event_type": "anomaly.scored",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "session_id": session.session_id,
        "data": {
            "scored_event_id": session.ended_event_id,   # the session.ended event
            "agent_id": session.agent_id,
            "detector": DETECTOR,
            "model_version": model_version,
            "score": score,
            "n_calls": len(session.calls),
        },
    }