"""DSPOT service: routes Kafka messages to the alarm monitor and publishes its alarms.

It only depends on a `sink` with send(topic, key, value), so it is tested without Kafka.
"""
from __future__ import annotations

import logging
from typing import Protocol

from dspot.adapters import events
from dspot.domain.monitor import AlarmMonitor

log = logging.getLogger("dspot")


class Sink(Protocol):
    def send(self, topic: str, key: str, value: dict) -> None: ...


class DSPOTService:
    def __init__(self, monitor: AlarmMonitor, sink: Sink,
                 alarm_topics: tuple[str, ...] = ("alerts", "review-queue")) -> None:
        self.monitor = monitor
        self.sink = sink
        self.alarm_topics = alarm_topics

    def handle(self, msg: dict) -> None:
        """Process one decoded message; bad messages are logged and skipped, never fatal."""
        try:
            kind = msg.get("event_type") if isinstance(msg, dict) else None
            if kind == events.SCORED:
                self._on_score(msg)
            elif kind == events.LABELLED:
                self._on_label(msg)
            # other event types on these topics are not for DSPOT
        except ValueError as e:
            log.warning("skipped message %s: %s", msg.get("event_id") if isinstance(msg, dict) else "?", e)

    def _on_score(self, msg: dict) -> None:
        score = events.parse_score(msg)
        calibrated = (score.agent_id, score.detector) in self.monitor.detectors
        alarm = self.monitor.on_score(score)
        if not calibrated and (score.agent_id, score.detector) in self.monitor.detectors:
            log.info("calibrated %s/%s: threshold %.4g", score.agent_id, score.detector,
                     self.monitor.detectors[(score.agent_id, score.detector)].threshold)
        if alarm is None:
            return
        event = events.alarm_event(alarm, msg)
        for topic in self.alarm_topics:
            self.sink.send(topic, score.agent_id, event)
        log.info("ALARM %s/%s event %s: score %.4g > threshold %.4g", score.agent_id,
                 score.detector, score.ref, score.value, alarm.threshold)

    def _on_label(self, msg: dict) -> None:
        verdict = events.parse_verdict(msg)
        if self.monitor.on_verdict(verdict):
            log.info("learned false alarm %s (%s)", verdict.ref, verdict.detector)
