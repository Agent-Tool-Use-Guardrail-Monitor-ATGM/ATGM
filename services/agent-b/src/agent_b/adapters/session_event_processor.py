"""Publishes agent session and tool call events to Kafka or writes them into a specified file, thus creating the dataset.

Per user prompt (= session): session.started, one tool_call.completed /
tool_call.failed per tool call, session.ended.
A call counts as failed when the tool raised, returned an error, or answered with a
known error text ("No contact found", "Invalid date"). The two checking tools also report
their decision in data.result (scan status and finding types, tone match and score),
never the draft text.

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
from pathlib import Path
from typing import Protocol, TextIO

from confluent_kafka import Producer
from langchain_core.callbacks import BaseCallbackHandler

SCHEMA_VERSION = "1.0"

# Answers that mean a tool did not do its job, although it returned normally
ERROR_ANSWERS = {
    "find_contact": ("No contact found",),
    "get_free_slots": ("Invalid date",),
}


def _content(output: Any) -> Any:
    """The tool's answer: a ToolMessage's content (dict answers arrive as JSON text) or the raw value."""
    content = getattr(output, "content", output)
    if isinstance(content, str) and content[:1] == "{":
        try:
            return json.loads(content)
        except ValueError:
            return content
    return content


def answer_failed(tool_name: str, content: Any) -> bool:
    """A normal-looking answer that is really a failure, e.g. 'No contact found'."""
    if isinstance(content, str):
        return content.startswith(ERROR_ANSWERS.get(tool_name, ()))
    if isinstance(content, dict) and tool_name == "tone_checker":
        return any(i.get("code") == "empty_draft" for i in content.get("issues", []))
    return False


def result_summary(tool_name: str, content: Any) -> dict | None:
    """What the monitor may know about a tool's answer: decisions only, never draft text or secrets."""
    if not isinstance(content, dict):
        return None
    if tool_name == "sensitive_content_scan":
        return {"status": content.get("status"),
                "finding_types": sorted({f.get("type") for f in content.get("findings", []) if f.get("type")})}
    if tool_name == "tone_checker":
        return {"matches_tone": content.get("matches_tone"), "score": content.get("score")}
    return None

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

class EventSink(Protocol):
    def send(self, key: str, event: dict) -> None: ...
    def flush(self) -> None: ...


class KafkaSink:
    def __init__(self, producer: Producer, topic: str) -> None:
        self._producer = producer
        self._topic = topic

    def send(self, key: str, event: dict) -> None:
        self._producer.produce(self._topic, key=key, value=json.dumps(event, default=str))
        self._producer.poll(0)

    def flush(self) -> None:
        self._producer.flush(10)


class JsonlSink:
    """Appends one JSON event per line. Shared by all sessions of a run."""

    def __init__(self, path: Path, append: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = open(path, "a" if append else "w", encoding="utf-8")
        self._lock = threading.Lock()
    def send(self, key: str, event: dict) -> None:
        line = json.dumps(event, default=str, ensure_ascii=False)
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()

    def flush(self) -> None:
        with self._lock:
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            self._file.close()


class SessionEventPublisher(BaseCallbackHandler):
    """One instance per session. Pass it via config={"callbacks": [publisher]}."""

    def __init__(self, sink: EventSink, *, run_id: str, session_id: str, agent_id: str = "B", session_info: dict | None = None, tool_args: dict[str, set] | None = None) -> None:
        self._session_info = session_info or {}
        self._sink = sink
        self._run_id = run_id
        self._session_id = session_id
        self._agent_id = agent_id
        self._lock = threading.Lock()  # tools may run in parallel threads
        self._sequence = 0
        self._call_count = 0
        self._last_end = time.monotonic()  # end of previous call (session start for the first)
        self._pending: dict[UUID, dict] = {}
        self._finished: dict[int, dict] = {}   # finished calls waiting for their turn
        self._next_index = 1                  
        self._publish_lock = threading.Lock() 
        self._tool_args = tool_args or {}   # tool name -> the parameters the tool accepts
    
    # -- session lifecycle -------------------------------------------------

    def start(self) -> None:
        self._last_end = time.monotonic()
        self._emit("session.started", {"agent_id": self._agent_id, **self._session_info})
    def end(self) -> None:
        with self._lock:
            unfinished = list(self._pending.values())
            self._pending.clear()
        for call in unfinished:                # a call that never returned counts as failed
            self._finished_call(call, success=False, ended=time.monotonic())
        self._publish_ready(flush_all=True)
        self._emit("session.ended", {"agent_id": self._agent_id, "call_count": self._call_count})
        self._sink.flush()

    # -- LangChain callbacks -----------------------------------------------

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, run_id: UUID,
                      inputs: dict[str, Any] | None = None, **kwargs: Any) -> None:
        started = time.monotonic()
        name = kwargs.get("name") or (serialized or {}).get("name") or "unknown"
        arguments = inputs if inputs is not None else {"input": input_str}
        if name in self._tool_args:        
            arguments = {key: value for key, value in arguments.items() if key in self._tool_args[name]}
        with self._lock:
            self._call_count += 1
            self._pending[run_id] = {
                "tool_name": name,
                "arguments": arguments,
                "started": started,
                "session_call_index": self._call_count,
                "time_since_previous_call_ms": max(0, int((started - self._last_end) * 1000)),
            }
        #print(f"\n[TOOL CALL] {name}({json.dumps(arguments, default=str)})")

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        content = _content(output)
        with self._lock:
            call = self._pending.get(run_id)
            name = call["tool_name"] if call else ""
        failed = getattr(output, "status", "success") == "error" or answer_failed(name, content)
        self._finish(run_id, success=not failed, result=result_summary(name, content))

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        #print(f"[TOOL ERROR] {type(error).__name__}: {error}")
        self._finish(run_id, success=False)

    # -- internals ---------------------------------------------------------

    def _finish(self, run_id: UUID, *, success: bool, result: dict | None = None) -> None:
        ended = time.monotonic()
        with self._lock:
            call = self._pending.pop(run_id, None)
            if call is None:
                return
            self._last_end = ended
        self._finished_call(call, success=success, ended=ended, result=result)
        self._publish_ready()

    def _finished_call(self, call: dict, *, success: bool, ended: float, result: dict | None = None) -> None:
        data = {
            "agent_id": self._agent_id,
            "tool_name": call["tool_name"],
            "arguments": call["arguments"],
            "duration_ms": int((ended - call["started"]) * 1000),
            "success": success,
            "session_call_index": call["session_call_index"],
            "time_since_previous_call_ms": call["time_since_previous_call_ms"],
        }
        if result is not None:
            data["result"] = result
        with self._lock:
            self._finished[call["session_call_index"]] = data

    def _publish_ready(self, flush_all: bool = False) -> None:
        with self._publish_lock:
            while True:
                with self._lock:
                    if self._next_index in self._finished:
                        data = self._finished.pop(self._next_index)
                    elif flush_all and self._finished:
                        data = self._finished.pop(min(self._finished))
                    else:
                        return
                    self._next_index = data["session_call_index"] + 1
                self._emit("tool_call.completed" if data["success"] else "tool_call.failed", data)

    def _emit(self, event_type: str, data: dict) -> None:
        with self._lock:
            self._sequence += 1
            event = envelope(event_type, data, run_id=self._run_id,
                            session_id=self._session_id, sequence=self._sequence)
        try:
            self._sink.send(self._session_id, event)
        except Exception:  # never let sink problems break the agent
            log.exception("Failed to publish %s", event_type)