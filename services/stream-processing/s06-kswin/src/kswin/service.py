"""Application service for per-agent KSWIN drift detection."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from kswin.adapters.events import parse_score, parse_tool_call
from kswin.domain.detector import KSWIN


class Sink(Protocol):
    def send(self, topic: str, key: str, value: dict[str, Any]) -> None:
        """Publish an event."""


class KSWINService:
    """Coordinate feature extraction, drift detection, and event publishing."""

    FEATURES = ("argument_length", "failure_rate", "anomaly_score")

    def __init__(
        self,
        sink: Sink,
        window_size: int = 100,
        stat_size: int = 30,
        alpha: float = 0.005,
        random_state: int = 42,
    ) -> None:
        self.sink = sink
        self.window_size = window_size
        self.stat_size = stat_size
        self.alpha = alpha
        self.random_state = random_state

        self.detectors: dict[tuple[str, str], KSWIN] = {}

    def _detector(self, agent_id: str, feature: str) -> KSWIN:
        key = (agent_id, feature)

        if key not in self.detectors:
            seed = self.random_state + sum(
                ord(character) for character in f"{agent_id}:{feature}"
            )

            self.detectors[key] = KSWIN(
                window_size=self.window_size,
                stat_size=self.stat_size,
                alpha=self.alpha,
                random_state=seed,
            )

        return self.detectors[key]

    def _observe(
        self,
        agent_id: str,
        feature: str,
        value: float,
        source_event: dict[str, Any],
    ) -> None:
        result = self._detector(agent_id, feature).update(value)

        if result is None or not result.drift_detected:
            return

        now = datetime.now(timezone.utc).isoformat()

        drift_event = {
            "schema_version": source_event.get("schema_version", "1.0"),
            "event_id": str(uuid.uuid4()),
            "event_type": "drift.detected",
            "occurred_at": now,
            "run_id": source_event.get("run_id"),
            "session_id": source_event.get("session_id"),
            "sequence": source_event.get("sequence"),
            "request_id": source_event.get("request_id"),
            "data": {
                "agent_id": agent_id,
                "detector": "kswin",
                "monitored": feature,
                "statistic": result.statistic,
                "p_value": result.p_value,
                "alpha": self.alpha,
                "window_size": self.window_size,
            },
        }

        self.sink.send(
            topic="drift",
            key=agent_id,
            value=drift_event,
        )

    def process(self, event: dict[str, Any], topic: str) -> None:
        """Process one tool-call or anomaly-score event."""
        if event.get("event_type") in {
            "tool_call.completed",
            "tool_call.failed",
        }:
            observation = parse_tool_call(event, topic)

            self._observe(
                observation.agent_id,
                "argument_length",
                observation.argument_length,
                observation.source_event,
            )

            self._observe(
                observation.agent_id,
                "failure_rate",
                observation.failure_rate,
                observation.source_event,
            )

        elif event.get("event_type") == "anomaly.scored":
            observation = parse_score(event, topic)

            self._observe(
                observation.agent_id,
                "anomaly_score",
                observation.anomaly_score,
                observation.source_event,
            )
