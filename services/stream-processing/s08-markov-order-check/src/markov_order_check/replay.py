"""Replay harness and evaluator (spec Sec. 9).

In-process (default): feeds a dataset through the pipeline without Kafka, writes
every output (published or not) and prints evaluation metrics.
``--publish``: sends the dataset's events to the agent's Kafka topic instead.

Events are replayed session by session in ``sequence`` order, sessions ordered by
the time of their ``session.started``; never sorted by ``occurred_at`` (Sec. 4.2).

Examples::

    python -m markov_order_check.replay --agent A --dataset-file agent_a_events.jsonl \
        --model-file models/b3-markov-chain/A/<version>/transition_table.json --out replay_a.jsonl
    python -m markov_order_check.replay --agent B --dataset-file scenario_01_500.jsonl --publish
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import Settings
from .detector import MarkovOrderPipeline, Output
from .models import ModelRegistry
from .scoring import MarkovModel


@dataclass
class SessionRecord:
    session_id: str
    events: list[dict[str, Any]]
    category: str | None = None
    attack_type: str | None = None
    label: str | None = None
    start_time: str = ""


@dataclass
class SessionOutcome:
    record: SessionRecord
    n_calls: int = 0
    first_alert: int | str | None = None
    alerts: int = 0
    session_anomaly: bool | None = None
    empty: bool = False
    complete: bool = True
    outputs: list[dict[str, Any]] = field(default_factory=list)


# -- dataset ------------------------------------------------------------------
def read_sessions(path: str | Path) -> list[SessionRecord]:
    """Agent A's wrapped records ({..., "event": {...}}) or flat events (Agent B)."""
    by_session: dict[str, SessionRecord] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # the recorded files may end in a truncated line
            event = record["event"] if isinstance(record.get("event"), dict) else record
            sid = event.get("session_id")
            if not sid:
                continue
            rec = by_session.setdefault(sid, SessionRecord(sid, []))
            rec.events.append(event)
            if "event" in record:
                rec.category = record.get("category", rec.category)
                rec.attack_type = record.get("attack_type", rec.attack_type)
                rec.label = record.get("label", rec.label)
            if event.get("event_type") == "session.started":
                data = event.get("data") or {}
                rec.category = rec.category or data.get("category")
                rec.attack_type = rec.attack_type or data.get("attack_type")
                rec.start_time = event.get("occurred_at") or ""
    sessions = list(by_session.values())
    for rec in sessions:
        seen: set[str] = set()
        unique = []
        for e in rec.events:
            if e.get("event_id") in seen:
                continue  # the datasets contain duplicated sessions
            seen.add(e.get("event_id"))
            unique.append(e)
        rec.events = sorted(unique, key=lambda e: (e.get("sequence") is None, e.get("sequence") or 0))
        if not rec.start_time:
            rec.start_time = min((e.get("occurred_at") or "" for e in rec.events), default="")
    return sorted(sessions, key=lambda r: (r.start_time, r.session_id))


def load_model(path: str | Path, agent: str, key: str | None = None) -> MarkovModel:
    """A model.trained message (data.transition_table) or a bare transition table."""
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    registry = ModelRegistry()
    if "transition_table" in (obj.get("data") or {}):
        message = obj
    else:
        message = {"event_type": "model.trained",
                   "data": {"agent": agent, "version": Path(path).parent.name or "file", "transition_table": obj}}
    message.setdefault("data", {}).setdefault("agent", agent)
    result = registry.load(key or f"b3-markov-chain.{agent}", json.dumps(message))
    if not result.accepted:
        raise SystemExit(f"Cannot use model {path}: {result.reason}")
    return registry.get(agent)


# -- perturbations (Sec. 9.2, robustness) ---------------------------------------
def perturb(events: list[dict[str, Any]], rng: random.Random, *, shuffle: int, duplicate_rate: float,
            drop_rate: float) -> list[dict[str, Any]]:
    out = [e for e in events if not (e.get("event_type", "").startswith("tool_call.") and rng.random() < drop_rate)]
    if duplicate_rate:
        doubled = []
        for e in out:
            doubled.append(e)
            if rng.random() < duplicate_rate:
                doubled.append(e)
        out = doubled
    if shuffle > 0:
        keyed = [(i + rng.uniform(0, shuffle), e) for i, e in enumerate(out)]
        out = [e for _, e in sorted(keyed, key=lambda x: x[0])]
    return out


