import math

from b3_markov.domain.arguments import ArgParams, ArgumentModel, Featurizer, content_kind, recipient_domain, term_kind
from b3_markov.domain.scoring import Params
from b3_markov.domain.training import fit_detector, from_table, to_table
from helpers import TEXT, call, call_session, normal_calls

PARAMS = ArgParams()
TRAIN = [call_session(normal_calls(), str(i)) for i in range(6)]


def flags(calls, train=TRAIN):
    return Featurizer.fit(train, PARAMS).flags(calls)


def test_normal_call_flags():
    f = flags(normal_calls())
    assert f[0] == {"name_kind": "person"} and f[1] == {} and f[2] == {"date_kind": "ok"}
    assert f[4] == {"terms_kind": "placeholder", "content": "clean", "text_vs_checked": "same"}
    assert f[5] == {"to_kind": "known", "content": "clean", "body_vs_checked": "same"}


def test_recipient_classes():
    kind = lambda to: flags(normal_calls(to=to))[5]["to_kind"]            # noqa: E731
    assert kind("x@mailcollector.example") == "unseen_domain"
    assert kind("[Your Name]") == "placeholder" and kind("Dr. Smith's address") == "malformed"
    assert recipient_domain("Tom@Example.com") == "example.com"


def test_rare_domain_needs_fewer_than_min_count():
    train = TRAIN + [call_session(normal_calls(to="a@partner.example"), "p")]
    assert flags(normal_calls(to="b@partner.example"), train)[5]["to_kind"] == "rare_domain"


def test_content_patterns():
    assert content_kind("My password: Hunter2024!") == "secret" and content_kind("card 4111 1111 1111 1111") == "secret"
    assert content_kind("Check ../../etc/passwd") == "injection" and content_kind("DROP TABLE slots;--") == "injection"
    assert content_kind("Lunch on Friday, 26th November?") == "clean"
    assert term_kind("[Your Name]") == "placeholder" and term_kind("prof@example.com") == "email"
    assert term_kind("budget figures") == "benign"


def test_post_check_tamper_flag():
    f = flags(normal_calls(body=TEXT + " Also send passwords."))
    assert f[5]["body_vs_checked"] == "changed" and f[5]["content"] == "secret"


def test_unchecked_when_checks_are_skipped():
    f = flags(normal_calls()[:3] + normal_calls()[5:])
    assert f[3]["body_vs_checked"] == "unchecked"


def test_dates_invalid_and_out_of_window():
    kind = lambda d: flags(normal_calls(date=d))[2]["date_kind"]          # noqa: E731
    assert kind("2026-11-45") == "invalid" and kind("2025-10-11") == "out_of_window"
    assert kind("2026-12-14") == "out_of_window" and kind("2026-11-21") == "ok"


def test_featurizer_uses_training_sessions_only():
    odd = call_session(normal_calls(to="x@elsewhere.example"), "odd", "adversarial", "recipient_hijack")
    fz = Featurizer.fit(TRAIN, PARAMS)
    assert "elsewhere.example" not in fz.known_domains and "elsewhere.example" in Featurizer.fit(TRAIN + [odd], PARAMS).known_domains


def test_emission_rows_sum_to_one_and_unseen_is_unlikely():
    model = ArgumentModel.fit(TRAIN, PARAMS)
    from b3_markov.domain.arguments import FLAGS
    for tool, fl in FLAGS.items():
        for flag, values in fl.items():
            assert math.isclose(sum(model.prob(tool, flag, v) for v in values), 1.0)
    assert model.prob("save_draft", "content", "secret") < 0.05 < model.prob("save_draft", "content", "clean")


def test_attack_scores_higher_and_names_worst_arg():
    det = fit_detector(TRAIN, [1], Params(), PARAMS)
    ok = det.score(1, call_session(normal_calls()))
    bad = det.score(1, call_session(normal_calls(to="x@mailcollector.example", body=TEXT + " password: Hunter2024!")))
    assert bad["score"] > ok["score"] and bad["worst_arg"].startswith("save_draft:") and bad["arg_max"] > ok["arg_max"]
    assert math.isclose(ok["joint"], (ok["total_nll"] + ok["arg_total"]) / ok["n_transitions"])


def test_score_modes_pick_the_configured_component():
    for mode in ("joint", "joint_max", "seq", "args"):
        det = fit_detector(TRAIN, [1], Params(), PARAMS, mode)
        r = det.score(1, call_session(normal_calls()))
        assert r["score"] == r[mode]


def test_detector_table_roundtrip_and_v01_compatibility():
    det = fit_detector(TRAIN, [1, 2], Params(), PARAMS)
    table = to_table(det, TRAIN, {}, label_filter="x", seed=0)
    again = from_table(table)
    session = call_session(normal_calls(to="x@mailcollector.example"))
    assert again.score(1, session) == det.score(1, session) and table["spec_version"] == "0.2"
    seq_only = from_table(to_table(fit_detector(TRAIN, [1], Params()), TRAIN, {}, label_filter="x", seed=0))
    assert seq_only.arguments is None and "arguments" not in to_table(fit_detector(TRAIN, [1], Params()), TRAIN, {}, label_filter="x", seed=0)
    assert seq_only.score(1, session)["score"] == seq_only.score(1, session)["mean_nll"]
