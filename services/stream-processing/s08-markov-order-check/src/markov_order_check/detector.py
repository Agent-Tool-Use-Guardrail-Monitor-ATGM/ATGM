"""Per-event Markov order check (spec Secs. 4-7). No Kafka import: testable without a broker.

``MarkovOrderPipeline`` routes events to one ``MarkovOrderDetector`` per agent.
Each detector keeps a small state per session, orders calls by
``session_call_index``, decides completeness by the gapless envelope ``sequence``,
checks every transition against the agent's model and emits ``anomaly.scored``
events: call-level ``out_of_order`` alerts (detector ``markov_order``) and one
session score per session (detector ``markov``).
"""

from __future__ import annotations

import json
import logging
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from b3_markov.domain.arguments import ArgContext

from .config import Settings
from .drift import Metrics
from .events import (
    CALL_DETECTOR,
    CALL_RESULT_TYPES,
    SESSION_DETECTOR,
    Call,
    agent_id,
    call_from_result,
    event_type,
    payload,
    scored_event,
    tool_name,
)
from .models import ModelRegistry
from .scoring import MarkovModel, session_score

logger = logging.getLogger(__name__)


@dataclass
class Output:
    """One anomaly.scored event. ``publish`` is False for computed-but-unpublished alerts."""

    kind: str  # "call" | "session"
    agent: str
    event: dict[str, Any]
    publish: bool


@dataclass
class SessionState:
    agent: str
    session_id: str
    model: MarkovModel
    order: int
    known_start: bool
    run_id: str | None = None
    awaiting_start: bool = False
    opened_at: float = 0.0
    context: list[str] = field(default_factory=list)
    complete: bool = True
    # call ordering (session_call_index)
    next_index: int = 1
    pending: dict[int, Call] = field(default_factory=dict)
    pending_unindexed: list[Call] = field(default_factory=list)
    pending_since: float | None = None
    # completeness (envelope sequence)
    next_seq: int | None = None
    seen_seq: set[int] = field(default_factory=set)
    end_seq: int | None = None
    end_seen: bool = False
    end_time: float | None = None
    end_event_id: str | None = None
    end_occurred_at: str | None = None
    # dedupe and request/result join
    seen_event_ids: set[str] = field(default_factory=set)
    seen_call_ids: set[str] = field(default_factory=set)
    requested: dict[str, str | None] = field(default_factory=dict)
    # running sums for the session score
    seq_nll: float = 0.0
    n_transitions: int = 0
    n_unseen: int = 0
    min_lp: float = math.inf
    worst_transition: dict[str, Any] | None = None
    arg_total: float = 0.0
    arg_max: float = 0.0
    worst_arg: str | None = None
    worst_arg_cost: float = 0.0
    arg_ctx: ArgContext = field(default_factory=ArgContext)
    n_calls: int = 0
    last_symbol: str | None = None
    run_length: int = 0
    max_run_length: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)
    # bookkeeping
    last_event_time: float = 0.0
    last_event_id: str | None = None
    last_sequence: int | None = None
    last_occurred_at: str | None = None

    def reset_context_unknown(self) -> None:
        """After lost events: the next ``order`` transitions are not checked (Sec. 4.2)."""
        self.context = []
        self.complete = False

    def advance_seq(self) -> None:
        if self.next_seq is None:
            return
        while self.next_seq in self.seen_seq:
            self.next_seq += 1

    def all_seen_through_end(self) -> bool:
        if self.end_seq is None or self.next_seq is None:
            return True
        return self.next_seq > self.end_seq


