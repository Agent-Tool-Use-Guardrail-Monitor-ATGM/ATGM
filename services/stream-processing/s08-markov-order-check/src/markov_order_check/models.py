"""Per-agent model registry: loads and validates model.trained messages (spec Sec. 8).

Keys: ``b3-markov-chain.A`` / ``b3-markov-chain.B`` (B3 v0.4). The legacy key
``b3-markov-chain`` without an agent (B3 up to v0.3, trained on Agent B's data)
is accepted as Agent B's model.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .scoring import MarkovModel, ModelError

logger = logging.getLogger(__name__)

LEGACY_AGENT = "B"


@dataclass
class LoadResult:
    accepted: bool
    agent: str | None
    version: str | None
    reason: str = ""


def _decode(value: Any) -> dict[str, Any]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ModelError("model message is not a JSON object")
    return value


def agent_from_key(key: str | None, prefix: str) -> str | None:
    if not key:
        return None
    if key == prefix:
        return LEGACY_AGENT
    if key.startswith(prefix + "."):
        return key[len(prefix) + 1 :] or None
    return None


def parse_model_message(key: str | None, value: Any, prefix: str = "b3-markov-chain") -> MarkovModel:
    """Build a MarkovModel from one model-updates message, or raise ModelError."""
    message = _decode(value)
    if message.get("event_type", "model.trained") != "model.trained":
        raise ModelError(f"not a model.trained message: {message.get('event_type')}")
    data = message.get("data") if isinstance(message.get("data"), dict) else message
    key_agent = agent_from_key(key, prefix)
    data_agent = data.get("agent")
    if key is not None and key_agent is None:
        raise ModelError(f"key {key!r} is not a {prefix} model key")
    if data_agent and key_agent and key != prefix and data_agent != key_agent:
        raise ModelError(f"data.agent {data_agent!r} does not match key {key!r}")
    agent = data_agent or key_agent or LEGACY_AGENT
    table = data.get("transition_table")
    if not isinstance(table, dict):
        raise ModelError("message has no embedded transition_table")
    version = str(data.get("version") or table.get("training", {}).get("trained_at") or "unknown")
    return MarkovModel(table, version=version, agent=agent)


class ModelRegistry:
    """Newest valid model per agent. An invalid message never replaces a valid model."""

    def __init__(self, prefix: str = "b3-markov-chain"):
        self.prefix = prefix
        self._models: dict[str, MarkovModel] = {}

    def is_model_key(self, key: str | None) -> bool:
        return agent_from_key(key, self.prefix) is not None

    def load(self, key: str | None, value: Any) -> LoadResult:
        try:
            model = parse_model_message(key, value, self.prefix)
        except (ModelError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.error("Rejected model message key=%s: %s", key, exc)
            return LoadResult(False, agent_from_key(key, self.prefix), None, str(exc))
        self._models[model.agent] = model
        logger.info("Loaded model agent=%s version=%s", model.agent, model.version)
        return LoadResult(True, model.agent, model.version)

    def put(self, model: MarkovModel) -> None:
        self._models[model.agent] = model

    def get(self, agent: str) -> MarkovModel | None:
        return self._models.get(agent)

    def agents(self) -> list[str]:
        return sorted(self._models)
