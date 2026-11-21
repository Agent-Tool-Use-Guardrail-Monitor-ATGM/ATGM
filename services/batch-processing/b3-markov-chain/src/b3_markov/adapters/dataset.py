"""Loads sessions: from the dataset files (B1 layout or one raw events file) or from analytics_db.

All loaders return a list of Session (domain.sessions). `label` is "compliant" / "violating" like in B1.
"""
import json
import logging
from collections import defaultdict
from pathlib import Path

from b3_markov.domain.sessions import Session, build_sessions, to_call

log = logging.getLogger("b3-dataset")


def read_jsonl(path: Path) -> list[dict]:
    """Skips unparsable lines (e.g. a truncated last record) and says how many."""
    events, bad = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    if bad:
        log.warning("%s: skipped %d unparsable line(s)", path, bad)
    return events


def from_events_file(path: Path) -> list[Session]:
    """One raw events JSONL; the label follows from the category of session.started."""
    sessions, report = build_sessions(read_jsonl(path))
    if report["incomplete_sessions"]:
        log.warning("skipped %d incomplete session(s)", len(report["incomplete_sessions"]))
    for s in sessions:
        s.label = "compliant" if s.category == "normal" else "violating"
    return sessions


def from_dataset(dataset_dir: Path, scenario_file: str) -> list[Session]:
    """dataset/agent_b/events/events_for_<file> + dataset/agent_b/labels/labels_for_<file>
    (labels by actual behaviour, see services/agent-b/src/agent_b/label_events.py)."""
    sessions, report = build_sessions(read_jsonl(dataset_dir / "events" / f"events_for_{scenario_file}"))
    if report["incomplete_sessions"]:
        log.warning("skipped %d incomplete session(s)", len(report["incomplete_sessions"]))
    labels = {row["scenario_id"]: row["label"]
              for row in read_jsonl(dataset_dir / "labels" / f"labels_for_{scenario_file}")}
    for s in sessions:
        label = labels.get(s.session_id)
        s.label = None if label is None else ("violating" if label == "adversarial" else "compliant")
    return sessions


SESSION_CALLS_SQL = """
SELECT session_id, data, occurred_at FROM agent_events
WHERE event_type LIKE 'tool_call.%%' AND agent_id = %s
ORDER BY session_id, session_call_index"""

# the newest reviewer verdict per session (attack / false_alarm)
VERDICTS_SQL = """
SELECT DISTINCT ON (session_id) session_id, verdict FROM labels
WHERE agent_id = %s ORDER BY session_id, occurred_at DESC"""


def from_database(conninfo: str, agent_id: str = "B") -> list[Session]:
    """Tool calls from analytics_db.agent_events, labels from the reviewers (analytics_db.labels).

    The database has no session.started category: a session counts as normal unless the newest verdict is `attack`.
    """
    import psycopg

    with psycopg.connect(conninfo) as conn:
        verdicts = dict(conn.execute(VERDICTS_SQL, (agent_id,)).fetchall())
        calls = defaultdict(list)
        for session, data, occurred_at in conn.execute(SESSION_CALLS_SQL, (agent_id,)):
            calls[session].append({**data, "occurred_at": occurred_at.isoformat() if occurred_at else None})
    sessions = []
    for session, verdict in verdicts.items():
        if not calls[session]:
            continue
        attack = verdict == "attack"
        sessions.append(Session(session, [c["tool_name"] for c in calls[session]],
                                "adversarial" if attack else "normal", None,
                                "violating" if attack else "compliant",
                                calls=[to_call(c) for c in calls[session]]))
    return sessions
