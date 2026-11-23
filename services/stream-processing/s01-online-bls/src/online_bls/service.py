"""Join ordered tool calls to delayed session verdicts and persist the result."""

import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from math import tanh
from pathlib import Path

import numpy as np
from online_bls.domain.features import INPUT_WIDTH, Prefix
from online_bls.domain.model import ModelState, OnlineBLS

DETECTOR = "online_bls"
MODEL_VERSION = "bls-1"
TOOL_TOPICS = ("tool-calls.A", "tool-calls.B")
LABEL_TOPIC = "labels"
SCORE_TOPIC = "scores"
ERROR_TOPIC = "classifier-errors"
TOOL_EVENTS = ("tool_call.completed", "tool_call.failed")
VERDICTS = {"false_alarm": 0, "attack": 1}
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCall:
    index: int
    name: str
    event_id: str
    failed: bool
    argument_count: int
    run_id: str | None
    sequence: int | None


@dataclass
class Session:
    prefix: Prefix = field(default_factory=Prefix)
    index: int = 0
    pending_calls: dict[str, ToolCall] = field(default_factory=dict)
    broad_features: list[float] | None = None
    prediction: int | None = None
    prediction_ready: bool = False
    ended: bool = False
    label: int | None = None
    trained: bool = False
    error: int | None = None
    run_id: str | None = None


