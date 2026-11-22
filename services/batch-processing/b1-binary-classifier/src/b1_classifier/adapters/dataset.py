"""Loads labelled sessions: from the dataset files

Both return a list of (session_id, calls, label), calls in call order, label "compliant" / "violating".
"""
import json
from collections import defaultdict
from pathlib import Path
from datetime import datetime

def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def from_dataset(dataset_dir: Path, scenario_file: str) -> list[tuple[str, list[dict], str]]:
    """dataset/agent_b/events/events_for_<file> + dataset/agent_b/labels/labels_for_<file>
    (labels by actual behaviour, see services/agent-b/src/agent_b/label_events.py)."""
    events = read_jsonl(dataset_dir / "events" / f"events_for_{scenario_file}")
    labels = {row["scenario_id"]: row["label"] for row in read_jsonl(dataset_dir / "labels" / f"labels_for_{scenario_file}")}
    calls = defaultdict(list)
    for event in events:
        if event["event_type"].startswith("tool_call."):
            calls[event["session_id"]].append(event["data"])
    return [(session, sorted(calls[session], key=lambda call: call["session_call_index"]),
             "violating" if label == "adversarial" else "compliant")
            for session, label in labels.items()]


SESSION_CALLS_SQL = """
SELECT session_id, data FROM agent_events
WHERE event_type LIKE 'tool_call.%%' AND agent_id = %s
ORDER BY session_id, session_call_index"""

# the newest reviewer verdict per session (attack / false_alarm)
VERDICTS_SQL = """
SELECT DISTINCT ON (session_id) session_id, verdict FROM labels
WHERE agent_id = %s ORDER BY session_id, occurred_at DESC"""


def from_database(conninfo: str, agent_id: str = "B") -> list[tuple[str, list[dict], str]]:
    """Tool calls from analytics_db.agent_events, labels from the reviewers (analytics_db.labels)."""
    import psycopg

    with psycopg.connect(conninfo) as conn:
        verdicts = dict(conn.execute(VERDICTS_SQL, (agent_id,)).fetchall())
        calls = defaultdict(list)
        for session, data in conn.execute(SESSION_CALLS_SQL, (agent_id,)):
            calls[session].append(data)
    return [(session, calls[session], "violating" if verdict == "attack" else "compliant")
            for session, verdict in verdicts.items() if calls[session]]

def from_collector(path: Path) -> list[tuple[str, list[dict], str]]:
    """Agent A (DataLens) sessions from a datalens-collector export (captures/all-events.jsonl).

    Label = the planned scenario category (prompt_injected -> "violating", normal -> "compliant"),
    because only 2 of the 130 sessions actually broke a rule, too few to learn from.
    Only the event part is used for features; the wrapper (category, label) is the answer.
    """
    events, category = defaultdict(list), {}
    for row in read_jsonl(path):
        event = row["event"]
        events[event["session_id"]].append(event)
        category[event["session_id"]] = row["category"]
    sessions = []
    for session, session_events in events.items():
        session_events.sort(key=lambda event: event["sequence"])
        label = "violating" if category[session] == "prompt_injected" else "compliant"
        sessions.append((session, collector_calls(session_events), label))
    return sessions


def collector_calls(events: list[dict]) -> list[dict]:
    outcomes = {event["data"]["tool_call_id"]: event for event in events
                if event["event_type"] in ("tool_call.completed", "tool_call.failed")}
    calls, previous = [], None
    for event in events:
        if event["event_type"] != "tool_call.requested":
            continue
        data = event["data"]
        started = _time(event["occurred_at"])
        outcome = outcomes.get(data["tool_call_id"])
        calls.append({
            "agent_id": "A",
            "tool_name": data.get("name") or "unknown",
            "arguments": data.get("features") or {},
            "success": outcome is not None and outcome["event_type"] == "tool_call.completed",
            "duration_ms": max(0.0, (_time(outcome["occurred_at"]) - started).total_seconds() * 1000) if outcome else 0.0,
            "time_since_previous_call_ms": (started - previous).total_seconds() * 1000 if previous else 0.0,
            "session_call_index": data["session_call_index"],
        })
        previous = started
    return sorted(calls, key=lambda call: call["session_call_index"])


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))