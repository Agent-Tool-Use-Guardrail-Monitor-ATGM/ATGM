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
    epsilon: float = 1.0
    stats_every: float = 60.0
    alert_topic: str = "alerts"
    flag_topic: str = "flags"
    output_topic: str = "flags"


class TopKService:
    def __init__(self, settings: Settings, reader: ViolationReader):
        self.settings = settings
        self.reader = reader
        self.monitors = {}           # one monitor per agent
        self.last_stats = None

    def handle(self, topic: str, partition: int, event: dict, now: float) -> list:
        """Process one Kafka message; returns (topic, key, event) tuples to publish."""
        if topic.startswith("tool-calls."):
            self.reader.memory.remember(topic, partition, event)
            return []
        if topic == self.settings.alert_topic:
            violation = self.reader.from_alarm(partition, event)
        elif topic == self.settings.flag_topic:
            violation = self.reader.from_flag(partition, event)
        else:
            violation = None
        if violation is None:
            return []
        monitor = self._monitor(violation.agent)
        node_number = violation.partition % self.settings.nodes
        change = monitor.add(node_number, violation.item, now)
        return self._alert(violation.agent, monitor, change)

    def tick(self, now: float) -> list:
        """Called every loop: slides the windows and sends stats now and then."""
        output = []
        for agent, monitor in self.monitors.items():
            output += self._alert(agent, monitor, monitor.advance(now))
        if self.last_stats is None or now - self.last_stats >= self.settings.stats_every:
            self.last_stats = now
            for agent, monitor in self.monitors.items():
                output.append((self.settings.output_topic, agent, events.topk_stats(agent, monitor)))
        return output

    def _monitor(self, agent: str) -> TopKMonitor:
        if agent not in self.monitors:
            config = self.settings
            self.monitors[agent] = TopKMonitor(config.k, config.nodes, config.slot_seconds,
                                               config.units, config.epsilon)
        return self.monitors[agent]

    def _alert(self, agent, monitor, change) -> list:
        if change is None:
            return []
        before, after = change
        entered, left = after - before, before - after
        log.info("agent %s top-k changed: +%s -%s", agent, sorted(entered), sorted(left))
        event = events.topk_changed(agent, entered, left, monitor.ranking())
        return [(self.settings.output_topic, agent, event)]