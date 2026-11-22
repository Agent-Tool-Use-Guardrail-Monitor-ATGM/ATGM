"""Default tunables of the Markov order check (spec Secs. 4-8, 10.2).

Every value can be overridden by the environment variable of the same name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

AGENTS = ("A", "B")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap: str = "localhost:29092"
    kafka_group_id: str = "markov-order-check"
    topics: tuple[str, ...] = ("tool-calls.A", "tool-calls.B")
    model_topic: str = "model-updates"
    scores_topic: str = "scores"
    model_key_prefix: str = "b3-markov-chain"
    order: dict[str, int] = field(default_factory=lambda: {"A": 1, "B": 2})
    rule: str = "threshold"  # threshold | unseen | topg
    top_g: int = 2
    reorder_timeout_s: float = 5.0
    idle_timeout_s: float = 1800.0
    model_bootstrap_timeout_s: float = 15.0
    ph_delta: float = 0.05
    ph_lambda: float = 50.0
    max_sessions: int = 10000
    call_alerts: dict[str, bool] = field(default_factory=lambda: {"A": False, "B": True})
    empty_session: dict[str, str] = field(default_factory=lambda: {"A": "alert", "B": "tag"})

    @classmethod
    def from_env(cls) -> "Settings":
        d = cls()
        rule = _env("MARKOV_RULE", d.rule)
        if rule not in {"threshold", "unseen", "topg"}:
            raise ValueError(f"MARKOV_RULE must be threshold, unseen or topg, not {rule!r}")
        empty = {a: _env(f"MARKOV_EMPTY_SESSION_{a}", d.empty_session[a]) for a in AGENTS}
        for agent, policy in empty.items():
            if policy not in {"alert", "tag", "drop"}:
                raise ValueError(f"MARKOV_EMPTY_SESSION_{agent} must be alert, tag or drop")
        return cls(
            kafka_bootstrap=_env("KAFKA_BOOTSTRAP", d.kafka_bootstrap),
            kafka_group_id=_env("KAFKA_GROUP_ID", d.kafka_group_id),
            topics=tuple(t.strip() for t in _env("TOPICS", ",".join(d.topics)).split(",") if t.strip()),
            model_topic=_env("MODEL_TOPIC", d.model_topic),
            scores_topic=_env("SCORES_TOPIC", d.scores_topic),
            order={a: int(_env(f"MARKOV_ORDER_{a}", str(d.order[a]))) for a in AGENTS},
            rule=rule,
            top_g=int(_env("MARKOV_TOPG", str(d.top_g))),
            reorder_timeout_s=float(_env("MARKOV_REORDER_TIMEOUT_S", str(d.reorder_timeout_s))),
            idle_timeout_s=float(_env("MARKOV_IDLE_TIMEOUT_S", str(d.idle_timeout_s))),
            model_bootstrap_timeout_s=float(
                _env("MARKOV_MODEL_BOOTSTRAP_TIMEOUT_S", str(d.model_bootstrap_timeout_s))
            ),
            ph_delta=float(_env("MARKOV_PH_DELTA", str(d.ph_delta))),
            ph_lambda=float(_env("MARKOV_PH_LAMBDA", str(d.ph_lambda))),
            max_sessions=int(_env("MAX_SESSIONS", str(d.max_sessions))),
            call_alerts={
                a: _bool(_env(f"MARKOV_CALL_ALERTS_{a}", str(d.call_alerts[a]).lower())) for a in AGENTS
            },
            empty_session=empty,
        )

    def order_for(self, agent: str) -> int:
        return self.order.get(agent, 1)

    def call_alerts_for(self, agent: str) -> bool:
        return self.call_alerts.get(agent, True)

    def empty_policy_for(self, agent: str) -> str:
        return self.empty_session.get(agent, "alert")
