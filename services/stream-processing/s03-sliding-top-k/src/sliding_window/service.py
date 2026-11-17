"""S03 logic without Kafka: tool calls and violations in, scores and summaries out."""
import logging
from dataclasses import dataclass

from sliding_window import events
from sliding_window.domain.topk import TopKMonitor
from sliding_window.domain.violations import ViolationReader

log = logging.getLogger("sliding_window")


@dataclass
class Settings:
    k: int = 3
    nodes: int = 3
    slot_seconds: float = 30.0
    units: int = 20                 # window = 20 x 30 s = 10 minutes
    epsilon: float = 5.0
    scores_topic: str = "scores"
    stats_topic: str = "stats"

    @property
    def window_seconds(self) -> float:
        return self.slot_seconds * self.units


class TopKService:
    def __init__(self, settings: Settings, reader: ViolationReader):
        self.settings = settings
        self.reader = reader
        self.monitors = {}           # one monitor per agent
        self.changes = {}            # agent -> (entered, left) since the last summary
        self.last_slot = None

    def handle(self, topic: str, partition: int, event: dict, now: float) -> list:
        """Process one Kafka message; returns (topic, key, event) tuples to publish."""
        if topic.startswith("tool-calls."):
            self.reader.memory.remember(topic, partition, event)
            return []
        violation = self.reader.read(partition, event)
        if violation is None:
            return []
        agent = violation.agent
        monitor = self._monitor(agent)
        change = monitor.add(violation.partition % self.settings.nodes, violation.item, now)
        self._note(agent, change)
        count = monitor.total(violation.item)
        score = events.count_score(agent, violation.item, count, violation.event)
        return [(self.settings.scores_topic, agent, score)]

    def tick(self, now: float) -> list:
        """Called every loop: slides the windows; at each new time slot sends one summary per agent."""
        for agent, monitor in self.monitors.items():
            self._note(agent, monitor.advance(now))
        slot = int(now // self.settings.slot_seconds)
        if slot == self.last_slot:
            return []
        self.last_slot = slot
        output = []
        for agent, monitor in self.monitors.items():
            entered, left = self.changes.pop(agent, (set(), set()))
            summary = events.counts_summary(agent, monitor, now - self.settings.window_seconds, now,
                                            entered, left)
            output.append((self.settings.stats_topic, agent, summary))
        return output

    def _monitor(self, agent: str) -> TopKMonitor:
        if agent not in self.monitors:
            config = self.settings
            self.monitors[agent] = TopKMonitor(config.k, config.nodes, config.slot_seconds,
                                               config.units, config.epsilon)
        return self.monitors[agent]

    def _note(self, agent, change):
        if change is None:
            return
        before, after = change
        entered, left = self.changes.setdefault(agent, (set(), set()))
        entered |= after - before
        left |= before - after
        log.info("agent %s top-k changed: +%s -%s", agent, sorted(after - before), sorted(before - after))
