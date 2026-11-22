"""Build tests/fixtures/agent_a_real.jsonl from a recorded Agent A dataset (agent-run-events-v2, one JSON
object per line: {"event": {...}, "category", "scenario_id", "label", "attack_type", ...}).

    python tests/fixtures/build_agent_a_real.py path/to/dataset.jsonl [tests/fixtures/agent_a_real.jsonl]

Keeps only what the allow-list reads (tool name, argument features, outcome, ids) plus the labels the tests
report on. Model-call events, token usage, latencies, hashes and config references are dropped.
"""
import json
import sys
from pathlib import Path

KEEP_TYPES = {"session.started", "tool_call.requested", "tool_call.completed", "tool_call.failed", "session.ended"}


def slim(row: dict) -> dict | None:
    event = row["event"]
    kind, data = event["event_type"], event["data"]
    if kind not in KEEP_TYPES:
        return None
    out: dict = {}
    if kind == "tool_call.requested":
        out = {k: data[k] for k in ("kind", "name", "features", "tool_call_id", "session_call_index") if k in data}
    elif kind in ("tool_call.completed", "tool_call.failed"):
        out = {k: data[k] for k in ("status", "reason", "tool_call_id", "session_call_index") if k in data}
        evaluation = data.get("policy_evaluation")
        if evaluation:
            out["policy_evaluation"] = {"status": evaluation.get("status"),
                                        "reason": (evaluation.get("decision") or {}).get("reason")}
    elif kind == "session.ended":
        out = {"outcome": data.get("outcome")}
    return {"scenario_id": row["scenario_id"], "category": row["category"], "attack_type": row["attack_type"],
            "label": row["label"],
            "event": {"schema_version": event["schema_version"], "event_id": event["event_id"],
                      "event_type": kind, "occurred_at": event["occurred_at"], "run_id": event["run_id"],
                      "session_id": event["session_id"], "sequence": event["sequence"], "data": out}}


def main() -> None:
    source = Path(sys.argv[1])
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).with_name("agent_a_real.jsonl")
    with source.open(encoding="utf-8") as src, target.open("w", encoding="utf-8", newline="\n") as dst:
        for line in src:
            if line.strip() and (row := slim(json.loads(line))) is not None:
                dst.write(json.dumps(row, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