# -- in-process replay --------------------------------------------------------------
def replay(sessions: list[SessionRecord], model: MarkovModel, settings: Settings, *, seed: int = 0, shuffle: int = 0,
           duplicate_rate: float = 0.0, drop_rate: float = 0.0, restart_at: float | None = None,
           fold_models: dict[str, MarkovModel] | None = None) -> tuple[list[Output], dict[str, SessionOutcome]]:
    rng = random.Random(seed)
    topic = f"tool-calls.{model.agent}"
    outcomes = {r.session_id: SessionOutcome(r) for r in sessions}
    outputs: list[Output] = []

    def new_pipeline(m: MarkovModel) -> MarkovOrderPipeline:
        p = MarkovOrderPipeline(settings)
        p.add_model(m)
        return p

    groups: dict[str, list[SessionRecord]] = defaultdict(list)
    for rec in sessions:
        groups["final" if not fold_models or rec.session_id not in fold_models else rec.session_id].append(rec)
    clock = 0.0
    for group, recs in groups.items():
        pipeline = new_pipeline(model if group == "final" else fold_models[group])
        restart_index = int(len(recs) * restart_at) if restart_at is not None else None
        for i, rec in enumerate(recs):
            events = perturb(rec.events, rng, shuffle=shuffle, duplicate_rate=duplicate_rate, drop_rate=drop_rate)
            if restart_index is not None and i == restart_index and len(events) > 1:
                cut = len(events) // 2
                for e in events[:cut]:
                    clock += 0.01
                    outputs += pipeline.handle_event(topic, e, clock)
                pipeline = new_pipeline(model if group == "final" else fold_models[group])  # state lost
                events = events[cut:]
            for e in events:
                clock += 0.01
                outputs += pipeline.handle_event(topic, e, clock)
        outputs += pipeline.flush()
    for out in outputs:
        sid = out.event["session_id"]
        oc = outcomes.get(sid)
        if oc is None:
            continue
        data = out.event["data"]
        oc.outputs.append({**out.event, "published": out.publish})
        if out.kind == "call":
            oc.alerts += 1
            if oc.first_alert is None:
                oc.first_alert = data.get("call_index")
        elif oc.session_anomaly is None or data.get("complete"):
            oc.session_anomaly = data.get("is_anomaly")
            oc.n_calls = data.get("n_calls", 0)
            oc.empty = bool(data.get("empty_session"))
            oc.complete = bool(data.get("complete"))
    return outputs, outcomes


# -- evaluation ------------------------------------------------------------------
def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def evaluate(outcomes: dict[str, SessionOutcome], s07_flagged: set[str] | None = None) -> dict[str, Any]:
    def summarize(items: list[SessionOutcome]) -> dict[str, Any]:
        call = [o.alerts > 0 for o in items]
        sess = [bool(o.session_anomaly) for o in items]
        union = [a or b for a, b in zip(call, sess)]
        detected = [o for o in items if o.alerts > 0 and isinstance(o.first_alert, int)]
        to_alert = [o.first_alert for o in detected]
        saved = [o.n_calls - o.first_alert for o in detected]
        summary = {
            "sessions": len(items),
            "call_alert_rate": _rate(call),
            "session_flag_rate": _rate(sess),
            "union_rate": _rate(union),
            "median_calls_to_alert": statistics.median(to_alert) if to_alert else None,
            "median_calls_saved": statistics.median(saved) if saved else None,
        }
        if s07_flagged is not None:
            s07 = [o.record.session_id in s07_flagged for o in items]
            summary["s07_only"] = sum(1 for a, b in zip(s07, union) if a and not b)
            summary["s08_only"] = sum(1 for a, b in zip(s07, union) if b and not a)
            summary["both"] = sum(1 for a, b in zip(s07, union) if a and b)
        return summary

    groups: dict[str, list[SessionOutcome]] = defaultdict(list)
    for o in outcomes.values():
        if o.record.category == "normal":
            groups["normal"].append(o)
        else:
            groups[o.record.attack_type or o.record.category or "unknown"].append(o)
    result: dict[str, Any] = {"with_empty": {}, "without_empty": {}}
    for name, items in sorted(groups.items()):
        result["with_empty"][name] = summarize(items)
        non_empty = [o for o in items if not o.empty]
        result["without_empty"][name] = summarize(non_empty)
    return result


def read_s07_flags(path: str | Path) -> set[str]:
    flagged: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                event = json.loads(line)
                if event.get("event_type", "violation.flagged") == "violation.flagged" and event.get("session_id"):
                    flagged.add(event["session_id"])
    return flagged