class MarkovOrderDetector:
    """All sessions of one agent."""

    def __init__(self, agent: str, settings: Settings, registry: ModelRegistry, metrics: Metrics):
        self.agent = agent
        self.settings = settings
        self.registry = registry
        self.metrics = metrics
        self.sessions: dict[str, SessionState] = {}
        self.closed: OrderedDict[str, None] = OrderedDict()
        self._order_warned: set[str] = set()

    # -- public API -----------------------------------------------------------
    def process(self, event: dict[str, Any], now: float) -> list[Output]:
        session_id = event.get("session_id")
        if not session_id:
            return []
        if session_id in self.closed:
            self.metrics.inc(self.agent, "late_event")
            return []
        etype = event_type(event)
        sess = self.sessions.get(session_id)
        out: list[Output] = []
        if sess is None:
            model = self.registry.get(self.agent)
            if model is None:
                self.metrics.inc(self.agent, "unscored_no_model")
                return []
            if len(self.sessions) >= self.settings.max_sessions:
                out += self._evict_oldest(now)
            sess = self._open(session_id, model, event, now)
        if not self._accept(sess, event):
            self.metrics.inc(self.agent, "duplicate", sess.model.version)
            return out
        sess.last_event_time = now
        sess.last_event_id = event.get("event_id")
        sess.last_sequence = event.get("sequence") if event.get("sequence") is not None else sess.last_sequence
        sess.last_occurred_at = event.get("occurred_at")
        sess.run_id = sess.run_id or event.get("run_id")
        data = payload(event)
        if etype == "session.started" and not sess.known_start and sess.awaiting_start:
            self._late_start(sess, event)
        elif etype == "tool_call.requested":
            tcid = data.get("tool_call_id")
            if tcid:
                sess.requested[str(tcid)] = tool_name(data)
        elif etype in CALL_RESULT_TYPES:
            tcid = str(data["tool_call_id"]) if data.get("tool_call_id") else None
            if tcid and tcid in sess.seen_call_ids:
                self.metrics.inc(self.agent, "duplicate", sess.model.version)
            else:
                if tcid:
                    sess.seen_call_ids.add(tcid)
                self._enqueue(sess, call_from_result(event, sess.requested.get(tcid or "")), now)
        elif etype == "session.ended":
            sess.end_seen = True
            sess.end_seq = event.get("sequence")
            sess.end_time = now
            sess.end_event_id = event.get("event_id")
            sess.end_occurred_at = event.get("occurred_at")
        out += self._drain(sess)
        out += self._maybe_close(sess)
        return out

    def tick(self, now: float) -> list[Output]:
        """Handle timeouts: lost calls, sessions waiting to close, idle sessions."""
        out: list[Output] = []
        timeout = self.settings.reorder_timeout_s
        for sess in list(self.sessions.values()):
            if sess.awaiting_start and now - sess.opened_at > timeout:
                self._start_unknown(sess)
                out += self._drain(sess)
            if (sess.pending or sess.pending_unindexed) and sess.pending_since is not None and (
                now - sess.pending_since > timeout
            ):
                out += self._declare_lost(sess)
            if sess.end_seen and sess.end_time is not None and now - sess.end_time > timeout:
                if sess.pending or sess.pending_unindexed:
                    out += self._declare_lost(sess)
                if not sess.all_seen_through_end():
                    sess.complete = False
                    self.metrics.inc(self.agent, "gap", sess.model.version)
                out += self._close(sess, idle=False)
                continue
            if now - sess.last_event_time > self.settings.idle_timeout_s:
                self.metrics.inc(self.agent, "timeout", sess.model.version)
                out += self._close(sess, idle=True)
        return out

    def flush(self) -> list[Output]:
        """Close every open session as if all timeouts had passed (end of a replay)."""
        out: list[Output] = []
        for sess in list(self.sessions.values()):
            if sess.awaiting_start:
                self._start_unknown(sess)
                out += self._drain(sess)
            if sess.pending or sess.pending_unindexed:
                out += self._declare_lost(sess)
            if sess.end_seen:
                if not sess.all_seen_through_end():
                    sess.complete = False
                out += self._close(sess, idle=False)
            else:
                self.metrics.inc(self.agent, "timeout", sess.model.version)
                out += self._close(sess, idle=True)
        return out

    # -- session lifecycle ----------------------------------------------------
    def _resolve_order(self, model: MarkovModel) -> int:
        order = self.settings.order_for(self.agent)
        if model.has_order(order):
            return order
        fallback = max(o for o in model.orders if o <= order) if any(o <= order for o in model.orders) else min(
            model.orders)
        if model.version not in self._order_warned:
            logger.warning("Order %s not in model %s of agent %s; using %s", order, model.version, self.agent,
                           fallback)
            self._order_warned.add(model.version)
        return fallback

    def _open(self, session_id: str, model: MarkovModel, event: dict[str, Any], now: float) -> SessionState:
        order = self._resolve_order(model)
        known = event_type(event) == "session.started"
        sess = SessionState(agent=self.agent, session_id=session_id, model=model, order=order, known_start=known,
                            run_id=event.get("run_id"), last_event_time=now)
        sess.opened_at = now
        if known:
            sess.context = [model.start] * order
        else:
            # session.started may still be on its way (delivery disorder): hold calls until it
            # arrives or reorder_timeout passes; then the context is unknown (Sec. 4.4).
            sess.awaiting_start = True
        seq = event.get("sequence")
        sess.next_seq = 1 if seq is not None else None  # session.started has sequence 1
        self.sessions[session_id] = sess
        self.metrics.inc(self.agent, "sessions", model.version)
        return sess

    def _late_start(self, sess: SessionState, event: dict[str, Any]) -> None:
        """session.started delivered after another event of the session, before any call."""
        sess.known_start = True
        sess.awaiting_start = False
        sess.context = [sess.model.start] * sess.order
        seq = event.get("sequence")
        if seq is not None:
            sess.next_seq = int(seq)
            sess.advance_seq()

    def _accept(self, sess: SessionState, event: dict[str, Any]) -> bool:
        eid = event.get("event_id")
        if eid:
            if eid in sess.seen_event_ids:
                return False
            sess.seen_event_ids.add(eid)
        seq = event.get("sequence")
        if seq is not None:
            seq = int(seq)
            if seq in sess.seen_seq:
                return False
            sess.seen_seq.add(seq)
            if sess.next_seq is None or (seq < sess.next_seq and event_type(event) == "session.started"):
                sess.next_seq = seq
            sess.advance_seq()
        return True

    def _evict_oldest(self, now: float) -> list[Output]:
        oldest = min(self.sessions.values(), key=lambda s: s.last_event_time)
        self.metrics.inc(self.agent, "evicted", oldest.model.version)
        return self._close(oldest, idle=True)

    # -- call ordering ----------------------------------------------------------
    def _enqueue(self, sess: SessionState, call: Call, now: float) -> None:
        if call.call_index is None:
            sess.pending_unindexed.append(call)
            sess.pending_unindexed.sort(key=lambda c: (c.sequence is None, c.sequence or 0))
        else:
            if call.call_index < sess.next_index or call.call_index in sess.pending:
                self.metrics.inc(self.agent, "duplicate", sess.model.version)
                return
            sess.pending[call.call_index] = call
        if sess.pending_since is None:
            sess.pending_since = now

    def _start_unknown(self, sess: SessionState) -> None:
        """Give up waiting for session.started: the first `order` transitions are not checked."""
        sess.awaiting_start = False
        sess.reset_context_unknown()

    def _drain(self, sess: SessionState) -> list[Output]:
        out: list[Output] = []
        if sess.awaiting_start:
            return out
        while sess.next_index in sess.pending:
            out += self._process_call(sess, sess.pending.pop(sess.next_index))
            sess.next_index += 1
        while sess.pending_unindexed:
            call = sess.pending_unindexed[0]
            ready = call.sequence is None or sess.next_seq is None or sess.next_seq > call.sequence
            if not ready:
                break
            sess.pending_unindexed.pop(0)
            out += self._process_call(sess, call)
            sess.next_index = max(sess.next_index, sess.n_calls + 1)
        if not sess.pending and not sess.pending_unindexed:
            sess.pending_since = None
        return out

    def _declare_lost(self, sess: SessionState) -> list[Output]:
        """A call gap stayed open past the timeout: skip it with an unknown context."""
        self.metrics.inc(self.agent, "gap", sess.model.version)
        sess.reset_context_unknown()
        out: list[Output] = []
        for idx in sorted(sess.pending):
            if idx != sess.next_index:
                sess.reset_context_unknown()
            out += self._process_call(sess, sess.pending.pop(idx))
            sess.next_index = idx + 1
        for call in sess.pending_unindexed:
            out += self._process_call(sess, call)
        sess.pending_unindexed.clear()
        sess.pending_since = None
        return out

    def _maybe_close(self, sess: SessionState) -> list[Output]:
        if not sess.end_seen or sess.pending or sess.pending_unindexed or sess.awaiting_start:
            return []
        if not sess.all_seen_through_end():
            return []
        return self._close(sess, idle=False)

    # -- transitions and checks -------------------------------------------------
    def _transition(self, sess: SessionState, symbol: str, check: bool) -> dict[str, Any] | None:
        """Score one transition; return the violation dict if the check fires."""
        model, order = sess.model, sess.order
        if len(sess.context) < order:
            sess.context.append(symbol)
            return None  # unknown context: not scored and not checked
        ctx = tuple(sess.context[-order:])
        step = model.step(order, ctx, symbol)
        sess.seq_nll += -step.lp
        sess.n_transitions += 1
        if step.count == 0:
            sess.n_unseen += 1
        transition = {"state": step.state, "next": symbol, "count": step.count, "state_total": step.state_total,
                      "p": round(math.exp(step.lp), 6)}
        if step.lp < sess.min_lp:
            sess.min_lp = step.lp
            sess.worst_transition = transition
        sess.context = (sess.context + [symbol])[-order:]
        if not check:
            return None
        tau = model.call_threshold(order)
        rule = self.settings.rule
        if rule == "threshold" and tau is None:
            rule = "unseen"  # v0.2 table without call_threshold (Sec. 6, fallback)
        if rule == "threshold":
            fired = step.lp < tau
        elif rule == "unseen":
            fired = step.count == 0
        else:
            fired = symbol not in model.top_symbols(order, ctx, self.settings.top_g)
        if not fired:
            return None
        return {"lp": step.lp, "tau": tau if rule == "threshold" else None, "rule": rule, "transition": transition}

    def _call_alert(self, sess: SessionState, violation: dict[str, Any], *, call_index: Any, sequence: Any,
                    scored_event_id: str | None, occurred_at: str | None) -> Output:
        model = sess.model
        self.metrics.inc(self.agent, "out_of_order", model.version)
        tau = violation["tau"]
        extra = {
            "scope": "call",
            "check": "out_of_order",
            "threshold": None if tau is None else round(-tau, 6),
            "is_anomaly": True,
            "rule": violation["rule"],
            "order": sess.order,
            "call_index": call_index,
            "transition": violation["transition"],
        }
        event = scored_event(
            detector=CALL_DETECTOR, agent=self.agent, session_id=sess.session_id, run_id=sess.run_id,
            sequence=sequence, scored_event_id=scored_event_id, model_version=model.version,
            score=-violation["lp"], id_parts=(sess.session_id, call_index, "out_of_order", model.version),
            extra=extra, scored_event_occurred_at=occurred_at,
        )
        sess.violations.append({"call_index": call_index, "check": "out_of_order",
                                "score": round(-violation["lp"], 6)})
        return Output("call", self.agent, event, self.settings.call_alerts_for(self.agent))

    def _process_call(self, sess: SessionState, call: Call) -> list[Output]:
        model = sess.model
        sess.n_calls += 1
        self.metrics.inc(self.agent, "calls", model.version)
        symbol = model.symbol(call.tool_name)
        if symbol == sess.last_symbol:
            sess.run_length += 1
        else:
            sess.last_symbol, sess.run_length = symbol, 1
        sess.max_run_length = max(sess.max_run_length, sess.run_length)
        if call.tool_name:
            arg = model.argument_step(call.tool_name, call.arguments, call.occurred_at, sess.arg_ctx)
            if arg is not None:  # Agent B: B3 argument flags of this call (B3 Sec. 13)
                sess.arg_ctx = arg.context
                sess.arg_total += arg.nll
                sess.arg_max = max(sess.arg_max, arg.nll)
                if arg.worst_flag and arg.worst_cost > sess.worst_arg_cost:
                    sess.worst_arg, sess.worst_arg_cost = arg.worst_flag, arg.worst_cost
        violation = self._transition(sess, symbol, check=True)
        if violation is None:
            return []
        index = call.call_index if call.call_index is not None else sess.n_calls
        return [self._call_alert(sess, violation, call_index=index, sequence=call.sequence,
                                 scored_event_id=call.event_id, occurred_at=call.occurred_at)]

    # -- closing ----------------------------------------------------------------
    def _close(self, sess: SessionState, *, idle: bool) -> list[Output]:
        self.sessions.pop(sess.session_id, None)
        self.closed[sess.session_id] = None
        while len(self.closed) > max(self.settings.max_sessions, 1000):
            self.closed.popitem(last=False)
        model = sess.model
        empty = sess.n_calls == 0
        policy = self.settings.empty_policy_for(self.agent) if empty and not idle else "alert"
        if empty and not idle:
            self.metrics.inc(self.agent, "empty_sessions", model.version)
            if policy == "drop":
                return []
        out: list[Output] = []
        if idle:
            sess.complete = False
        else:
            violation = self._transition(sess, model.end, check=(policy == "alert"))
            if violation is not None:
                out.append(self._call_alert(
                    sess, violation, call_index="END", sequence=sess.end_seq, scored_event_id=sess.end_event_id,
                    occurred_at=sess.end_occurred_at))
        out.append(self._session_event(sess, idle=idle, tagged_empty=(empty and not idle and policy == "tag")))
        return out

    def _session_event(self, sess: SessionState, *, idle: bool, tagged_empty: bool) -> Output:
        model = sess.model
        has_args = model.arguments is not None
        kind = model.score_kind
        score = session_score(kind, sess.seq_nll, sess.n_transitions, sess.arg_total, sess.arg_max)
        threshold = model.session_threshold(sess.order)
        if tagged_empty:
            is_anomaly: bool | None = False
        elif threshold is None:
            is_anomaly = None
        else:
            is_anomaly = score > threshold
        if is_anomaly:
            self.metrics.inc(self.agent, "session_flags", model.version)
        seq_score = sess.seq_nll / sess.n_transitions if sess.n_transitions else 0.0
        extra = {
            "scope": "session",
            "check": "session_score",
            "score_kind": kind,
            "threshold": threshold,
            "is_anomaly": is_anomaly,
            "order": sess.order,
            "seq_score": seq_score,
            "arg_score": sess.arg_total if has_args else None,
            "arg_max": sess.arg_max if has_args else None,
            "worst_arg": sess.worst_arg if has_args else None,
            "n_unseen": sess.n_unseen,
            "min_p": math.exp(sess.min_lp) if sess.n_transitions else None,
            "worst_transition": sess.worst_transition,
            "n_calls": sess.n_calls,
            "max_run_length": sess.max_run_length,
            "empty_session": sess.n_calls == 0 and not idle,
            "complete": sess.complete and not idle,
            "violations": sess.violations,
        }
        event = scored_event(
            detector=SESSION_DETECTOR, agent=self.agent, session_id=sess.session_id, run_id=sess.run_id,
            sequence=sess.end_seq if sess.end_seen else sess.last_sequence,
            scored_event_id=sess.end_event_id if sess.end_seen else sess.last_event_id,
            model_version=model.version, score=score,
            id_parts=(sess.session_id, "session", "session_score", model.version), extra=extra,
            scored_event_occurred_at=sess.end_occurred_at if sess.end_seen else sess.last_occurred_at,
        )
        self.metrics.session_score(self.agent, model.version, score)
        return Output("session", self.agent, event, True)


