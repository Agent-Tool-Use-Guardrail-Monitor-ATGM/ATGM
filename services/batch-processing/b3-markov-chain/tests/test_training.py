import math

from b3_markov.domain.scoring import Params
from b3_markov.domain.training import (average_precision, cv_scores, fit, from_table, kfold, percentile,
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