def read_fold_models(directory: str | Path, dataset_file: str | Path, agent: str,
                     normal_by: str = "category") -> dict[str, MarkovModel]:
    """Map each normal session to the B3 fold model that never saw it (B3 ``--save-fold-models``).

    The fold tables do not list their held-out sessions, but B3's folds are reproducible:
    ``kfold(n_normal, n_folds, seed)`` over the normal sessions in the order B3's own loader
    returns them. Each fold is checked against the ``training.input_sha256`` of its table.
    """
    from b3_markov.adapters import dataset
    from b3_markov.domain.training import input_sha256, kfold
    from b3_markov.main import split_sessions

    loader = dataset.from_agent_a_file if agent == "A" else dataset.from_events_file
    normal, _ = split_sessions(loader(Path(dataset_file)), normal_by)
    paths = sorted(Path(directory).glob("fold_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    if not paths:
        raise SystemExit(f"no fold_<i>.json in {directory}")
    tables = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    seed = int((tables[0].get("training") or {}).get("random_seed", 0))
    mapping: dict[str, MarkovModel] = {}
    for path, table, held_out in zip(paths, tables, kfold(len(normal), len(paths), seed)):
        held = set(held_out)
        train = [s for i, s in enumerate(normal) if i not in held]
        if input_sha256(train) != (table.get("training") or {}).get("input_sha256"):
            raise SystemExit(f"{path.name}: its training sessions do not match {dataset_file}; "
                             "replay the file the fold models were trained on")
        model = MarkovModel(table, version=f"{path.parent.parent.name}/{path.stem}", agent=agent)
        for i in held_out:
            mapping[normal[i].session_id] = model
    return mapping


# -- Kafka publishing -------------------------------------------------------------
def publish(sessions: Iterable[SessionRecord], agent: str, bootstrap: str, speed: float) -> int:
    from confluent_kafka import Producer

    producer = Producer({"bootstrap.servers": bootstrap})
    topic = f"tool-calls.{agent}"
    sent = 0
    for rec in sessions:
        for event in rec.events:
            producer.produce(topic, key=rec.session_id, value=json.dumps(event))
            sent += 1
        producer.poll(0)
        if speed > 0:
            time.sleep(1.0 / speed)
    producer.flush(30)
    return sent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Replay a dataset through the Markov order check")
    parser.add_argument("--agent", choices=["A", "B"], required=True)
    parser.add_argument("--dataset-file", required=True)
    parser.add_argument("--model-file", help="transition_table.json or a model.trained message (in-process mode)")
    parser.add_argument("--fold-models", help="the folds/ directory of a B3 model (B3 --save-fold-models): "
                        "normal sessions are scored by the fold model that never saw them")
    parser.add_argument("--speed", type=float, default=100.0, help="sessions per second when publishing (0 = max)")
    parser.add_argument("--publish", action="store_true", help="publish events to Kafka instead of scoring")
    parser.add_argument("--shuffle", type=int, default=0, help="max displacement of events within a session")
    parser.add_argument("--duplicate-rate", type=float, default=0.0)
    parser.add_argument("--drop-rate", type=float, default=0.0, help="share of tool-call events dropped")
    parser.add_argument("--restart-at", type=float, help="fraction of sessions after which state is lost")
    parser.add_argument("--with-s07-flags", help="JSONL of S07 violation.flagged events for the overlap metric")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", help="write every output (published or not) as JSONL")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    sessions = read_sessions(args.dataset_file)
    if args.publish:
        sent = publish(sessions, args.agent, settings.kafka_bootstrap, args.speed)
        print(f"Published {sent} events of {len(sessions)} sessions to tool-calls.{args.agent}")
        return
    if not args.model_file:
        parser.error("--model-file is required unless --publish is given")
    model = load_model(args.model_file, args.agent)
    folds = read_fold_models(args.fold_models, args.dataset_file, args.agent) if args.fold_models else None
    outputs, outcomes = replay(sessions, model, settings, seed=args.seed, shuffle=args.shuffle,
                               duplicate_rate=args.duplicate_rate, drop_rate=args.drop_rate,
                               restart_at=args.restart_at, fold_models=folds)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for out in outputs:
                fh.write(json.dumps({**out.event, "published": out.publish}) + "\n")
    s07 = read_s07_flags(args.with_s07_flags) if args.with_s07_flags else None
    print(json.dumps({"agent": args.agent, "model_version": model.version, "sessions": len(sessions),
                      "outputs": len(outputs), "metrics": evaluate(outcomes, s07)}, indent=2))


if __name__ == "__main__":
    main()
