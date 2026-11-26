"""Output events in the team's envelope.

    anomaly.scored  -> scores   the current window count of the violation that just came in
                                (detector topk_counts), so DSPOT decides when a count is a spike
    counts.summary  -> stats    the top-k per agent once per time slot, for dashboards
"""
import uuid
from datetime import datetime, timezone

DETECTOR = "topk_counts"
MODEL_VERSION = "chen2017-global"


def iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def make_event(event_type, data, source=None):
    source = source or {}
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "run_id": source.get("run_id"),
        "session_id": source.get("session_id"),
        "sequence": source.get("sequence"),
        "request_id": None,
        "data": data,
    }


def count_score(agent, item, count, source):
    """The window count of `item` right after this violation, as a score for DSPOT."""
    return make_event("anomaly.scored", {
        "scored_event_id": source.get("event_id"),
        "agent_id": agent,
        "detector": DETECTOR,
        "model_version": MODEL_VERSION,
        "score": float(count),
        "item": item,
    }, source)


def counts_summary(agent, monitor, window_start, window_end, entered, left):
    """Top-k of the agent's violations in the current window, plus the protocol's cost."""
    return make_event("counts.summary", {
        "agent_id": agent,
        "detector": DETECTOR,
        "window_start": iso(window_start),
        "window_end": iso(window_end),
        "top": [{"item": item, "count": count} for item, count in monitor.ranking()],
        "entered": sorted(entered),
        "left": sorted(left),
        "messages": monitor.messages,
        "naive_messages": monitor.naive_messages,
        "resolutions": monitor.resolutions,
    })
