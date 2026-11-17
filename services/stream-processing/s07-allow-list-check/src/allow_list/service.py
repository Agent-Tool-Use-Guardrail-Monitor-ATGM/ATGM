"""Message routing without any Kafka dependency: one message in, `violation.flagged` events out."""
from __future__ import annotations

import json

from allow_list.detector import AllowListDetector
from allow_list.events import agent_id, flagged_event, is_tool_call, parse_toolset_update


class AllowListService:
    def __init__(self, detector: AllowListDetector, toolset_topic: str, flags_topic: str) -> None:
        self.detector = detector
        self.toolset_topic = toolset_topic
        self.flags_topic = flags_topic

    def handle(self, topic: str, key, value: bytes) -> list[tuple[str, str, dict]]:
        """Returns (topic, key, event) to publish. Raises ValueError / KeyError / TypeError for bad messages."""
        event = json.loads(value.decode("utf-8"))
        if not isinstance(event, dict):
            raise ValueError("Kafka event must be a JSON object")

        if topic == self.toolset_topic:
            key = key.decode("utf-8") if isinstance(key, bytes) else key
            for agent, tools in parse_toolset_update(event, key).items():
                self.detector.set_toolset(agent, tools)
            return []

        kind, session = event.get("event_type"), event.get("session_id")
        if kind == "session.started" and session:
            self.detector.start_session(session)
        elif kind == "session.ended" and session:
            self.detector.end_session(session)
        elif is_tool_call(event):
            agent = agent_id(event, topic)
            return [(self.flags_topic, agent, flagged_event(event, agent, v, self.detector.version))
                    for v in self.detector.process(event, agent)]
        return []
