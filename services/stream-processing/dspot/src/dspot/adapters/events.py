"""Kafka message format: Agent A's event envelope (datalens-agent, schema_version "1.0").

    {"schema_version": "1.0", "event_id": "<uuid>", "event_type": "...",
     "occurred_at": "<ISO time>", "run_id": "<uuid>", "session_id": "<uuid>",
     "sequence": 7, "request_id": null, "data": {...}}

The `data` of the three event types DSPOT uses (proposed, see the README):

    anomaly.scored   (topic scores)        {scored_event_id, agent_id, detector, model_version, score}
    alarm.raised     (alerts, review-queue) {scored_event_id, agent_id, detector, model_version,
                                             score, threshold, q}
    review.labelled  (topic labels)        {scored_event_id, detector, verdict: "false_alarm" | "attack"}

Only this module knows the format; the domain works with Score, Alarm and Verdict.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from dspot.domain.monitor import Alarm, Score, Verdict

SCHEMA_VERSION = "1.0"
SCORED = "anomaly.scored"
ALARM = "alarm.raised"
LABELLED = "review.labelled"
VERDICTS = {"false_alarm": True, "attack": False}


def _data(msg: dict) -> dict:
    if msg.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {msg.get('schema_version')!r}")
    data = msg.get("data")
    if not isinstance(data, dict):
        raise ValueError("message has no data object")
    return data


def parse_score(msg: dict) -> Score:
    d = _data(msg)
    try:
        return Score(ref=str(d["scored_event_id"]), agent_id=str(d["agent_id"]),
                     detector=str(d["detector"]), value=float(d["score"]))
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"bad {SCORED} data: {e}") from None


def parse_verdict(msg: dict) -> Verdict:
    d = _data(msg)
    try:
        return Verdict(ref=str(d["scored_event_id"]), detector=str(d["detector"]),
                       false_alarm=VERDICTS[d["verdict"]])
    except (KeyError, TypeError) as e:
        raise ValueError(f"bad {LABELLED} data: {e}") from None


def alarm_event(alarm: Alarm, source: dict) -> dict:
    """The alarm as an envelope; run, session and sequence are copied from the score message."""
    s = alarm.score
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "event_type": ALARM,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "run_id": source.get("run_id"),
        "session_id": source.get("session_id"),
        "sequence": source.get("sequence"),
        "request_id": source.get("request_id"),
        "data": {
            "scored_event_id": s.ref,
            "agent_id": s.agent_id,
            "detector": s.detector,
            "model_version": source["data"].get("model_version"),
            "score": s.value,
            "threshold": alarm.threshold,
            "q": alarm.q,
        },
    }
