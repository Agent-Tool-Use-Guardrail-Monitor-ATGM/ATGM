"""B3: trains the Markov-chain anomaly detector on normal sessions and saves the transition table + metrics

    python -m b3_markov.main                                   # dataset files in the repo
    python -m b3_markov.main --events-file my_events.jsonl     # one raw events file
    python -m b3_markov.main --source db --announce            # analytics_db (reviewed labels)
    python -m b3_markov.main --orders 1 2 3 --smoothing floor --epsilon 1e-5

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
from b3_markov.domain.training import fit_detector, profile, run_experiment, to_table

REPO_DATASET = Path(__file__).resolve().parents[5] / "dataset" / "agent_b"


def split_sessions(sessions, normal_by: str):
    """Normal = category 'normal' (session.started / reviewer verdict != attack) or behaviour label 'compliant'."""
    if normal_by == "label":
        is_normal = lambda s: s.label == "compliant"       # noqa: E731
    else:
        is_normal = lambda s: s.category == "normal"       # noqa: E731
    return [s for s in sessions if is_normal(s)], [s for s in sessions if not is_normal(s)]


def main() -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(description="B3: Markov-chain anomaly detector")
    parser.add_argument("--source", choices=["dataset", "db"], default="dataset")
    parser.add_argument("--scenarios", default="scenario_01_500.jsonl", help="dataset file name (source=dataset)")
    parser.add_argument("--dataset-dir", default=env("DATASET_DIR", str(REPO_DATASET)))
    parser.add_argument("--events-file", help="one raw events JSONL instead of the events/labels folders")
    parser.add_argument("--orders", type=int, nargs="+", default=[1, 2], help="Markov orders; the first is scored live")
    parser.add_argument("--smoothing", choices=["additive", "floor", "backoff"], default="additive")
    parser.add_argument("--alpha", type=float, default=0.1)
    parser.add_argument("--epsilon", type=float, default=1e-5)
    parser.add_argument("--no-arguments", action="store_true", help="tool names only (v0.1 behaviour)")
    parser.add_argument("--score", choices=SCORE_MODES, default="joint", help="session score (spec Sec. 13.4)")
    parser.add_argument("--arg-alpha", type=float, default=0.1, help="smoothing of the argument emissions")
    parser.add_argument("--min-domain-count", type=int, default=2, help="recipient domains seen less often are rare")
    parser.add_argument("--date-slack-days", type=int, default=3)
    parser.add_argument("--percentile", type=float, default=99.0, help="threshold percentile of held-out normal scores")
    parser.add_argument("--folds", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bootstrap", type=int, default=1000, help="bootstrap repetitions for the AUC interval")
    parser.add_argument("--normal-by", choices=["category", "label"], default="category")
    parser.add_argument("--models-dir", default=env("MODELS_DIR", "models"))
    parser.add_argument("--announce", action="store_true", help="publish the new model on model-updates")
    args = parser.parse_args()

    if args.source == "db":
        sessions = dataset.from_database(env("ANALYTICS_DB", "host=localhost dbname=analytics_db user=analytics_svc"))
    elif args.events_file:
        sessions = dataset.from_events_file(Path(args.events_file))
    else:
        sessions = dataset.from_dataset(Path(args.dataset_dir), args.scenarios)
    normal, adversarial = split_sessions(sessions, args.normal_by)
    if not normal:
        raise SystemExit("no normal sessions to train on")
    # print(f"{len(sessions)} sessions: {len(normal)} normal (training), {len(adversarial)} other (evaluation)")

    params = Params(args.smoothing, args.alpha, args.epsilon)
    arg_params = None if args.no_arguments else ArgParams(args.arg_alpha, args.min_domain_count, args.date_slack_days)
    mode = "seq" if args.no_arguments else args.score
    experiment = run_experiment(normal, adversarial, args.orders, params, folds=args.folds, seed=args.seed,
                                pct=args.percentile, bootstrap=args.bootstrap, arg_params=arg_params, mode=mode)
    model = fit_detector(normal, args.orders, params, arg_params, mode)
    thresholds = {str(o): experiment["results"][f"order{o}"]["threshold"] for o in args.orders}
    calibration = {"method": f"kfold-{args.folds}", "score": mode,
                   "percentile": args.percentile, "primary_order": args.orders[0], "threshold": thresholds}
    label_filter = "category == normal" if args.normal_by == "category" else "label == compliant"
    table = to_table(model, normal, calibration, label_filter=label_filter, seed=args.seed)

    metrics = {"model": args.smoothing,
               "parameters": {k: v for k, v in vars(args).items() if k != "announce"},
               "data": profile(normal, adversarial), **experiment}
    version = model_store.version_name(args.smoothing)
    folder = model_store.save(table, metrics, Path(args.models_dir), version)
    #for name, r in experiment["results"].items():
    #    print(f"{name}: threshold {r['threshold']:.3f}  ROC-AUC {r['roc_auc']:.3f}  PR-AUC {r['pr_auc']:.3f}  "
    #          f"recall {r['at_threshold']['recall']}  fpr {r['at_threshold']['fpr']}")
    #print(f"Model saved to {folder}")
    if args.announce:
        model_store.announce(folder, metrics, table, env("KAFKA_BOOTSTRAP", "localhost:29092"))


if __name__ == "__main__":
    main()
