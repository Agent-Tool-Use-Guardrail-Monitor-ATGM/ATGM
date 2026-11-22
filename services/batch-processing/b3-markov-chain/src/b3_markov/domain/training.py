"""Training (counting), calibration (k-fold on normal sessions) and evaluation on adversarial sessions."""
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone

from b3_markov.domain.arguments import ArgParams, ArgumentModel
from b3_markov.domain.scoring import Detector, MarkovModel, Params
from b3_markov.domain.sequences import DELIM, END, START, UNK, context_key, transitions
from b3_markov.domain.sessions import Session

SPEC_VERSION = "0.3"


# ---------------------------------------------------------------- training

def fit(sessions: list[Session], orders: list[int], params: Params, vocabulary: list[str] | None = None) -> MarkovModel:
    """Maximum-likelihood counts per order. Backoff needs every lower order too.

    `vocabulary` fixes V to a declared tool list (spec Sec. 15.5); tools outside it are counted as <UNK>.
    Without it V is the set of tools seen in training.
    """
    if params.smoothing == "backoff":
        orders = list(range(0, max(orders) + 1))
    declared = set(vocabulary) if vocabulary else None
    vocabulary = sorted(declared) if declared else sorted({tool for s in sessions for tool in s.tools} - {UNK})
    counts: dict[int, dict[str, dict[str, int]]] = {}
    for order in orders:
        rows: dict[str, Counter] = defaultdict(Counter)
        for s in sessions:
            for ctx, nxt in transitions(s.tools, order, declared):
                rows[context_key(ctx)][nxt] += 1
        counts[order] = {key: dict(sorted(row.items())) for key, row in sorted(rows.items())}
    return MarkovModel(vocabulary, counts, params)


def fit_detector(sessions: list[Session], orders: list[int], params: Params, arg_params: ArgParams | None = None,
                 mode: str = "joint", vocabulary: list[str] | None = None) -> Detector:
    """Chain over tool names, plus the argument emission model unless arg_params is None."""
    chain = fit(sessions, orders, params, vocabulary)
    return Detector(chain, ArgumentModel.fit(sessions, arg_params) if arg_params else None, mode)


def input_sha256(sessions: list[Session]) -> str:
    payload = json.dumps(sorted([s.session_id, s.tools] for s in sessions))
    return hashlib.sha256(payload.encode()).hexdigest()


def to_table(detector: Detector, sessions: list[Session], calibration: dict, *, label_filter: str,
             seed: int, trained_at: str | None = None, agent: str | None = None,
             vocabulary_declared: bool = False) -> dict:
    """The transition table of the spec (Sec. 5 + 13.6), JSON-serialisable."""
    model = detector.chain if isinstance(detector, Detector) else detector
    arguments = detector.arguments if isinstance(detector, Detector) else None
    p = model.params
    orders = {}
    for order in model.orders:
        transitions_json = {}
        for key, row in model.counts[order].items():
            total = sum(row.values())
            transitions_json[key] = {"total": total, "next": {
                nxt: {"count": c, "p_mle": c / total} for nxt, c in row.items()}}
        orders[str(order)] = {"n_transitions": sum(sum(r.values()) for r in model.counts[order].values()),
                              "transitions": transitions_json}
    table = {
        "spec_version": SPEC_VERSION,
        "model": {"type": "markov_chain", "orders": model.orders, "state_encoding": "tool_name",
                  "tokens": {"start": START, "end": END, "unk": UNK}, "state_delimiter": DELIM,
                  "smoothing": {"method": p.smoothing, "alpha": p.alpha, "epsilon": p.epsilon,
                                "backoff_weight": p.backoff_weight},
                  "log_base": "e"},
        "training": {"label_filter": label_filter, "n_sessions": len(sessions),
                     "n_calls": sum(len(s.tools) for s in sessions),
                     "input_sha256": input_sha256(sessions),
                     "trained_at": trained_at or datetime.now(timezone.utc).isoformat(),
                     "random_seed": seed, "agent": agent,
                     "vocabulary_source": "declared" if vocabulary_declared else "learned"},
        "vocabulary": model.vocabulary,
        "orders": orders,
        "calibration": calibration,
    }
    if arguments is not None:
        table["arguments"] = arguments.to_json()
        table["scoring"] = {"score": detector.mode}
    return table


def from_table(table: dict) -> Detector:
    m = table["model"]["smoothing"]
    params = Params(m["method"], m["alpha"], m["epsilon"], m.get("backoff_weight", 0.4))
    counts = {int(order): {key: {nxt: v["count"] for nxt, v in row["next"].items()}
                           for key, row in data["transitions"].items()}
              for order, data in table["orders"].items()}
    chain = MarkovModel(table["vocabulary"], counts, params)
    arguments = ArgumentModel.from_json(table["arguments"]) if table.get("arguments") else None
    return Detector(chain, arguments, (table.get("scoring") or {}).get("score", "joint"))


