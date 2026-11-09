"""review.labelled events in Agent A's envelope (schema_version "1.0").

    data = {scored_event_id, detector, verdict: "attack" | "false_alarm",
            violation_type (attack type or null), agent_id, reviewer: "simulated"}

DSPOT needs scored_event_id, detector and verdict; violation_type is for the batch
classifiers (B2) and the dashboards.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from review_queue.domain.queue import Label


def label_event(label: Label, reviewer: str = "simulated") -> dict:
    i = label.item
    return {"schema_version": "1.0", "event_id": str(uuid.uuid4()), "event_type": "review.labelled",
            "occurred_at": datetime.now(timezone.utc).isoformat(), "run_id": i.run_id,
            "session_id": i.session_id, "sequence": None, "request_id": None,
            "data": {"scored_event_id": i.scored_event_id, "detector": i.detector, "verdict": label.verdict,
                     "violation_type": label.violation_type, "agent_id": i.agent_id, "reviewer": reviewer}}
