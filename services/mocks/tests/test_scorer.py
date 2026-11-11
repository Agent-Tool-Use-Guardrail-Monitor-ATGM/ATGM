import random

import pytest

from atgm_mocks.domain.scorer import MockScorer
from atgm_mocks.domain.sessions import ATTACKS, SessionGenerator
from atgm_mocks.envelope import session_events
from atgm_mocks.run_scorer import score_event


def session_scores(scorer, session, rng):
    return [v for e in session_events(session, "r", rng=rng) if (v := scorer.score(e)) is not None]


@pytest.fixture
def trained():
    rng = random.Random(0)
    g, scorer = SessionGenerator(rng, attack_rate=0), MockScorer()
    for _ in range(800):
        for agent in "AB":
            session_scores(scorer, g.session(agent), rng)
    return g, scorer, rng


@pytest.mark.parametrize("agent,attack", [(a, t) for a in "AB" for t in ATTACKS[a]])
def test_every_attack_type_scores_above_normal_sessions(trained, agent, attack):
    g, scorer, rng = trained
    normal = sorted(max(session_scores(scorer, g.session(agent), rng)) for _ in range(300))
    p99 = normal[int(0.99 * len(normal))]
    attacks = [max(session_scores(scorer, g.session(agent, attack), rng)) for _ in range(20)]
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