# ---------------------------------------------------------------- calibration helpers

def percentile(values: list[float], q: float) -> float:
    """Linear interpolation (numpy default), q in [0, 100]."""
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def kfold(n: int, folds: int, seed: int) -> list[list[int]]:
    index = list(range(n))
    random.Random(seed).shuffle(index)
    folds = max(2, min(folds, n))
    return [index[i::folds] for i in range(folds)]


def cv_results(normal: list[Session], order: int, params: Params, folds: int, seed: int,
               arg_params: ArgParams | None = None, mode: str = "joint",
               vocabulary: list[str] | None = None) -> list[dict]:
    """Full score dict of every normal session, from the model trained on the other folds."""
    results: list[dict] = [{}] * len(normal)
    for held_out in kfold(len(normal), folds, seed):
        held = set(held_out)
        model = fit_detector([s for i, s in enumerate(normal) if i not in held], [order], params, arg_params,
                             mode, vocabulary)
        for i in held_out:
            results[i] = model.score(order, normal[i])
    return results


def cv_scores(normal: list[Session], order: int, params: Params, folds: int, seed: int,
              key: str = "score", arg_params: ArgParams | None = None, mode: str = "joint",
              vocabulary: list[str] | None = None) -> list[float]:
    """Held-out score of every normal session (model trained on the other folds)."""
    return [r[key] for r in cv_results(normal, order, params, folds, seed, arg_params, mode, vocabulary)]


def fold_models(normal: list[Session], orders: list[int], params: Params, folds: int, seed: int,
                arg_params: ArgParams | None = None, mode: str = "joint",
                vocabulary: list[str] | None = None) -> list[tuple[list[int], list[Session], Detector]]:
    """The CV fold models: (held-out indices, training sessions, detector). Same folds as cv_results."""
    out = []
    for held_out in kfold(len(normal), folds, seed):
        held = set(held_out)
        train = [s for i, s in enumerate(normal) if i not in held]
        out.append((held_out, train, fit_detector(train, orders, params, arg_params, mode, vocabulary)))
    return out


ALPHA_GRID = (0.01, 0.03, 0.1, 0.3, 1.0)


def tune_alpha(normal: list[Session], order: int, params: Params, folds: int, seed: int,
               vocabulary: list[str] | None = None, grid=ALPHA_GRID) -> tuple[float, dict]:
    """Additive alpha with the lowest held-out mean NLL per transition on normal sessions (no attack data)."""
    table = {}
    for alpha in grid:
        trial = Params(params.smoothing, alpha, params.epsilon, params.backoff_weight)
        results = cv_results(normal, order, trial, folds, seed, None, "seq", vocabulary)
        table[alpha] = sum(r["total_nll"] for r in results) / sum(r["n_transitions"] for r in results)
    return min(table, key=table.get), table


# ---------------------------------------------------------------- metrics

def roc_auc(negatives: list[float], positives: list[float]) -> float:
    """P(score_pos > score_neg) + 0.5 P(equal) (Mann-Whitney)."""
    if not negatives or not positives:
        return float("nan")
    pooled = sorted([(v, 0) for v in negatives] + [(v, 1) for v in positives])
    ranks, i = [], 0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        ranks += [(i + j) / 2 + 1] * (j - i + 1)
        i = j + 1
    rank_sum = sum(r for r, (_, y) in zip(ranks, pooled) if y == 1)
    n_pos, n_neg = len(positives), len(negatives)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def average_precision(negatives: list[float], positives: list[float]) -> float:
    """PR-AUC as average precision; tied scores are handled as one threshold step."""
    if not positives:
        return float("nan")
    pooled = sorted([(v, 1) for v in positives] + [(v, 0) for v in negatives], reverse=True)
    tp = fp = 0
    ap, i = 0.0, 0
    while i < len(pooled):
        j = i
        while j < len(pooled) and pooled[j][0] == pooled[i][0]:
            j += 1
        new_tp = sum(y for _, y in pooled[i:j])
        tp, fp = tp + new_tp, fp + (j - i - new_tp)
        ap += (new_tp / len(positives)) * (tp / (tp + fp))
        i = j
    return ap


def at_threshold(negatives: list[float], positives: list[float], threshold: float) -> dict:
    """Alarm when score > threshold."""
    tp = sum(v > threshold for v in positives)
    fp = sum(v > threshold for v in negatives)
    fn, tn = len(positives) - tp, len(negatives) - fp
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / len(positives) if positives else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    return {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision,
            "recall": recall, "f1": f1, "fpr": fp / len(negatives) if negatives else None}


