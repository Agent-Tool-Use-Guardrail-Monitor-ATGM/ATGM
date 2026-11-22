"""Loads sessions: from the dataset files (B1 layout, one raw events file, Agent A's wrapped file) or from analytics_db.

All loaders return a list of Session (domain.sessions). `label` is "compliant" / "violating" like in B1.
"""
import json
import logging
from collections import defaultdict
from pathlib import Path

from b3_markov.domain.sequences import UNK
from b3_markov.domain.sessions import Call, Session, build_sessions, to_call

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


def from_agent_a_file(path: Path) -> list[Session]:
    """Agent A's recorded dataset: JSONL of wrapped records (spec Sec. 15.3).

    Each line has category / attack_type / label next to the event under `event` (payload agent-run-events-v2).
    The tool name sits in tool_call.requested (data.name); tool_call.completed / tool_call.failed carry the result.
    Request and result are joined by data.tool_call_id and the call is counted once, at its result, with the name
    from whichever of the two has it (no name -> <UNK>, e.g. a request for a tool that does not exist). Failed
    calls count. Calls are ordered by data.session_call_index, else by the envelope sequence. model_call.* is ignored.
    Arguments are only hashed in this data, so calls carry none.
    """
    seen: set = set()
    meta: dict[str, dict] = {}
    requested: dict[tuple, dict] = {}
    results: dict[str, list[dict]] = {}
    for record in read_jsonl(path):
        event = record.get("event") or {}
        if event.get("event_id") in seen:
            continue
        seen.add(event.get("event_id"))
        session = event.get("session_id") or record.get("case_id")
        if not session:
            continue
        meta.setdefault(session, {"category": record.get("category"), "attack_type": record.get("attack_type"),
                                  "label": record.get("label")})
        kind, data = event.get("event_type", ""), event.get("data") or {}
        if kind == "tool_call.requested":
            requested[(session, data.get("tool_call_id"))] = data
        elif kind in ("tool_call.completed", "tool_call.failed"):
            results.setdefault(session, []).append(event)

    sessions = []
    for session, info in meta.items():
        calls = []
        for event in results.get(session, []):
            data = event.get("data") or {}
            request = requested.get((session, data.get("tool_call_id")), {})
            name = request.get("name") or data.get("name") or data.get("tool_name") or UNK
            index = data.get("session_call_index", request.get("session_call_index", event.get("sequence", 0)))
            calls.append((index, event.get("sequence", 0), Call(name, {}, event.get("occurred_at"))))
        ordered = [c for _, _, c in sorted(calls, key=lambda item: item[:2])]
        sessions.append(Session(session, [c.tool for c in ordered], info["category"] or "normal",
                                info["attack_type"], info["label"], calls=ordered))
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
WHERE event_type IN ('tool_call.completed', 'tool_call.failed') AND agent_id = %s
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
