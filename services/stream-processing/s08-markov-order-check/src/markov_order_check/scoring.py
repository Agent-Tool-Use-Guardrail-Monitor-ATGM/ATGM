"""Adapter over the B3 package: the model arithmetic itself lives in ``b3_markov`` (spec Sec. 2).

B3 rebuilds a model from its announced table (``training.from_table``), scores one
transition with ``scoring.step`` and featurizes one call with
``Featurizer.flags_for_call``. This module only adds what the stream needs around
them: table validation, per-agent symbols, call and session thresholds, and the
running form of B3's session scores.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from b3_markov.domain.arguments import ArgContext
from b3_markov.domain.scoring import SCORE_MODES, Detector
from b3_markov.domain.scoring import step as b3_step
from b3_markov.domain.sequences import DELIM, END, START, UNK, context_key
from b3_markov.domain.sessions import Call as B3Call
from b3_markov.domain.training import from_table

SUPPORTED_SPEC_VERSIONS = {"0.1", "0.2", "0.3", "0.4"}
SMOOTHING_METHODS = {"additive", "floor", "backoff"}


class ModelError(ValueError):
    """The transition table cannot be used."""


@dataclass(frozen=True)
class Step:
    lp: float  # natural log-probability of the transition
    count: int  # training count of (state, next)
    state_total: int  # training count of the state as context
    state: str  # state key as in the table


@dataclass(frozen=True)
class ArgumentStep:
    nll: float  # sum of -ln P(value | tool, flag) over the call's flags
    worst_flag: str | None  # the call's most expensive flag, "tool:flag=value" (B3's worst_arg format)
    worst_cost: float
    context: ArgContext  # what this call contributes to the next call's flags


def _per_order(value: Any, order: int) -> float | None:
    """Calibration values are per order ({"1": x, "2": y}) or a single number (v0.1 tables)."""
    if value is None:
        return None
    if isinstance(value, dict):
        v = value.get(str(order), value.get(order))
        return None if v is None else float(v)
    return float(value)


class MarkovModel:
    """One agent's announced B3 model."""

    start, end, unk, delimiter = START, END, UNK, DELIM

    def __init__(self, table: dict[str, Any], *, version: str, agent: str):
        self.table = table
        self.version = version
        self.agent = agent
        self._validate(table)
        try:
            self.detector: Detector = from_table(table)
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelError(f"cannot build the B3 model from the table: {exc!r}") from exc
        self.chain = self.detector.chain
        self.arguments = self.detector.arguments
        self.vocabulary = self.chain.vocabulary
        self._vocab = set(self.vocabulary)
        self.next_symbols = self.vocabulary + [END, UNK]
        self.orders = self.chain.orders
        self.calibration = table.get("calibration") or {}
        # B3 Detector.score: without an argument model the session score is the sequence score
        self.score_kind = self.detector.mode if self.arguments is not None else "seq"

    @staticmethod
    def _validate(table: dict[str, Any]) -> None:
        spec = str(table.get("spec_version", "0.1"))
        if spec not in SUPPORTED_SPEC_VERSIONS:
            raise ModelError(f"unsupported spec_version {spec}")
        model = table.get("model") or {}
        tokens = model.get("tokens") or {}
        expected = {"start": START, "end": END, "unk": UNK}
        if any(tokens.get(k, v) != v for k, v in expected.items()):
            raise ModelError(f"tokens {tokens} differ from B3's {expected}")
        if model.get("state_delimiter", DELIM) != DELIM:
            raise ModelError(f"state delimiter {model.get('state_delimiter')!r} differs from B3's {DELIM!r}")
        method = (model.get("smoothing") or {}).get("method")
        if method not in SMOOTHING_METHODS:
            raise ModelError(f"unknown smoothing method {method}")
        vocabulary = table.get("vocabulary") or []
        if not vocabulary:
            raise ModelError("empty vocabulary")
        for tool in vocabulary:
            if DELIM in tool:
                raise ModelError(f"tool name {tool!r} contains the state delimiter")
        if not table.get("orders"):
            raise ModelError("no orders in table")
        if method == "backoff" and "0" not in table["orders"]:
            raise ModelError("backoff smoothing needs the order-0 counts in the table")
        score = (table.get("scoring") or {}).get("score")
        if score is not None and score not in SCORE_MODES:
            raise ModelError(f"unknown session score {score}")

    # -- symbols and transitions (b3_markov.domain.scoring.step) -------------------
    def symbol(self, tool: str | None) -> str:
        return tool if tool in self._vocab else UNK

    def has_order(self, order: int) -> bool:
        return order in self.orders

    def step(self, order: int, context: tuple[str, ...], symbol: str) -> Step:
        lp, count, total = b3_step(self.chain, order, context, symbol)
        return Step(lp=lp, count=count, state_total=total, state=context_key(context))

    def top_symbols(self, order: int, context: tuple[str, ...], g: int) -> list[str]:
        ranked = sorted(((b3_step(self.chain, order, context, s)[0], s) for s in self.next_symbols),
                        key=lambda x: (-x[0], x[1]))
        return [s for _, s in ranked[:g]]

    # -- arguments (b3_markov.domain.arguments) --------------------------------------
    def argument_step(self, tool: str, arguments: dict[str, Any] | None, occurred_at: str | None,
                      context: ArgContext | None) -> ArgumentStep | None:
        """Flags of one call and their emission cost, as B3's ArgumentModel.score does per call."""
        if self.arguments is None:
            return None
        call = B3Call(tool, arguments if isinstance(arguments, dict) else {}, occurred_at)
        flags, new_context = self.arguments.featurizer.flags_for_call(call, context)
        nll, worst, worst_cost = 0.0, None, 0.0
        for flag, value in flags.items():
            cost = -math.log(self.arguments.prob(tool, flag, value))
            nll += cost
            if cost > worst_cost:
                worst, worst_cost = f"{tool}:{flag}={value}", cost
        return ArgumentStep(nll, worst, worst_cost, new_context)

    # -- calibration ----------------------------------------------------------
    def call_threshold(self, order: int) -> float | None:
        return _per_order(self.calibration.get("call_threshold"), order)

    def session_threshold(self, order: int) -> float | None:
        return _per_order(self.calibration.get("threshold"), order)


def session_score(kind: str, seq_nll_total: float, n_transitions: int, arg_total: float, arg_max: float) -> float:
    """B3's session scores (Detector.score), from the running sums the stream keeps."""
    mean = seq_nll_total / n_transitions if n_transitions else 0.0
    if kind == "seq":
        return mean
    if kind == "args":
        return arg_max
    if kind == "joint_max":
        return mean + arg_max
    return (seq_nll_total + arg_total) / n_transitions if n_transitions else 0.0  # joint