def bootstrap_auc_ci(negatives: list[float], positives: list[float], reps: int, seed: int) -> list[float] | None:
    if reps <= 0 or not negatives or not positives:
        return None
    rng = random.Random(seed)
    aucs = sorted(roc_auc(rng.choices(negatives, k=len(negatives)), rng.choices(positives, k=len(positives)))
                  for _ in range(reps))
    return [percentile(aucs, 2.5), percentile(aucs, 97.5)]


def rate_ci(values: list[float], threshold: float, reps: int, seed: int, below: bool = False) -> list[float] | None:
    """Bootstrap interval of the share of values above (or, below=True, under) a fixed threshold."""
    if reps <= 0 or not values:
        return None
    rng = random.Random(seed)
    hit = (lambda v: v < threshold) if below else (lambda v: v > threshold)
    rates = sorted(sum(hit(v) for v in rng.choices(values, k=len(values))) / len(values) for _ in range(reps))
    return [percentile(rates, 2.5), percentile(rates, 97.5)]


SENSITIVITY_PERCENTILES = (90, 95, 99, 99.5)


def evaluate_config(normal: list[Session], adversarial: list[Session], order: int, params: Params, *,
                    folds: int, seed: int, pct: float, bootstrap: int, score_key: str = "score",
                    arg_params: ArgParams | None = None, mode: str = "joint",
                    vocabulary: list[str] | None = None) -> dict:
    """Calibrates on held-out normal scores, scores adversarial sessions with the model trained on all normal.

    Besides the session threshold (Sec. 7.1) it calibrates the call-level threshold of Sec. 14.3:
    m(s) = min over transitions of ln p, call_threshold = the (100 - pct)-th percentile of the held-out m(s).
    """
    cv = cv_results(normal, order, params, folds, seed, arg_params, mode, vocabulary)
    held_out = [r[score_key] for r in cv]
    held_m = [r["min_log_p"] for r in cv]
    model = fit_detector(normal, [order], params, arg_params, mode, vocabulary)
    adv = [model.score(order, s) for s in adversarial]
    adv_scores = [r[score_key] for r in adv]
    threshold = percentile(held_out, pct)
    call_threshold = percentile(held_m, 100 - pct)

    by_type: dict[str, list[tuple[float, dict]]] = defaultdict(list)
    for s, v, r in zip(adversarial, adv_scores, adv):
        by_type[s.attack_type or "unknown"].append((v, r))

    def first_below(r: dict) -> int | None:
        """1-based index of the first transition below the call threshold (T + 1 is the <END> step)."""
        return next((i for i, lp in enumerate(r["log_probs"], 1) if lp < call_threshold), None)

    call_by_type = {}
    for t, items in sorted(by_type.items()):
        firsts = [f for _, r in items if (f := first_below(r)) is not None]
        call_by_type[t] = {
            "n": len(items), "call_detected": len(firsts), "call_recall": len(firsts) / len(items),
            "union_detected": sum(1 for v, r in items if v > threshold or first_below(r) is not None),
            "first_index": {"indices": sorted(firsts), "median": percentile(firsts, 50) if firsts else None}}
    session_fa = sum(v > threshold for v in held_out) / len(held_out)
    call_fa = sum(m < call_threshold for m in held_m) / len(held_m)
    union_fa = sum(v > threshold or m < call_threshold for v, m in zip(held_out, held_m)) / len(held_out)
    return {
        "order": order, "smoothing": params.smoothing, "score": mode if score_key == "score" else score_key,
        "arguments": arg_params is not None,
        "threshold": threshold, "percentile": pct,
        "normal_heldout": {"mean": sum(held_out) / len(held_out), "median": percentile(held_out, 50),
                           "p95": percentile(held_out, 95), "p99": percentile(held_out, 99), "max": max(held_out)},
        "roc_auc": roc_auc(held_out, adv_scores),
        "roc_auc_ci95": bootstrap_auc_ci(held_out, adv_scores, bootstrap, seed),
        "pr_auc": average_precision(held_out, adv_scores),
        "at_threshold": at_threshold(held_out, adv_scores, threshold),
        "false_alarm_rate_ci95": rate_ci(held_out, threshold, bootstrap, seed),
        "recall_by_attack_type": {t: {"n": len(v), "detected": sum(x > threshold for x, _ in v),
                                      "recall": sum(x > threshold for x, _ in v) / len(v)}
                                  for t, v in sorted(by_type.items())},
        "sensitivity": {str(q): at_threshold(held_out, adv_scores, percentile(held_out, q))
                        for q in SENSITIVITY_PERCENTILES},
        # call-level check (spec Sec. 14.3): an offline preview of the stream pipeline's out_of_order alerts
        "call_level": {
            "call_threshold": call_threshold, "statistic": "min_log_p_per_session",
            "heldout_min_log_p": held_m,
            "false_alarm": {"session": session_fa, "call": call_fa, "union": union_fa,
                            "call_ci95": rate_ci(held_m, call_threshold, bootstrap, seed, below=True)},
            "recall_by_attack_type": call_by_type,
            "union_recall": (sum(c["union_detected"] for c in call_by_type.values()) / len(adversarial)
                             if adversarial else None),
        },
    }


