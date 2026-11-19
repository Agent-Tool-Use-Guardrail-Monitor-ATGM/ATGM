"""Loads labelled sessions: from the dataset files

Both return a list of (session_id, calls, label), calls in call order, label "compliant" / "violating".
"""
import json
from collections import defaultdict
from pathlib import Path


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