class ClassifierService:
    def __init__(self, path: str | Path) -> None:
        self.model = OnlineBLS(INPUT_WIDTH)
        self.db = sqlite3.connect(path)
        # One consumer owns the checkpoint and the corresponding Kafka group.
        self.db.execute("PRAGMA locking_mode = EXCLUSIVE")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                agent TEXT, id TEXT, state TEXT NOT NULL, PRIMARY KEY (agent, id)
            );
            CREATE TABLE IF NOT EXISTS models (
                agent TEXT PRIMARY KEY, version TEXT NOT NULL, state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS score_outbox (
                id TEXT PRIMARY KEY, event TEXT NOT NULL
            );
        """)
        self.models = {agent: self.model.initial_state() for agent in ("A", "B")}
        for agent, version, raw in self.db.execute("SELECT agent, version, state FROM models"):
            if version != MODEL_VERSION:
                raise ValueError(f"Unsupported Online-BLS checkpoint model version: {version}")
            factor, weights, counts = json.loads(raw)
            self.models[agent] = ModelState(np.array(factor), np.array(weights), tuple(counts))

    def close(self) -> None:
        self.db.close()

    def pending_scores(self) -> list[dict]:
        return [json.loads(raw) for (raw,) in self.db.execute("SELECT event FROM score_outbox ORDER BY rowid")]

    def acknowledge_score(self, event_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM score_outbox WHERE id = ?", (event_id,))

    def _load_session(self, agent: str, session_id: str) -> Session:
        row = self.db.execute(
            "SELECT state FROM sessions WHERE agent = ? AND id = ?", (agent, session_id)
        ).fetchone()
        if row is None:
            return Session()
        state = json.loads(row[0])
        state["prefix"] = Prefix(**state["prefix"])
        state["pending_calls"] = {
            index: ToolCall(**call) for index, call in state.get("pending_calls", {}).items()
        }
        return Session(**state)

    def handle(self, topic: str, event: object) -> None:
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            return
        kind, data, session_id = event.get("event_type"), event["data"], event.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return

        if topic == LABEL_TOPIC and kind == "review.labelled":
            agent = data.get("agent_id")
            verdict = data.get("verdict")
            if agent not in ("A", "B") or not isinstance(verdict, str) or verdict not in VERDICTS:
                return
            session = self._load_session(agent, session_id)
            if session.label is not None:
                if session.label != VERDICTS[verdict]:
                    log.warning("Conflicting verdict for agent %s session %s; kept first verdict", agent, session_id)
                return
            session.label = VERDICTS[verdict]
            self._save(agent, session_id, session)
        elif topic in TOOL_TOPICS:
            agent = topic[-1]
            if data.get("agent_id") not in (None, agent):
                return
            if kind == "session.ended":
                session = self._load_session(agent, session_id)
                if not session.ended:
                    session.ended = True
                    self._save(agent, session_id, session, self._score_available(agent, session_id, session))
            elif kind in TOOL_EVENTS:
                self._record_call(agent, session_id, event)

    def _record_call(self, agent: str, session_id: str, event: dict) -> None:
        data = event["data"]
        index, tool, source_id = data.get("session_call_index"), data.get("tool_name"), event.get("event_id")
        if type(index) is not int or index < 1 or not isinstance(tool, str) or not tool:
            return
        if not isinstance(source_id, str) or not source_id:
            return
        session = self._load_session(agent, session_id)
        if session.ended or index <= session.index or str(index) in session.pending_calls:
            return
        arguments = data.get("arguments")
        session.pending_calls[str(index)] = ToolCall(
            index=index,
            name=tool,
            event_id=source_id,
            failed=event["event_type"] == "tool_call.failed",
            argument_count=len(arguments) if isinstance(arguments, dict) else 0,
            run_id=event.get("run_id"),
            sequence=event.get("sequence"),
        )
        self._save(agent, session_id, session, self._score_available(agent, session_id, session))

    def _score_available(self, agent: str, session_id: str, session: Session) -> list[dict]:
        if session.ended:
            # Missing indexes can no longer arrive once the session ends.
            remaining = sorted(session.pending_calls.values(), key=lambda call: call.index)
            session.pending_calls.clear()
            return [self._score_call(agent, session_id, session, call) for call in remaining]

        scores = []
        while (call := session.pending_calls.pop(str(session.index + 1), None)) is not None:
            scores.append(self._score_call(agent, session_id, session, call))
        return scores

    def _score_call(self, agent: str, session_id: str, session: Session, call: ToolCall) -> dict:
        features = session.prefix.observe(call.name, call.failed, call.argument_count)
        state = self.models[agent]
        broad = self.model.expand(features)
        margin = float(broad @ (state.weights[:, 1] - state.weights[:, 0]))
        session.prediction = int(margin > 0.0)
        session.prediction_ready = all(state.class_counts)
        session.index = call.index
        session.run_id = call.run_id
        session.broad_features = broad.tolist()
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"atgm/{DETECTOR}/{MODEL_VERSION}/{agent}/{call.event_id}"))
        return {
            "schema_version": "1.0",
            "event_id": event_id,
            "event_type": "anomaly.scored",
            "occurred_at": datetime.now(UTC).isoformat(),
            "run_id": call.run_id,
            "session_id": session_id,
            "sequence": call.sequence,
            "request_id": None,
            "data": {
                "scored_event_id": call.event_id,
                "agent_id": agent,
                "detector": DETECTOR,
                "model_version": MODEL_VERSION,
                "score": (1.0 + tanh(margin)) / 2.0,
                "predicted_class": session.prediction,
                "ready": session.prediction_ready,
                "session_call_index": call.index,
            },
        }
    def _save(self, agent: str, session_id: str, session: Session, scores: list[dict] | None = None) -> None:
        output = list(scores or ())
        updated = None
        if session.ended and session.label is not None and not session.trained and session.broad_features is not None:
            if session.prediction_ready:
                session.error = int(session.prediction != session.label)
                event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(
                    ["atgm", "classifier.error", DETECTOR, MODEL_VERSION, agent, session_id]
                )))
                output.append({
                    "schema_version": "1.0",
                    "event_id": event_id,
                    "event_type": "classifier.error",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "run_id": session.run_id,
                    "session_id": session_id,
                    "sequence": None,
                    "request_id": None,
                    "data": {
                        "agent_id": agent,
                        "detector": DETECTOR,
                        "model_version": MODEL_VERSION,
                        "error": session.error,
                    },
                })
            updated = self.model.learn(self.models[agent], np.array(session.broad_features), session.label)
            session.broad_features = None
            session.trained = True

        with self.db:
            if updated is not None:
                state = json.dumps([updated.factor.tolist(), updated.weights.tolist(), updated.class_counts])
                self.db.execute("INSERT OR REPLACE INTO models VALUES (?, ?, ?)", (agent, MODEL_VERSION, state))
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
                            (agent, session_id, json.dumps(asdict(session))))
            for score in output:
                self.db.execute("INSERT INTO score_outbox VALUES (?, ?)", (score["event_id"], json.dumps(score)))
        if updated is not None:
            self.models[agent] = updated
