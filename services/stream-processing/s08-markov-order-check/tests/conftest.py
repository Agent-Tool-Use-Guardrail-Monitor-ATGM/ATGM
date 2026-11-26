from __future__ import annotations

import sys
from pathlib import Path

# Development convenience: use the B3 package from the same repository if it is not installed.
_B3_SRC = Path(__file__).resolve().parents[3] / "batch-processing" / "b3-markov-chain" / "src"
try:
    import b3_markov  # noqa: F401
except ImportError:
    if _B3_SRC.is_dir():
        sys.path.insert(0, str(_B3_SRC))

import json
import uuid
from dataclasses import replace

import pytest

from markov_order_check.config import Settings
from markov_order_check.demo import DEMO_SESSIONS, DEMO_VOCABULARY, build_table, model_message, session_events
from markov_order_check.detector import MarkovOrderPipeline
from markov_order_check.scoring import MarkovModel


def make_model(agent: str = "B", sessions=None, vocabulary=None, orders=(1, 2), version="v1", **kwargs) -> MarkovModel:
    sessions = sessions if sessions is not None else DEMO_SESSIONS[agent]
    table = build_table(sessions, vocabulary=vocabulary or DEMO_VOCABULARY[agent], orders=orders, **kwargs)
    return MarkovModel(table, version=version, agent=agent)


def make_pipeline(*models: MarkovModel, **settings_overrides) -> MarkovOrderPipeline:
    settings = replace(Settings(), **settings_overrides)
    pipeline = MarkovOrderPipeline(settings)
    for m in models:
        pipeline.add_model(m)
    return pipeline


def feed(pipeline: MarkovOrderPipeline, events, agent: str = "B", start: float = 0.0, flush: bool = True):
    now = start
    outputs = []
    for e in events:
        now += 0.01
        outputs += pipeline.handle_event(f"tool-calls.{agent}", e, now)
    if flush:
        outputs += pipeline.flush()
    return outputs


def strip_wall_clock(event: dict) -> dict:
    """Drop the fields that depend on processing time (occurred_at, latency_ms)."""
    e = json.loads(json.dumps(event))
    e.pop("occurred_at", None)
    e["data"].pop("latency_ms", None)
    return e


def v2_session(tools: list[str | None], session_id: str | None = None) -> list[dict]:
    """Agent A's recorded agent-run-events-v2 payload: name only on tool_call.requested."""
    sid = session_id or str(uuid.uuid4())
    seq = 1
    events = [{"event_id": str(uuid.uuid4()), "event_type": "session.started", "session_id": sid, "sequence": seq,
               "occurred_at": "2026-11-14T10:00:00Z", "run_id": "r", "data": {"category": "normal"}}]
    for i, tool in enumerate(tools, start=1):
        tcid = str(uuid.uuid4())
        req = {"kind": "numerical" if tool else "unknown", "tool_call_id": tcid, "session_call_index": i,
               "features": {}, "arguments_sha256": "x"}
        if tool:
            req["name"] = tool
        seq += 1
        events.append({"event_id": str(uuid.uuid4()), "event_type": "tool_call.requested", "session_id": sid,
                       "sequence": seq, "occurred_at": "2026-11-14T10:00:01Z", "run_id": "r", "data": req})
        seq += 1
        events.append({"event_id": str(uuid.uuid4()), "event_type": "model_call.completed", "session_id": sid,
                       "sequence": seq, "occurred_at": "2026-11-14T10:00:01Z", "run_id": "r", "data": {}})
        seq += 1
        status = "completed" if tool else "failed"
        events.append({"event_id": str(uuid.uuid4()), "event_type": f"tool_call.{status}", "session_id": sid,
                       "sequence": seq, "occurred_at": "2026-11-14T10:00:02Z", "run_id": "r",
                       "data": {"status": status, "tool_call_id": tcid, "session_call_index": i,
                                **({} if tool else {"reason": "unknown_tool"})}})
    seq += 1
    events.append({"event_id": str(uuid.uuid4()), "event_type": "session.ended", "session_id": sid, "sequence": seq,
                   "occurred_at": "2026-11-14T09:59:59Z", "run_id": "r", "data": {"outcome": "completed"}})
    return events


@pytest.fixture
def model_b():
    return make_model("B")


@pytest.fixture
def model_a():
    return make_model("A", orders=(1,))


__all__ = ["make_model", "make_pipeline", "feed", "strip_wall_clock", "v2_session", "session_events",
           "model_message"]
