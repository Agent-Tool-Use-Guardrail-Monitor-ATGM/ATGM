"""Review UI logic without Streamlit, Kafka or a database (so it can be tested).

The page shows the sessions ACI sent to review (`decision.made` with decision "review", or a
random audit) that have no reviewer verdict yet, and publishes the human's verdict as a
`review.labelled` event on the `labels` topic, in the same format as the simulated reviewer
(services/review-queue), so DSPOT, ACI, S01, S05 and the batch jobs learn from it unchanged.

Sessions with scenario ground truth (mocks, generated scenarios) are answered by the
simulated reviewer; by default the page hides them, so a session is never judged twice.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

VERDICTS = {"Attack": "attack", "Normal (false alarm)": "false_alarm"}
# B2's violation classes (services/batch-processing/b2-violation-type-classifier), plus "other"
VIOLATION_TYPES = ["unauthorized_tool", "unsafe_args", "skipped_check", "out_of_order", "other"]

PENDING_SQL = """
SELECT d.event_id, d.occurred_at, d.session_id, d.run_id, d.data
FROM other_events d
WHERE d.event_type = 'decision.made'
  AND (d.data->>'decision' = 'review' OR (d.data->>'audit')::boolean)
  AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.session_id = d.session_id)
ORDER BY d.occurred_at DESC
LIMIT %(limit)s
"""
CALLS_SQL = """
SELECT sequence, occurred_at, event_type, tool_name, success, duration_ms, arguments
FROM agent_events WHERE session_id = %(sid)s
ORDER BY coalesce(sequence, 0), occurred_at
"""
SCORES_SQL = """
SELECT detector, count(*) AS scores, round(max(score)::numeric, 3) AS max_score,
       round(avg(score)::numeric, 3) AS avg_score
FROM scores WHERE session_id = %(sid)s GROUP BY detector ORDER BY max_score DESC NULLS LAST
"""
FLAGS_SQL = """
SELECT occurred_at, data->>'rule' AS rule, data->>'severity' AS severity, data->>'detector' AS detector
FROM other_events WHERE session_id = %(sid)s AND event_type = 'violation.flagged' ORDER BY occurred_at
"""
ALARMS_SQL = """
SELECT occurred_at, detector, round(score::numeric, 3) AS score, round(threshold::numeric, 3) AS threshold
FROM alarms WHERE session_id = %(sid)s ORDER BY occurred_at
"""
DONE_SQL = """
SELECT occurred_at, agent_id, session_id, verdict, violation_type, reviewer
FROM labels ORDER BY occurred_at DESC LIMIT %(limit)s
"""
COUNTS_SQL = """
SELECT coalesce(split_part(reviewer, ':', 1), 'unknown') AS reviewer, count(*) FROM labels GROUP BY 1
"""


def item_from_decision(row: dict) -> dict:
    """The reviewable item of one pending `decision.made` row (as PENDING_SQL returns it)."""
    data = row.get("data") or {}
    return {"session_id": row["session_id"], "run_id": row.get("run_id"),
            "agent_id": data.get("agent_id"), "detector": data.get("detector", "aci"),
            "scored_event_id": data.get("scored_event_id") or row["session_id"],
            "decision": data.get("decision"), "audit": bool(data.get("audit")),
            "session_score": data.get("session_score"), "pass_up_to": data.get("pass_up_to"),
            "flag_from": data.get("flag_from"), "decided_at": row.get("occurred_at")}


def without_ground_truth(items: list[dict], known: set[str]) -> list[dict]:
    """Drop the sessions the simulated reviewer answers (they have scenario ground truth)."""
    return [i for i in items if i["session_id"] not in known]


def label_event(item: dict, verdict: str, violation_type: str | None, reviewer: str,
                now: datetime | None = None) -> dict:
    """review.labelled event for a human verdict, same shape as the simulated reviewer's."""
    if verdict not in VERDICTS.values():
        raise ValueError(f"verdict must be one of {sorted(VERDICTS.values())}")
    if verdict == "attack" and violation_type not in VIOLATION_TYPES:
        raise ValueError(f"an attack needs a violation type from {VIOLATION_TYPES}")
    name = " ".join((reviewer or "").split())[:40] or "anonymous"
    return {"schema_version": "1.0", "event_id": str(uuid.uuid4()), "event_type": "review.labelled",
            "occurred_at": (now or datetime.now(timezone.utc)).isoformat(), "run_id": item.get("run_id"),
            "session_id": item["session_id"], "sequence": None, "request_id": None,
            "data": {"scored_event_id": item["scored_event_id"], "detector": item["detector"],
                     "verdict": verdict, "violation_type": violation_type if verdict == "attack" else None,
                     "agent_id": item.get("agent_id"), "reviewer": f"human:{name}"}}
