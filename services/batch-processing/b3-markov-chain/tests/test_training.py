import math

from b3_markov.domain.scoring import Params
from b3_markov.domain.training import (average_precision, cv_scores, fit, fit_detector, from_table, kfold, percentile,
                                       profile, roc_auc, to_table)
from helpers import FULL, SHORT, sess

# Sec. 8 worked example: sessions 552b... (6 calls) and 64b2... (4 calls)
EXAMPLE = [sess(FULL, "552b"), sess(SHORT, "64b2")]


def test_worked_example_counts():
    model = fit(EXAMPLE, [1], Params())
    c = model.counts[1]
    assert c["<START>"] == {"find_contact": 2}
    assert c["find_contact"] == {"get_current_datetime": 2}
    assert c["get_current_datetime"] == {"get_free_slots": 2}
    assert c["get_free_slots"] == {"tone_checker": 1, "save_draft": 1}
    assert c["tone_checker"] == {"sensitive_content_scan": 1}
    assert c["sensitive_content_scan"] == {"save_draft": 1}
    assert c["save_draft"] == {"<END>": 2}
    assert sum(sum(r.values()) for r in c.values()) == 12


def test_additive_rows_sum_to_one_over_next_symbols():
    model = fit(EXAMPLE, [1, 2], Params("additive", alpha=0.1))
    nexts = model.vocabulary + ["<END>", "<UNK>"]
    for order, rows in model.counts.items():
        for key in rows:
            ctx = tuple(key.split(">"))
            assert math.isclose(sum(model.prob(order, ctx, n)[0] for n in nexts), 1.0)


def test_unseen_context_is_uniform_with_additive():
    model = fit(EXAMPLE, [1], Params("additive"))
    p, seen = model.prob(1, ("nope",), "save_draft")
    assert math.isclose(p, 1 / (len(model.vocabulary) + 2)) and not seen


def test_floor_smoothing_uses_epsilon_for_unseen():
    model = fit(EXAMPLE, [1], Params("floor", epsilon=1e-5))
    assert model.prob(1, ("find_contact",), "save_draft") == (1e-5, False)
    assert model.prob(1, ("get_free_slots",), "save_draft") == (0.5, True)


def test_backoff_falls_back_to_lower_order():
    model = fit(EXAMPLE, [2], Params("backoff"))
    assert 0 in model.counts and 1 in model.counts
    p, seen = model.prob(2, ("find_contact", "save_draft"), "<END>")
    assert not seen and p > 0


def test_only_given_sessions_are_counted():
    attack = sess(["unauthorized"], "x", "adversarial", "unauthorized_tool")
    normal = [s for s in EXAMPLE + [attack] if s.category == "normal"]
    assert "unauthorized" not in fit(normal, [1], Params()).vocabulary


def test_table_roundtrip_gives_same_scores():
    model = fit(EXAMPLE, [1, 2], Params())
    table = to_table(model, EXAMPLE, {"threshold": {"1": 1.0}}, label_filter="category == normal", seed=0)
    again = from_table(table)
    for order in (1, 2):
        assert again.score(order, SHORT)["mean_nll"] == model.score(order, SHORT)["mean_nll"]
    assert table["orders"]["1"]["transitions"]["<START>"] == {"total": 2, "next": {"find_contact": {"count": 2, "p_mle": 1.0}}}
    assert table["training"]["n_sessions"] == 2 and table["training"]["n_calls"] == 10


def test_training_is_deterministic():
    a = to_table(fit(EXAMPLE, [1], Params()), EXAMPLE, {}, label_filter="x", seed=0, trained_at="t")
    b = to_table(fit(list(reversed(EXAMPLE)), [1], Params()), list(reversed(EXAMPLE)), {}, label_filter="x", seed=0, trained_at="t")
    assert a == b


def test_percentile_and_kfold():
    assert percentile([1, 2, 3, 4], 50) == 2.5 and percentile([1, 2, 3, 4], 100) == 4
    folds = kfold(23, 10, 0)
    assert sorted(i for f in folds for i in f) == list(range(23)) and kfold(23, 10, 0) == folds


def test_cv_scores_are_heldout():
    normal = [sess(FULL, str(i)) for i in range(6)] + [sess(SHORT, "odd")]
    scores = cv_scores(normal, 1, Params(), folds=7, seed=0)
    assert scores[-1] > max(scores[:-1])            # the unique session is unseen when held out


