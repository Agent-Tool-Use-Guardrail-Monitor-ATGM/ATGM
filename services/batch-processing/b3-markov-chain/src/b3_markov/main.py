"""B3: trains the Markov-chain anomaly detector of one agent on normal sessions; saves table + metrics, announces it

    python -m b3_markov.main                                   # Agent B, dataset files in the repo
    python -m b3_markov.main --events-file my_events.jsonl     # Agent B, one raw events file
    python -m b3_markov.main --agent A --dataset-file agent_a.jsonl --announce
    python -m b3_markov.main --source db --announce            # analytics_db (reviewed labels)
    python -m b3_markov.main --orders 1 2 3 --smoothing floor --epsilon 1e-5 --save-fold-models

Live scoring is not done here: the stream pipeline reads the announced tables (spec Sec. 14).
Environment: ANALYTICS_DB (libpq connection string), KAFKA_BOOTSTRAP (localhost:29092), MODELS_DIR (./models),
DATASET_DIR. Every option below also lands in metrics.json under "parameters".
"""
import argparse
import json
import os
from pathlib import Path

from b3_markov.adapters import dataset, model_store
from b3_markov.domain.arguments import ArgParams
from b3_markov.domain.scoring import SCORE_MODES, Params
from b3_markov.domain.training import (evaluate_config, fit_detector, fold_models, profile, run_experiment,
                                       to_table, tune_alpha)

REPO_DATASET = Path(__file__).resolve().parents[5] / "dataset" / "agent_b"


def split_sessions(sessions, normal_by: str):
    """Normal = category 'normal' (session.started / reviewer verdict != attack) or behaviour label 'compliant'."""
    if normal_by == "label":
        is_normal = lambda s: s.label == "compliant"       # noqa: E731
    else:
        is_normal = lambda s: s.category == "normal"       # noqa: E731
    return [s for s in sessions if is_normal(s)], [s for s in sessions if not is_normal(s)]


AGENT_A_TOOLS = ["inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns",
                 "finalize_statistics", "request_clarification"]       # statistics-tools-v1 (spec Sec. 15.5)


def summary(r: dict) -> dict:
    return {k: r[k] for k in ("roc_auc", "pr_auc", "at_threshold")}


