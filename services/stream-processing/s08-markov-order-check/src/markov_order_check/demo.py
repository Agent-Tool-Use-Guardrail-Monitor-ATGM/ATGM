"""Demo models and sessions for local runs and tests.

``build_table`` trains a model with B3 itself (``fit_detector`` + ``to_table``) and
adds in-sample thresholds. It is only for trying the pipeline before B3 has
announced real models; real models come from B3 on ``model-updates``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from b3_markov.domain.arguments import ArgParams
from b3_markov.domain.scoring import Params
from b3_markov.domain.sequences import END, START, UNK
from b3_markov.domain.sessions import Call, Session
from b3_markov.domain.training import fit_detector, percentile, to_table

DEMO_SESSIONS: dict[str, list[list[str]]] = {
    "A": [
        ["inspect_dataset", "finalize_statistics"],
        ["aggregate_statistics", "finalize_statistics"],
        ["aggregate_statistics", "aggregate_statistics", "finalize_statistics"],
        ["inspect_dataset", "aggregate_statistics", "finalize_statistics"],
        ["correlate_columns", "finalize_statistics"],
        ["request_clarification"],
        ["aggregate_statistics"],
        ["inspect_dataset", "request_clarification"],
    ],
    "B": [
        ["find_contact", "get_current_datetime", "get_free_slots", "tone_checker", "sensitive_content_scan",
         "save_draft"],
        ["find_contact", "get_current_datetime", "get_free_slots", "get_free_slots", "tone_checker",
         "sensitive_content_scan", "save_draft"],
        ["find_contact", "get_current_datetime", "get_free_slots", "save_draft"],
        ["get_current_datetime", "find_contact", "get_free_slots", "tone_checker", "sensitive_content_scan",
         "save_draft"],
    ],
}
DEMO_VOCABULARY = {
    "A": ["inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns", "finalize_statistics",
          "request_clarification"],
    "B": ["find_contact", "get_current_datetime", "get_free_slots", "tone_checker", "sensitive_content_scan",
          "save_draft"],
}
DEMO_ATTACKS: dict[str, list[list[str]]] = {
    "A": [["finalize_statistics", "inspect_dataset"], []],
    "B": [["find_contact", "save_draft", "save_draft", "save_draft"]],
}


def build_table(sessions: list[list[str]] | list[Session], *, vocabulary: list[str] | None = None,
                orders: tuple[int, ...] = (1, 2), alpha: float = 0.1, percentile_q: float = 95.0,
                with_arguments: bool = False, agent: str | None = None,
                smoothing: str = "additive") -> dict[str, Any]:
    """A B3 transition table from normal sessions (tool lists, or B3 Sessions with arguments)."""
    normal = [s if isinstance(s, Session) else Session(f"demo-{i}", list(s)) for i, s in enumerate(sessions)]
    mode = "joint" if with_arguments else "seq"
    detector = fit_detector(normal, list(orders), Params(smoothing, alpha),
                            ArgParams() if with_arguments else None, mode, vocabulary)
    calibration: dict[str, Any] = {"method": "in-sample-demo", "score": mode, "percentile": percentile_q,
                                   "threshold": {}, "call_threshold": {}}
    for k in orders:
        results = [detector.score(k, s) for s in normal]
        calibration["threshold"][str(k)] = percentile([r["score"] for r in results], percentile_q) + 1e-9
        calibration["call_threshold"][str(k)] = percentile([r["min_log_p"] for r in results],
                                                           100 - percentile_q) - 1e-9
    return to_table(detector, normal, calibration, label_filter="normal", seed=0, agent=agent,
                    vocabulary_declared=vocabulary is not None)


def demo_session_with_arguments(tools_args: list[tuple[str, dict]], session_id: str,
                                occurred_at: str = "2026-11-14T10:00:00+00:00") -> Session:
    """A B3 Session with arguments (for Agent B argument models in tests)."""
    calls = [Call(tool, args, occurred_at) for tool, args in tools_args]
    return Session(session_id, [c.tool for c in calls], calls=calls)


def model_message(agent: str, table: dict[str, Any], version: str = "demo_additive") -> dict[str, Any]:
    """model.trained envelope as B3 announces it (B3 Sec. 9, key b3-markov-chain.<agent>)."""
    return {"schema_version": "1.0", "event_id": str(uuid.uuid4()), "event_type": "model.trained",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "data": {"model": "b3-markov-chain", "agent": agent, "version": version, "path": None, "metrics": {},
                     "transition_table": table}}


def session_events(agent: str, tools: list[str], *, session_id: str | None = None,
                   start: datetime | None = None, failed: set[int] | None = None,
                   arguments: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """A session in the flat live envelope: started, one completed/failed per call, ended."""
    sid = session_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    t0 = start or datetime.now(timezone.utc)
    failed = failed or set()
    events = [{"schema_version": "1.0", "event_id": str(uuid.uuid4()), "event_type": "session.started",
               "occurred_at": t0.isoformat(), "run_id": run_id, "session_id": sid, "sequence": 1,
               "request_id": None, "data": {"agent_id": agent}}]
    for i, tool in enumerate(tools, start=1):
        events.append({"schema_version": "1.0", "event_id": str(uuid.uuid4()),
                       "event_type": "tool_call.failed" if i in failed else "tool_call.completed",
                       "occurred_at": (t0 + timedelta(milliseconds=100 * i)).isoformat(), "run_id": run_id,
                       "session_id": sid, "sequence": i + 1, "request_id": None,
                       "data": {"agent_id": agent, "tool_call_id": str(uuid.uuid4()), "tool_name": tool,
                                "arguments": (arguments[i - 1] if arguments else {}), "duration_ms": 40, "success": i not in failed,
                                "session_call_index": i, "time_since_previous_call_ms": 100}})
    events.append({"schema_version": "1.0", "event_id": str(uuid.uuid4()), "event_type": "session.ended",
                   "occurred_at": (t0 + timedelta(milliseconds=100 * (len(tools) + 1))).isoformat(),
                   "run_id": run_id, "session_id": sid, "sequence": len(tools) + 2, "request_id": None,
                   "data": {"agent_id": agent, "call_count": len(tools)}})
    return events
