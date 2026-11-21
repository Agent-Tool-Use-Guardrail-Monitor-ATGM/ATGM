"""The anomaly.scored event published to the scores topic."""
import uuid
from datetime import datetime, timezone

from b3_markov.domain.sessions import FinishedSession

DETECTOR = "b3_markov"


def score_event(session: FinishedSession, result: dict, model_version: str, threshold: float | None,
                run_id: str | None = None) -> dict:
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
            "score": result["score"],                    # configured score (default joint mean NLL), higher = more anomalous
            "seq_score": result["seq_score"],
            "arg_score": result.get("arg_max"),
            "worst_arg": result.get("worst_arg"),
            "n_calls": len(session.calls),
            "n_unseen": result["n_unseen"],
            "threshold": threshold,
        },
    }
