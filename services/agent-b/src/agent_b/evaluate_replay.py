"""Compares the detector scores of a replayed Agent B dataset with its labels (analytics_db).

Session score of a detector = its highest score in the session.
AUC = how well the score ranks violating sessions above compliant ones (0.5 random, 1.0 perfect).

Usage (from services/agent-b, after the replay is fully processed):
    PYTHONPATH=src uv run python src/agent_b/evaluate_replay.py scenario_01_500.jsonl
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict

from agent_b.load_ground_truth import DATASET_DIR, PROJECT_ROOT, read_jsonl

# forest scores point to a tool call, B1 scores to session.ended: get the session either way
SCORES_SQL = """
SELECT coalesce(s.session_id, e.session_id), s.detector, max(s.score)
FROM scores s LEFT JOIN agent_events e ON e.event_id = s.scored_event_id
GROUP BY 1, 2"""
VERDICTS_SQL = """
SELECT DISTINCT ON (session_id) session_id, verdict FROM labels ORDER BY session_id, occurred_at DESC"""


def auc(positives: list[float], negatives: list[float]) -> float:
    if not positives or not negatives:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def confusion(scores: list[float], violating: list[bool], threshold: float) -> dict:
    predicted = [score >= threshold for score in scores]
    tp = sum(p and v for p, v in zip(predicted, violating))
    fp = sum(p and not v for p, v in zip(predicted, violating))
    fn = sum(not p and v for p, v in zip(predicted, violating))
    tn = len(scores) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def main() -> None:
    import psycopg
    from dotenv import dotenv_values

    env = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
    parser = argparse.ArgumentParser(description="Evaluate detector scores of a replayed dataset")
    parser.add_argument("file", help="scenario file name, e.g. scenario_01_500.jsonl")
    parser.add_argument("--threshold", type=float, default=0.5, help="B1 decision threshold")
    parser.add_argument("--db", default=(f"host=localhost port=5432 dbname=analytics_db "
                                         f"user=analytics_svc password={env.get('SERVICE_DB_PASSWORD', '')}"))
    args = parser.parse_args()

    labels = {row["scenario_id"]: row["label"] == "adversarial"
              for row in read_jsonl(DATASET_DIR / "labels" / f"labels_for_{args.file}")}

    with psycopg.connect(args.db) as conn:
        scores = defaultdict(dict)                       # detector -> session -> score
        for session, detector, score in conn.execute(SCORES_SQL):
            if session in labels:
                scores[detector][session] = score
        verdicts = {s: v for s, v in conn.execute(VERDICTS_SQL) if s in labels}

    print(f"{len(labels)} sessions: {sum(labels.values())} violating, {len(labels) - sum(labels.values())} compliant\n")
    for detector, by_session in sorted(scores.items()):
        sessions = list(by_session)
        values = [by_session[s] for s in sessions]
        truth = [labels[s] for s in sessions]
        result = f"{detector:16} sessions={len(sessions):4}  AUC={auc([v for v, t in zip(values, truth) if t], [v for v, t in zip(values, truth) if not t]):.3f}"
        if detector == "b1_classifier":
            result += f"  @{args.threshold}: {confusion(values, truth, args.threshold)}"
        print(result)

    agree = sum((verdict == "attack") == labels[s] for s, verdict in verdicts.items())
    print(f"\nreviewer verdicts: {len(verdicts)} sessions reviewed, {agree} agree with the labels")


if __name__ == "__main__":
    main()