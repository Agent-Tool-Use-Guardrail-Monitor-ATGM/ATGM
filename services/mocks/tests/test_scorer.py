import copy
import random
from datetime import date

import pytest

from atgm_mocks.domain.scorer import MockScorer
from atgm_mocks.domain.agent_b import POLICY_ONLY_ATTACKS
from atgm_mocks.domain.sessions import ATTACKS, SessionGenerator
from atgm_mocks.envelope import session_events
from atgm_mocks.run_scorer import score_event


def session_scores(scorer, session, rng):
    return [v for e in session_events(session, "r", rng=rng) if (v := scorer.score(e)) is not None]


@pytest.fixture
def trained():
    rng = random.Random(0)
    # fixed "today": Agent B's date choices consume random numbers, so the date must not change the run
    g, scorer = SessionGenerator(rng, attack_rate=0, today=date(2026, 11, 15)), MockScorer()
    for _ in range(800):
        for agent in "AB":
            session_scores(scorer, g.session(agent), rng)
    return g, scorer, rng


# recipient_hijack / invalid_date change argument values only: tool order, counts and timing look
# normal, so an anomaly score cannot see them. They are the ground for the allow-list check.
DETECTABLE = [(a, t) for a in "AB" for t in ATTACKS[a] if t not in POLICY_ONLY_ATTACKS]


@pytest.mark.parametrize("agent,attack", DETECTABLE)
def test_every_attack_type_scores_above_normal_sessions(trained, agent, attack):
    g, scorer, rng = trained
    # `unknown_contact` is a deliberately rare one-call normal session. The scorer rightly finds it odd (about
    # 5-7), and at 1% of sessions it decides whether the p99 of 300 samples is 3 or 7, so it is left out here.
    normal = []
    while len(normal) < 300:
        s = g.session(agent)
        score = max(session_scores(scorer, s, rng))
        if s.scenario_kind != "unknown_contact":
            normal.append(score)
    normal.sort()
    p99 = normal[int(0.99 * len(normal))]
    # The scorer learns from everything it sees. Judge every attack against the same clean model, not one
    # that already learned the previous attacks (a repeated pattern such as save_draft -> save_draft would
    # become "normal" after the first flood).
    baseline = copy.deepcopy(scorer)
    attacks = [max(session_scores(copy.deepcopy(baseline), g.session(agent, attack), rng)) for _ in range(20)]
    assert sum(a > p99 for a in attacks) >= 18


def test_only_tool_calls_and_session_ends_are_scored():
    scorer = MockScorer()
    s = SessionGenerator(random.Random(1)).session("B")
    results = [scorer.score(e) for e in session_events(s, "r")]
    assert results[0] is None and all(v is not None for v in results[1:])
    assert scorer.score({"event_type": "model_call.completed", "data": {}}) is None


def test_scored_event_envelope():
    scorer = MockScorer()
    events = session_events(SessionGenerator(random.Random(2)).session("A"), "run-1")
    assert score_event(scorer, events[0]) is None
    out = score_event(scorer, events[1])
    assert out["schema_version"] == "1.0" and out["event_type"] == "anomaly.scored"
    assert out["session_id"] == events[1]["session_id"] and out["run_id"] == "run-1"
    d = out["data"]
    assert d["scored_event_id"] == events[1]["event_id"] and d["agent_id"] == "A"
    assert d["detector"] == "mock_scorer" and d["score"] >= 0


def test_session_memory_is_bounded():
    scorer = MockScorer(max_sessions=10)
    g = SessionGenerator(random.Random(3))
    for _ in range(30):
        events = session_events(g.session("A"), "r")
        scorer.score(events[0])
    assert len(scorer._last) == 10
