"""Publishes agent session and tool call events to Kafka (schema_version "1.0").

Per user prompt (= session): session.started, one tool_call.completed /
tool_call.failed per tool call, session.ended.

Plug it into the agent through LangChain callbacks; events are sent at the
moment a tool call finishes, with real measured timings.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from confluent_kafka import Producer
from langchain_core.callbacks import BaseCallbackHandler

SCHEMA_VERSION = "1.0"

log = logging.getLogger(__name__)


def envelope(event_type: str, data: dict, *, run_id: str, session_id: str, sequence: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "session_id": session_id,
        "sequence": sequence,
        "request_id": None,
        "data": data,
    }


class SessionEventPublisher(BaseCallbackHandler):
    """One instance per session. Pass it via config={"callbacks": [publisher]}."""

    def __init__(self, producer: Producer, topic: str, *, run_id: str, session_id: str, agent_id: str = "B") -> None:
        self._producer = producer
        self._topic = topic
        self._run_id = run_id
        self._session_id = session_id
        self._agent_id = agent_id
        self._lock = threading.Lock()  # tools may run in parallel threads
        self._sequence = 0
        self._call_count = 0
        self._last_end = time.monotonic()  # end of previous call (session start for the first)
        self._pending: dict[UUID, dict] = {}

    # -- session lifecycle -------------------------------------------------

    def start(self) -> None:
        self._last_end = time.monotonic()
        self._emit("session.started", {"agent_id": self._agent_id})

    def end(self) -> None:
        self._emit("session.ended", {"agent_id": self._agent_id, "call_count": self._call_count})
        self._producer.flush(10)

    # -- LangChain callbacks -----------------------------------------------

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, run_id: UUID,
                      inputs: dict[str, Any] | None = None, **kwargs: Any) -> None:
        started = time.monotonic()
        name = kwargs.get("name") or (serialized or {}).get("name") or "unknown"
        arguments = inputs if inputs is not None else {"input": input_str}
        with self._lock:
            self._call_count += 1
            self._pending[run_id] = {
                "tool_name": name,
                "arguments": arguments,
                "started": started,
                "session_call_index": self._call_count,
                "time_since_previous_call_ms": max(0, int((started - self._last_end) * 1000)),
            }
        print(f"\n[TOOL CALL] {name}({json.dumps(arguments, default=str)})")

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        content = getattr(output, "content", output)
        print(f"[TOOL RESULT] {content}")
        self._finish(run_id, success=getattr(output, "status", "success") != "error")

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        print(f"[TOOL ERROR] {type(error).__name__}: {error}")
        self._finish(run_id, success=False)

    # -- internals ---------------------------------------------------------

    def _finish(self, run_id: UUID, *, success: bool) -> None:
        ended = time.monotonic()
        with self._lock:
            call = self._pending.pop(run_id, None)
            if call is None:
                return
            self._last_end = ended
        self._emit(
            "tool_call.completed" if success else "tool_call.failed",
            {
                "agent_id": self._agent_id,
                "tool_name": call["tool_name"],
                "arguments": call["arguments"],
                "duration_ms": int((ended - call["started"]) * 1000),
                "success": success,
                "session_call_index": call["session_call_index"],
                "time_since_previous_call_ms": call["time_since_previous_call_ms"],
            },
        )

    def _emit(self, event_type: str, data: dict) -> None:
        with self._lock:
            self._sequence += 1
            event = envelope(event_type, data, run_id=self._run_id,
                             session_id=self._session_id, sequence=self._sequence)
        try:
            self._producer.produce(self._topic, key=self._session_id,
                                   value=json.dumps(event, default=str))
            self._producer.poll(0)
        except Exception:  # never let Kafka problems break the agent
            log.exception("Failed to publish %s", event_type)