def main() -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(description="B3: Markov-chain anomaly detector (batch layer)")
    parser.add_argument("--agent", choices=["A", "B"], default="B", help="one run trains one agent's model")
    parser.add_argument("--source", choices=["dataset", "db"], default="dataset")
    parser.add_argument("--scenarios", default="scenario_01_500.jsonl", help="dataset file name (source=dataset)")
    parser.add_argument("--dataset-dir", default=env("DATASET_DIR", str(REPO_DATASET)))
    parser.add_argument("--events-file", help="Agent B: one raw events JSONL instead of the events/labels folders")
    parser.add_argument("--dataset-file", help="Agent A: the recorded JSONL of wrapped records (required for A)")
    parser.add_argument("--orders", type=int, nargs="+", default=[1, 2], help="Markov orders; the first is primary")
    parser.add_argument("--smoothing", choices=["additive", "floor", "backoff"], default="additive")
    parser.add_argument("--alpha", default=None, help="additive alpha, or 'cv' to tune it (default: 0.1 for B, cv for A)")
    parser.add_argument("--epsilon", type=float, default=1e-5)
    parser.add_argument("--vocabulary", help="comma-separated tool names fixing V (default for A: statistics-tools-v1)")
    parser.add_argument("--no-arguments", action="store_true", help="tool names only (forced for Agent A)")
    parser.add_argument("--score", choices=SCORE_MODES, default="joint", help="session score (spec Sec. 13.4)")
    parser.add_argument("--arg-alpha", type=float, default=0.1, help="smoothing of the argument emissions")
    parser.add_argument("--min-domain-count", type=int, default=2, help="recipient domains seen less often are rare")
    parser.add_argument("--date-slack-days", type=int, default=3)
    parser.add_argument("--percentile", type=float, default=None,
                        help="threshold percentile of held-out normal scores (default: 99 for B, 95 for A)")
    parser.add_argument("--folds", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bootstrap", type=int, default=1000, help="bootstrap repetitions for the intervals")
    parser.add_argument("--normal-by", choices=["category", "label"], default="category")
    parser.add_argument("--exclude-labels", help="comma-separated behaviour labels: also train without those normal "
                                                 "sessions and report the difference (A: model_failure)")
    parser.add_argument("--save-fold-models", action="store_true", help="write the CV fold tables to <model>/folds/")
    parser.add_argument("--models-dir", default=env("MODELS_DIR", "models"))
    parser.add_argument("--announce", action="store_true", help="publish the new model on model-updates")
    args = parser.parse_args()

    agent_a = args.agent == "A"
    if agent_a:
        args.no_arguments = True                        # A's clear arguments are not recorded (spec Sec. 15.5)
    if args.percentile is None:
        args.percentile = 95.0 if agent_a else 99.0
    if args.alpha is None:
        args.alpha = "cv" if agent_a else "0.1"
    vocabulary = ([t.strip() for t in args.vocabulary.split(",") if t.strip()] if args.vocabulary
                  else AGENT_A_TOOLS if agent_a else None)

    if args.source == "db":
        sessions = dataset.from_database(env("ANALYTICS_DB", "host=localhost dbname=analytics_db user=analytics_svc"),
                                         args.agent)
    elif agent_a:
        if not args.dataset_file:
            raise SystemExit("--agent A needs --dataset-file (Agent A's recorded JSONL) or --source db")
        sessions = dataset.from_agent_a_file(Path(args.dataset_file))
    elif args.events_file:
        sessions = dataset.from_events_file(Path(args.events_file))
    else:
        sessions = dataset.from_dataset(Path(args.dataset_dir), args.scenarios)
    normal, adversarial = split_sessions(sessions, args.normal_by)
    if not normal:
        raise SystemExit("no normal sessions to train on")
    print(f"Agent {args.agent}: {len(sessions)} sessions: {len(normal)} normal (training), "
          f"{len(adversarial)} other (evaluation)")

    common = dict(folds=args.folds, seed=args.seed)
    base = Params(args.smoothing, 0.1 if args.alpha == "cv" else float(args.alpha), args.epsilon)
    alpha_report = {"mode": "fixed", "chosen": base.alpha}
    if args.alpha == "cv":
        chosen, nll = tune_alpha(normal, args.orders[0], base, vocabulary=vocabulary, **common)
        base = Params(args.smoothing, chosen, args.epsilon)
        alpha_report = {"mode": "cv", "chosen": chosen, "heldout_nll_per_transition": nll, "sensitivity": {
            str(a): summary(evaluate_config(normal, adversarial, args.orders[0], Params(args.smoothing, a, args.epsilon),
                                            pct=args.percentile, bootstrap=0, arg_params=None, mode="seq",
                                            vocabulary=vocabulary, **common)) for a in nll}}
    params = base
    arg_params = None if args.no_arguments else ArgParams(args.arg_alpha, args.min_domain_count, args.date_slack_days)
    mode = "seq" if args.no_arguments else args.score
    experiment = run_experiment(normal, adversarial, args.orders, params, pct=args.percentile,
                                bootstrap=args.bootstrap, arg_params=arg_params, mode=mode,
                                vocabulary=vocabulary, **common)
    model = fit_detector(normal, args.orders, params, arg_params, mode, vocabulary)

    calibration = {"method": f"kfold-{args.folds}", "score": mode, "percentile": args.percentile,
                   "primary_order": args.orders[0],
                   "threshold": {str(o): experiment["results"][f"order{o}"]["threshold"] for o in args.orders},
                   "call_threshold": {str(o): experiment["results"][f"order{o}"]["call_level"]["call_threshold"]
                                      for o in args.orders},
                   "call_statistic": "min_log_p_per_session"}
    label_filter = "category == normal" if args.normal_by == "category" else "label == compliant"
    table_args = dict(label_filter=label_filter, seed=args.seed, agent=args.agent,
                      vocabulary_declared=vocabulary is not None)
    table = to_table(model, normal, calibration, **table_args)

    metrics = {"model": args.smoothing,
               "parameters": {k: v for k, v in vars(args).items() if k != "announce"},
               "alpha": alpha_report, "data": profile(normal, adversarial), **experiment}
    if args.exclude_labels:
        dropped = {x.strip() for x in args.exclude_labels.split(",")}
        kept = [s for s in normal if s.label not in dropped]
        metrics["sensitivity_without_labels"] = {
            "labels": sorted(dropped), "n_removed": len(normal) - len(kept),
            "results": {f"order{o}": summary(evaluate_config(kept, adversarial, o, params, pct=args.percentile,
                                                              bootstrap=0, arg_params=arg_params, mode=mode,
                                                              vocabulary=vocabulary, **common))
                        for o in args.orders}}
    version = model_store.version_name(args.smoothing)
    folder = model_store.save(table, metrics, Path(args.models_dir), version, args.agent)
    if args.save_fold_models:
        tables = [to_table(det, train, calibration, **table_args)
                  for _, train, det in fold_models(normal, args.orders, params, arg_params=arg_params, mode=mode,
                                                   vocabulary=vocabulary, **common)]
        model_store.save_fold_tables(folder, tables)
    for name, r in experiment["results"].items():
        cl = r["call_level"]
        print(f"{name}: threshold {r['threshold']:.3f}  ROC-AUC {r['roc_auc']:.3f}  PR-AUC {r['pr_auc']:.3f}  "
              f"recall {r['at_threshold']['recall']}  fpr {r['at_threshold']['fpr']}  |  call threshold "
              f"{cl['call_threshold']:.3f}  call fpr {cl['false_alarm']['call']:.3f}  union recall {cl['union_recall']}")
    print(f"Model saved to {folder}")
    if args.announce:
        model_store.announce(folder, metrics, table, env("KAFKA_BOOTSTRAP", "localhost:29092"), args.agent)


if __name__ == "__main__":
    main()
