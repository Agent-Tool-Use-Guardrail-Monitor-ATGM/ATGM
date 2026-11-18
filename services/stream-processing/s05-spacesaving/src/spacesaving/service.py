"""S05 service: process tool calls and review labels into frequent-item summaries."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Protocol

from spacesaving.adapters.events import (
    LABEL_EVENT_TYPE,
    TOOL_CALL_TYPES,
    parse_review_label,
    parse_tool_call,
)
from spacesaving.domain.integrated_spacesaving import IntegratedSpaceSaving


log = logging.getLogger("spacesaving")


class Sink(Protocol):
    def send(self, topic: str, key: str, value: dict) -> None: ...


class SpaceSavingService:
    def __init__(
        self,
        sink: Sink,
        capacity: int = 100,
        window_seconds: int = 60,
        top_k: int = 10,
        max_tracked_events: int = 50_000,
        retention_windows: int = 10,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")

        if window_seconds < 1 or top_k < 1:
            raise ValueError("window_seconds and top_k must be positive")

        if max_tracked_events < 1 or retention_windows < 1:
            raise ValueError("memory limits must be positive")

        self.sink = sink
        self.capacity = capacity
        self.window_seconds = window_seconds
        self.top_k = top_k
        self.max_tracked_events = max_tracked_events
        self.retention_windows = retention_windows

        # One sketch per agent, category and time window.
        self.sketches: dict[
            tuple[str, str, int], IntegratedSpaceSaving
        ] = {}

        # Original tool-call ID -> its contributions and original window.
        self.event_contributions: OrderedDict[
            str, tuple[str, int, tuple[tuple[str, str], ...]]
        ] = OrderedDict()

        # Bounded deduplication stores.
        self.processed_calls: OrderedDict[str, None] = OrderedDict()
        self.reviewed_calls: OrderedDict[str, None] = OrderedDict()

        self.current_window: int | None = None

    def handle(self, event: dict, topic: str) -> None:
        """Route one input event to the appropriate handler."""
        if not isinstance(event, dict):
            raise ValueError("event must be a JSON object")

        event_type = event.get("event_type")

        if event_type in TOOL_CALL_TYPES:
            self._on_tool_call(event, topic)
        elif event_type == LABEL_EVENT_TYPE:
            self._on_review_label(event)

    def _window_index(self, timestamp: datetime) -> int:
        return int(timestamp.timestamp() // self.window_seconds)

    def _get_sketch(
        self, agent_id: str, category: str, window: int
    ) -> IntegratedSpaceSaving:
        key = (agent_id, category, window)

        if key not in self.sketches:
            self.sketches[key] = IntegratedSpaceSaving(self.capacity)

        return self.sketches[key]

    @staticmethod
    def _argument_pattern(arguments: object) -> str:
        """Create a stable, bounded representation of an argument pattern."""
        canonical = json.dumps(
            arguments,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

        if len(canonical) > 256:
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            canonical = f"sha256:{digest}"

        return f"args:{canonical}"

    def _on_tool_call(self, event: dict, topic: str) -> None:
        call = parse_tool_call(event, topic)

        if call.event_id in self.processed_calls:
            return

        window = self._window_index(call.occurred_at)

        if self.current_window is None or window > self.current_window:
            self.current_window = window
            self._prune_old_windows()

        cutoff = self.current_window - self.retention_windows + 1

        # Ignore events older than the retained window range.
        if window < cutoff:
            log.warning("Ignoring expired tool call %s", call.event_id)
            return

        contributions = (
            ("tool", f"tool:{call.tool_name}"),
            ("arguments", self._argument_pattern(call.arguments)),
        )

        for category, item in contributions:
            self._get_sketch(call.agent_id, category, window).insert(item)

        self.event_contributions[call.event_id] = (
            call.agent_id,
            window,
            contributions,
        )
        self.processed_calls[call.event_id] = None

        self._trim_ordered(
            self.processed_calls, self.max_tracked_events
        )
        self._trim_ordered(
            self.event_contributions, self.max_tracked_events
        )

        self._publish_summary(call.agent_id, window, event)

    def _on_review_label(self, event: dict) -> None:
        label = parse_review_label(event)

        if label.scored_event_id in self.reviewed_calls:
            return

        contribution = self.event_contributions.pop(
            label.scored_event_id, None
        )

        # Without the original contribution, its original window is unknown.
        # Do not assign the label to the latest window.
        if contribution is None:
            log.info(
                "No retained contribution for review label %s",
                label.scored_event_id,
            )
            self.reviewed_calls[label.scored_event_id] = None
            self._trim_ordered(
                self.reviewed_calls, self.max_tracked_events
            )
            return

        agent_id, window, items = contribution

        if label.verdict == "false_alarm":
            for category, item in items:
                sketch = self.sketches.get(
                    (agent_id, category, window)
                )
                if sketch is not None:
                    sketch.delete(item)

        elif label.verdict == "attack":
            violation = label.violation_type or "unknown"
            self._get_sketch(
                agent_id, "violation", window
            ).insert(f"violation:{violation}")

        self.reviewed_calls[label.scored_event_id] = None
        self._trim_ordered(
            self.reviewed_calls, self.max_tracked_events
        )

        self._publish_summary(agent_id, window, event)

    def _publish_summary(
        self, agent_id: str, window: int, source_event: dict
    ) -> None:
        """Publish the top frequent items for one agent and time window."""
        window_start = datetime.fromtimestamp(
            window * self.window_seconds, tz=timezone.utc
        )
        window_end = datetime.fromtimestamp(
            (window + 1) * self.window_seconds, tz=timezone.utc
        )

        ranked = []

        for (agent, category, sketch_window), sketch in self.sketches.items():
            if agent != agent_id or sketch_window != window:
                continue

            ranked.extend(sketch.top(self.top_k))

        ranked.sort(key=lambda item: item["count"], reverse=True)
        top = ranked[: self.top_k]

        output = {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "event_type": "counts.summary",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "run_id": source_event.get("run_id"),
            "session_id": source_event.get("session_id"),
            "sequence": source_event.get("sequence"),
            "request_id": source_event.get("request_id"),
            "data": {
                "agent_id": agent_id,
                "detector": "spacesaving",
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "top": top,
            },
        }

        self.sink.send("stats", agent_id, output)

    def _prune_old_windows(self) -> None:
        if self.current_window is None:
            return

        cutoff = self.current_window - self.retention_windows + 1

        self.sketches = {
            key: sketch
            for key, sketch in self.sketches.items()
            if key[2] >= cutoff
        }

        self.event_contributions = OrderedDict(
            (event_id, value)
            for event_id, value in self.event_contributions.items()
            if value[1] >= cutoff
        )

    @staticmethod
    def _trim_ordered(store: OrderedDict, maximum: int) -> None:
        while len(store) > maximum:
            store.popitem(last=False)
