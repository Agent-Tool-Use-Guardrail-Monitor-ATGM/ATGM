"""Events published to the `flags` topic, in the team's event format."""
import uuid
from datetime import datetime, timezone


def make_event(event_type: str, agent: str, data: dict) -> dict:
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "run_id": None,
        "session_id": None,
        "sequence": None,
        "request_id": None,
        "data": {"stage": "sliding_window_topk", "agent_id": agent, **data},
    }


def as_list(ranking):
    return [{"item": item, "count": count} for item, count in ranking]


def topk_changed(agent, entered, left, ranking):
    """Spike alert: the most frequent violations of an agent changed."""
    return make_event("topk.changed", agent, {
        "entered": sorted(entered),
        "left": sorted(left),
        "top": as_list(ranking),
    })


def topk_stats(agent, monitor):
    """Regular status: current top-k and how many messages the protocol needed."""
    return make_event("topk.stats", agent, {
        "top": as_list(monitor.ranking()),
        "messages": monitor.messages,
        "naive_messages": monitor.naive_messages,
        "resolutions": monitor.resolutions,
    })