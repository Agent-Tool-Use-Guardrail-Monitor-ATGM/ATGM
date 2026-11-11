"""Review queue with a simulated reviewer (pure Python, time is passed in).

Items arrive from the `review-queue` topic: `alarm.raised` (DSPOT) or `decision.made` (ACI)
with decision "review" or marked as a random audit (`audit: true`). The simulated reviewer
answers each item after `delay` seconds, using the scenario ground truth:

    session was an attack  -> verdict "attack", violation_type = the attack type
    session was normal     -> verdict "false_alarm"

A session is judged once; further alarms of the same session get the same verdict.
With `error_rate` > 0 the reviewer sometimes gets a session wrong (human mistakes).
If the ground truth is not there yet, the item is retried a few times, then dropped.
"""
from __future__ import annotations

import heapq
import itertools
import random
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Truth:
    category: str                 # "normal" | "adversarial"
    attack_type: str | None


@dataclass(frozen=True)
class Item:
    scored_event_id: str
    detector: str
    session_id: str
    agent_id: str | None
    run_id: str | None


@dataclass(frozen=True)
class Label:
    item: Item
    verdict: str                  # "attack" | "false_alarm"
    violation_type: str | None


def parse_item(msg: dict) -> Item | None:
    """The reviewable item in a review-queue message, or None if it needs no review."""
    kind = msg.get("event_type")
    data = msg.get("data")
    if not isinstance(data, dict):
        raise ValueError("message has no data object")
    if kind == "decision.made" and data.get("decision") != "review" and data.get("audit") is not True:
        return None                                   # pass / flag decisions are reviewed only as audits
    if kind not in ("alarm.raised", "decision.made"):
        return None
    try:
        return Item(str(data["scored_event_id"]), str(data["detector"]), str(msg["session_id"]),
                    data.get("agent_id"), msg.get("run_id"))
    except KeyError as e:
        raise ValueError(f"missing field {e}") from None


class ReviewQueue:
    def __init__(self, truth: Callable[[str], Truth | None], delay: float = 10.0,
                 error_rate: float = 0.0, retries: int = 5, rng: random.Random | None = None,
                 max_sessions: int = 50_000) -> None:
        if delay < 0 or not 0 <= error_rate <= 1 or retries < 0:
            raise ValueError("need delay >= 0, error_rate in [0, 1], retries >= 0")
        self.truth, self.delay, self.error_rate, self.retries = truth, delay, error_rate, retries
        self.rng = rng or random.Random()
        self.max_sessions = max_sessions
        self._heap: list[tuple[float, int, Item, int]] = []      # (due time, tie, item, attempt)
        self._tie = itertools.count()
        self._judged: OrderedDict[str, tuple[str, str | None]] = OrderedDict()
        self.dropped = 0

    def __len__(self) -> int:
        return len(self._heap)

    def submit(self, item: Item, now: float) -> None:
        heapq.heappush(self._heap, (now + self.delay, next(self._tie), item, 0))

    def due(self, now: float) -> list[Label]:
        """Labels for every item whose review time has come."""
        labels = []
        while self._heap and self._heap[0][0] <= now:
            _, _, item, attempt = heapq.heappop(self._heap)
            judged = self._judge(item.session_id)
            if judged is None:
                if attempt < self.retries:                       # ground truth may arrive late
                    heapq.heappush(self._heap, (now + max(self.delay, 1.0), next(self._tie), item, attempt + 1))
                else:
                    self.dropped += 1
                continue
            labels.append(Label(item, *judged))
        return labels

    def _judge(self, session_id: str) -> tuple[str, str | None] | None:
        if session_id in self._judged:
            return self._judged[session_id]
        t = self.truth(session_id)
        if t is None:
            return None
        attack = t.category == "adversarial"
        if self.rng.random() < self.error_rate:
            attack = not attack                                   # reviewer mistake
        verdict = ("attack", t.attack_type or "unknown") if attack else ("false_alarm", None)
        self._judged[session_id] = verdict
        if len(self._judged) > self.max_sessions:
            self._judged.popitem(last=False)
        return verdict