class MarkovOrderPipeline:
    """Routes model messages and tool-call events; one detector per agent with a model."""

    def __init__(self, settings: Settings | None = None, registry: ModelRegistry | None = None,
                 metrics: Metrics | None = None):
        self.settings = settings or Settings()
        self.registry = registry or ModelRegistry(self.settings.model_key_prefix)
        self.metrics = metrics or Metrics(self.settings.ph_delta, self.settings.ph_lambda)
        self.detectors: dict[str, MarkovOrderDetector] = {}

    def handle_model(self, key: str | bytes | None, value: Any):
        if isinstance(key, (bytes, bytearray)):
            key = key.decode("utf-8")
        if key is not None and not self.registry.is_model_key(key):
            return None  # another model's message on the shared topic
        result = self.registry.load(key, value)
        if result.accepted and result.agent not in self.detectors:
            self.detectors[result.agent] = MarkovOrderDetector(result.agent, self.settings, self.registry,
                                                               self.metrics)
        return result

    def add_model(self, model: MarkovModel) -> None:
        """Install an already-built model (replay and tests)."""
        self.registry.put(model)
        if model.agent not in self.detectors:
            self.detectors[model.agent] = MarkovOrderDetector(model.agent, self.settings, self.registry,
                                                              self.metrics)

    def handle_event(self, topic: str, value: Any, now: float) -> list[Output]:
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        event = json.loads(value) if isinstance(value, str) else value
        if not isinstance(event, dict):
            raise ValueError("Kafka event must be a JSON object")
        agent = agent_id(event, topic)
        detector = self.detectors.get(agent)
        if detector is None:
            self.metrics.inc(agent, "unscored_no_model")
            return []
        return detector.process(event, now)

    def tick(self, now: float) -> list[Output]:
        out: list[Output] = []
        for detector in self.detectors.values():
            out += detector.tick(now)
        return out

    def flush(self) -> list[Output]:
        out: list[Output] = []
        for detector in self.detectors.values():
            out += detector.flush()
        return out
