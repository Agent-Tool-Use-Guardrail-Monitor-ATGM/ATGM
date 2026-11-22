import math

from b3_markov.domain.scoring import Params
from b3_markov.domain.scoring import step
from b3_markov.domain.sequences import transitions
from b3_markov.domain.training import fit
from helpers import FULL, SHORT, sess

TRAIN = [sess(FULL, "1"), sess(SHORT, "2")]


def test_mean_nll_of_training_session_is_low_and_unseen_is_high():
    model = fit(TRAIN, [1], Params("additive"))
    normal = model.score(1, SHORT)
    odd = model.score(1, ["save_draft", "save_draft", "find_contact"])
    assert normal["n_unseen"] == 0 and odd["n_unseen"] >= 2 and odd["mean_nll"] > normal["mean_nll"]


def test_score_fields_and_formula_for_floor():
    model = fit(TRAIN, [1], Params("floor", epsilon=1e-5))
    r = model.score(1, ["find_contact", "save_draft"])      # START->find_contact 1, find_contact->save_draft eps, save_draft->END 1
    assert r["n_transitions"] == 3 and r["n_unseen"] == 1
    assert math.isclose(r["total_nll"], -math.log(1e-5)) and math.isclose(r["mean_nll"], r["total_nll"] / 3)
    assert math.isclose(r["min_p"], 1e-5) and r["worst_transition"] == "find_contact -> save_draft"


def test_empty_session_scores_start_to_end():
    r = fit(TRAIN, [1], Params()).score(1, [])
    assert r["n_transitions"] == 1 and r["n_calls"] == 0 and r["n_unseen"] == 1


def test_unknown_tool_is_unk_and_too_long_is_flagged():
    r = fit(TRAIN, [1], Params()).score(1, ["rm_rf"] * 11)
    assert r["exceeds_max_len"] and r["max_run_length"] == 11 and r["n_unseen"] == r["n_transitions"]


def test_step_returns_log_prob_count_and_row_total():
    model = fit(TRAIN, [1], Params("floor", epsilon=1e-5))
    assert step(model, 1, ("get_free_slots",), "tone_checker") == (math.log(0.5), 1, 2)
    lp, count, total = step(model, 1, ("find_contact",), "save_draft")
    assert math.isclose(lp, math.log(1e-5)) and count == 0 and total == 2
    assert step(model, 1, ("never_seen",), "save_draft")[1:] == (0, 0)


def test_folding_step_gives_the_whole_session_nll_and_min_log_p():
    for smoothing in ("additive", "floor", "backoff"):
        model = fit(TRAIN, [1, 2], Params(smoothing))
        tools = ["find_contact", "save_draft", "mystery", "save_draft"]
        for order in (1, 2):
            lps = [step(model, order, ctx, nxt)[0] for ctx, nxt in transitions(tools, order, set(model.vocabulary))]
            r = model.score(order, tools)
            assert math.isclose(-sum(lps), r["total_nll"]) and math.isclose(min(lps), r["min_log_p"])
            assert r["log_probs"] == lps and len(lps) == len(tools) + 1


def test_worked_example_minimum_log_probability():
    # Sec. 8: the sample session f06c... repeats get_free_slots, the only transition unseen after training on two sessions
    model = fit(TRAIN, [1], Params("floor", epsilon=1e-5))
    r = model.score(1, ["find_contact", "get_current_datetime", "get_free_slots", "get_free_slots", "tone_checker",
                        "sensitive_content_scan", "save_draft"])
    assert r["n_unseen"] == 1 and math.isclose(r["min_log_p"], math.log(1e-5))


def test_fixed_vocabulary_maps_other_tools_to_unk_and_keeps_declared_unseen_tools():
    model = fit([sess(["a", "b"]), sess(["a", "rogue"])], [1], Params("additive"), vocabulary=["a", "b", "c"])
    assert model.vocabulary == ["a", "b", "c"] and "rogue" not in model.counts[1]["a"]
    assert model.counts[1]["a"] == {"<UNK>": 1, "b": 1}
    lp, count, _ = step(model, 1, ("a",), "c")                    # declared but never seen: smoothed, not <UNK>
    assert count == 0 and lp > -10
    assert step(model, 1, ("a",), "zzz")[1] == 1                  # an undeclared name is scored as <UNK>
