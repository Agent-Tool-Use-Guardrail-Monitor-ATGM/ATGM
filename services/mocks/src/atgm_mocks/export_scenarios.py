"""Export scenarios as JSON lines (no Kafka, no database): python -m atgm_mocks.export_scenarios

One line per scenario: the prompt to send to the real agent, the allow-list policy, the rules an
adversarial scenario breaks and `reference_calls`, the tool calls a normal / compromised agent would
make. Use it to (1) feed the prompts to Agent B and check its real traces against your policy, and
(2) unit-test the allow-list checker offline with the reference calls.

    python -m atgm_mocks.export_scenarios --n 500 --attack-rate 0.5 --seed 1 --out scenarios.jsonl
    python -m atgm_mocks.export_scenarios --attack recipient_hijack --n 50     # only that attack

Options: --agent B (only B has prompts and policies)  --n [200]  --attack-rate [0.5]  --seed
         --attack TYPE (every scenario is that attack)  --today YYYY-MM-DD (the agent's "now")  --out FILE
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from datetime import date

from atgm_mocks.domain.sessions import ATTACKS, SessionGenerator

PROJECT_ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = PROJECT_ROOT / "dataset" / "agent_b" / "scenarios"

def scenario_record(s) -> dict:
    return {"scenario_id": s.session_id, "agent": s.agent, "category": s.category,
            "attack_type": s.attack_type, "scenario_kind": s.scenario_kind, "prompt": s.prompt,
            "adversarial_text": s.adversarial_text, "policy": s.policy, "violated_rules": s.violated_rules,
            "expected_behavior": s.expected_behavior,
            "reference_calls": [{"tool": c.tool, "arguments": c.arguments} for c in s.calls]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Export Agent B scenarios as JSON lines")
    ap.add_argument("--agent", default="B", choices=["B"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--attack-rate", type=float, default=0.5)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--attack", choices=ATTACKS["B"])
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    gen = SessionGenerator(random.Random(args.seed), attack_rate=args.attack_rate, today=args.today)
    out = open(OUT_DIR / args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        for _ in range(args.n):
            s = gen.session(args.agent, args.attack) if args.attack else gen.next(args.agent)
            out.write(json.dumps(scenario_record(s), ensure_ascii=False) + "\n")
    finally:
        if args.out:
            out.close()


if __name__ == "__main__":
    main()
