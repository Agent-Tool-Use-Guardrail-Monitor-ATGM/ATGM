import math

from b3_markov.domain.scoring import Params
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
    assert r["min_p"] == 1e-5 and r["worst_transition"] == "find_contact -> save_draft"


def test_empty_session_scores_start_to_end():
    r = fit(TRAIN, [1], Params()).score(1, [])
    assert r["n_transitions"] == 1 and r["n_calls"] == 0 and r["n_unseen"] == 1


def test_unknown_tool_is_unk_and_too_long_is_flagged():
    r = fit(TRAIN, [1], Params()).score(1, ["rm_rf"] * 11)
    assert r["exceeds_max_len"] and r["max_run_length"] == 11 and r["n_unseen"] == r["n_transitions"]
