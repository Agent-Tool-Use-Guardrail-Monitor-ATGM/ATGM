"""Loads the ground truth of an Agent B dataset into scenario_db.ground_truth.

Load it before replaying the events (event_publisher.py)
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATASET_DIR = PROJECT_ROOT / "dataset" / "agent_b"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ground_truth (
    scenario_id       TEXT PRIMARY KEY,
    agent             TEXT NOT NULL,
    category          TEXT NOT NULL CHECK (category IN ('normal', 'adversarial')),
    attack_type       TEXT,
    expected_tools    JSONB NOT NULL,
    expected_behavior TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
)"""
EXTRA_COLUMNS = ("scenario_kind TEXT", "prompt TEXT", "adversarial_text TEXT",
                 "policy JSONB", "violated_rules JSONB")

UPSERT = """
INSERT INTO ground_truth (scenario_id, agent, category, attack_type, expected_tools, expected_behavior,
                          scenario_kind, prompt, adversarial_text, policy, violated_rules)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (scenario_id) DO UPDATE SET
    category = EXCLUDED.category, attack_type = EXCLUDED.attack_type,
    violated_rules = EXCLUDED.violated_rules"""


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def ground_truth_rows(scenarios: list[dict], labels: list[dict]) -> list[dict]:
    """One row per scenario that has a label (= the agent ran it)."""
    label_of = {row["scenario_id"]: row for row in labels}
    rows = []
    for scenario in scenarios:
        label = label_of.get(scenario["scenario_id"])
        if label is None:
            continue
        adversarial = label["label"] == "adversarial"
        rows.append({
            "scenario_id": scenario["scenario_id"],
            "agent": scenario.get("agent", "B"),
            "category": label["label"],
            "attack_type": scenario.get("attack_type") if adversarial else None,
            "expected_tools": [call["tool"] for call in scenario.get("reference_calls", [])],
            "expected_behavior": scenario.get("expected_behavior", ""),
            "scenario_kind": scenario.get("scenario_kind"),
            "prompt": scenario.get("prompt"),
            "adversarial_text": scenario.get("adversarial_text"),
            "policy": scenario.get("policy"),
            "violated_rules": label["violated_rules"],
        })
    return rows


def save(rows: list[dict], conninfo: str) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(CREATE_TABLE)
        for column in EXTRA_COLUMNS:
            conn.execute(f"ALTER TABLE ground_truth ADD COLUMN IF NOT EXISTS {column}")
        for row in rows:
            conn.execute(UPSERT, (
                row["scenario_id"], row["agent"], row["category"], row["attack_type"],
                Jsonb(row["expected_tools"]), row["expected_behavior"], row["scenario_kind"],
                row["prompt"], row["adversarial_text"],
                Jsonb(row["policy"]) if row["policy"] else None, Jsonb(row["violated_rules"])))


def main() -> None:
    from dotenv import dotenv_values

    env = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
    parser = argparse.ArgumentParser(description="Load Agent B ground truth into scenario_db")
    parser.add_argument("file", help="scenario file name, e.g. scenario_01_500.jsonl")
    parser.add_argument("--db", default=(f"host={env.get('DB_HOST', 'localhost')} port=5432 dbname=scenario_db "
                                         f"user=scenario_svc password={env.get('SERVICE_DB_PASSWORD', '')}"))
    args = parser.parse_args()

    rows = ground_truth_rows(read_jsonl(DATASET_DIR / "scenarios" / args.file),
                             read_jsonl(DATASET_DIR / "labels" / f"labels_for_{args.file}"))
    save(rows, args.db)
    print(f"{len(rows)} scenarios loaded:", dict(Counter(row["category"] for row in rows)))


if __name__ == "__main__":
    main()