def profile(normal: list[Session], adversarial: list[Session]) -> dict:
    """Step 0: what the data looks like, and how much a sequence-only model can possibly see."""
    def lengths(sessions):
        return dict(sorted(Counter(len(s.tools) for s in sessions).items()))
    normal_sequences = {tuple(s.tools) for s in normal}
    bigrams = {pair for s in normal for pair in transitions(s.tools, 1)}
    by_type: dict[str, list[Session]] = defaultdict(list)
    for s in adversarial:
        by_type[s.attack_type or "unknown"].append(s)
    return {
        "n_normal": len(normal), "n_adversarial": len(adversarial),
        "adversarial_by_type": {t: len(v) for t, v in sorted(by_type.items())},
        "length_distribution_normal": lengths(normal),
        "length_distribution_adversarial": lengths(adversarial),
        "zero_call_sessions": {"normal": sum(not s.tools for s in normal),
                               "adversarial": sum(not s.tools for s in adversarial)},
        "vocabulary_normal": sorted({t for s in normal for t in s.tools}),
        "tools_only_in_adversarial": sorted({t for s in adversarial for t in s.tools} - {t for s in normal for t in s.tools}),
        "distinct_normal_sequences": len(normal_sequences),
        # sessions whose exact tool sequence also occurs in normal data cannot be detected by any sequence-only model
        "adversarial_exact_sequence_in_normal": {
            "total": sum(tuple(s.tools) in normal_sequences for s in adversarial),
            "by_type": {t: sum(tuple(s.tools) in normal_sequences for s in v) for t, v in sorted(by_type.items())}},
        "max_session_recall_sequence_only": (
            (len(adversarial) - sum(tuple(s.tools) in normal_sequences for s in adversarial)) / len(adversarial)
            if adversarial else None),
        "adversarial_all_bigrams_seen_in_normal": sum(
            all(pair in bigrams for pair in transitions(s.tools, 1)) for s in adversarial),
    }


def run_experiment(normal: list[Session], adversarial: list[Session], orders: list[int], params: Params, *,
                   folds: int, seed: int, pct: float, bootstrap: int, arg_params: ArgParams | None = None,
                   mode: str = "joint", vocabulary: list[str] | None = None) -> dict:
    """All metrics: the chosen configuration per order, ablations, the other smoothings, and the baselines."""
    common = dict(folds=folds, seed=seed, pct=pct, vocabulary=vocabulary)
    results = {f"order{o}": evaluate_config(normal, adversarial, o, params, bootstrap=bootstrap,
                                            arg_params=arg_params, mode=mode, **common) for o in orders}
    short = lambda r: {k: r[k] for k in ("roc_auc", "pr_auc", "at_threshold")}      # noqa: E731
    ablation = {}
    if arg_params is not None:
        for variant in ("seq", "args", "joint", "joint_max"):
            for o in orders:
                ablation[f"{variant}_order{o}"] = short(evaluate_config(
                    normal, adversarial, o, params, bootstrap=0, arg_params=arg_params, mode=variant, **common))
    comparison = {}
    for smoothing in ("additive", "floor", "backoff"):
        other = Params(smoothing, params.alpha, params.epsilon, params.backoff_weight)
        for o in orders:
            comparison[f"{smoothing}_order{o}"] = short(evaluate_config(
                normal, adversarial, o, other, bootstrap=0, arg_params=arg_params, mode=mode, **common))
    additive = Params("additive", params.alpha, params.epsilon, params.backoff_weight)
    baselines = {
        # order-0 chain = bag of tools (ignores order); stide-style = fraction of unseen bigrams; both tool names only
        "bag_of_tools": evaluate_config(normal, adversarial, 0, additive, bootstrap=bootstrap, score_key="mean_nll", **common),
        "stide_unseen_fraction_order1": evaluate_config(normal, adversarial, 1, additive, bootstrap=bootstrap,
                                                        score_key="unseen_fraction", **common),
    }
    return {"results": results, "ablation": ablation, "comparison": comparison, "baselines": baselines}