def test_auc_and_ap():
    assert roc_auc([0.1, 0.2], [0.3, 0.4]) == 1.0 and roc_auc([0.3], [0.3]) == 0.5
    assert roc_auc([0.5, 0.6], [0.1, 0.2]) == 0.0
    assert average_precision([0.1], [0.9]) == 1.0


def test_profile_flags_sequences_seen_in_normal():
    adv = [sess(FULL, "a", "adversarial", "unsafe_args"), sess(["save_draft"], "b", "adversarial", "skipped_check")]
    p = profile(EXAMPLE, adv)
    assert p["adversarial_exact_sequence_in_normal"]["total"] == 1


# ---------------------------------------------------------------- v0.3 / v0.4

def _normals(n=30):
    variants = [FULL, SHORT, FULL[:3] + ["get_free_slots"] + FULL[3:]]
    return [sess(variants[i % 3], f"n{i}") for i in range(n)]


def test_call_threshold_is_the_100_minus_p_percentile_of_heldout_min_log_p():
    from b3_markov.domain.training import cv_results, evaluate_config
    normal = _normals()
    kw = dict(folds=5, seed=1, pct=95, bootstrap=0)
    r = evaluate_config(normal, [sess(["save_draft", "save_draft"], "a", "adversarial", "x")], 1, Params(), **kw)
    held_m = [x["min_log_p"] for x in cv_results(normal, 1, Params(), 5, 1)]
    assert math.isclose(r["call_level"]["call_threshold"], percentile(held_m, 5))
    assert r["call_level"]["heldout_min_log_p"] == held_m and r["call_level"]["statistic"] == "min_log_p_per_session"


def test_adversarial_sessions_never_change_the_call_threshold_or_the_session_threshold():
    from b3_markov.domain.training import evaluate_config
    normal = _normals()
    kw = dict(folds=5, seed=1, pct=99, bootstrap=0)
    a = evaluate_config(normal, [], 1, Params(), **kw)
    b = evaluate_config(normal, [sess(["x", "y", "z"], "a", "adversarial", "t")] * 5, 1, Params(), **kw)
    assert a["call_level"]["call_threshold"] == b["call_level"]["call_threshold"] and a["threshold"] == b["threshold"]


def test_call_level_metrics_per_attack_type_and_first_index():
    from b3_markov.domain.training import evaluate_config
    odd = sess(["find_contact", "save_draft", "save_draft"], "a", "adversarial", "flood")
    r = evaluate_config(_normals(), [odd], 1, Params("floor"), folds=5, seed=1, pct=95, bootstrap=0)
    t = r["call_level"]["recall_by_attack_type"]["flood"]
    assert t["call_detected"] == 1 and t["call_recall"] == 1.0 and t["first_index"]["indices"] == [2]
    fa = r["call_level"]["false_alarm"]
    assert 0 <= fa["call"] <= fa["union"] <= 1 and fa["union"] >= fa["session"]


def test_fold_models_never_count_a_session_from_their_own_fold():
    from b3_markov.domain.training import fold_models
    normal = [sess(FULL, f"s{i}") if i != 7 else sess(["rare_tool"], "s7") for i in range(20)]
    folds = fold_models(normal, [1], Params(), 10, 0)
    assert len(folds) == 10
    for held_out, train, det in folds:
        held_ids = {normal[i].session_id for i in held_out}
        assert not held_ids & {s.session_id for s in train} and len(train) == 20 - len(held_out)
        assert ("rare_tool" in det.chain.vocabulary) == ("s7" not in held_ids)


def test_tune_alpha_uses_normal_data_only_and_returns_a_grid_value():
    from b3_markov.domain.training import ALPHA_GRID, tune_alpha
    best, table = tune_alpha(_normals(), 1, Params(), 5, 0)
    assert best in ALPHA_GRID and set(table) == set(ALPHA_GRID) and table[best] == min(table.values())


def test_table_records_agent_and_vocabulary_source():
    model = fit_detector(EXAMPLE, [1], Params(), vocabulary=["find_contact", "save_draft"])
    table = to_table(model, EXAMPLE, {}, label_filter="x", seed=0, agent="A", vocabulary_declared=True)
    assert table["training"]["agent"] == "A" and table["training"]["vocabulary_source"] == "declared"
    assert table["vocabulary"] == ["find_contact", "save_draft"]
