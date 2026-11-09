import random

import pytest

from atgm_mocks.domain.sessions import AGENT_A_TOOLS, AGENT_B_TOOLS, ATTACKS, SessionGenerator
from atgm_mocks.envelope import session_events


def gen(seed=0, rate=0.05):
    return SessionGenerator(random.Random(seed), attack_rate=rate)


def test_normal_sessions_use_only_the_agents_tools_in_a_sensible_order():
    g = gen()
    for _ in range(200):
        a = [c.tool for c in g.session("A").calls]
        assert set(a) <= set(AGENT_A_TOOLS)
        assert a[:2] == ["inspect_dataset", "describe_columns"] and a[-1] == "finalize_statistics"
        b = [c.tool for c in g.session("B").calls]
        assert b in (list(AGENT_B_TOOLS), list(AGENT_B_TOOLS) * 2)


@pytest.mark.parametrize("agent,attack", [(a, t) for a in "AB" for t in ATTACKS[a]])
def test_each_attack_looks_like_its_definition(agent, attack):
    s = gen(1).session(agent, attack)
    tools = [c.tool for c in s.calls]
    assert s.category == "adversarial" and s.attack_type == attack
    if attack == "unauthorized_tool":
        assert {"export_dataset", "send_email"} & set(tools)
    elif attack == "out_of_order":
        assert "inspect_dataset" not in tools and tools[-1] == "finalize_statistics"
    elif attack == "skipped_check":
        assert tools == []
    elif attack == "unsafe_args":
        args = str([c.arguments for c in s.calls])
        assert "../" in args or "col_399" in args or "password" in args or "4111" in args


def test_attack_rate_and_warm_up():
    g = gen(2, rate=0.1)
    sessions = [g.next("A") for _ in range(5_000)]
    rate = sum(s.category == "adversarial" for s in sessions) / len(sessions)
    assert 0.08 < rate < 0.12
    assert all(g.next("B", allow_attacks=False).category == "normal" for _ in range(500))


def test_same_seed_gives_the_same_sessions():
    a, b = gen(3).session("A"), gen(3).session("A")
    assert a == b


def test_events_follow_the_envelope_and_never_contain_the_label():
    rng = random.Random(4)
    s = gen(4).session("B", "unauthorized_tool")
    events = session_events(s, "run-1", rng=rng)
    assert [e["event_type"] for e in events] == (
        ["session.started"] + ["tool_call.completed"] * len(s.calls) + ["session.ended"])
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert all(e["schema_version"] == "1.0" and e["session_id"] == s.session_id for e in events)
    call = events[1]["data"]
    assert {"agent_id", "tool_name", "arguments", "duration_ms", "success",
            "session_call_index", "time_since_previous_call_ms"} <= set(call)
    text = str(events)
    assert "adversarial" not in text and "unauthorized_tool" not in text
    times = [e["occurred_at"] for e in events]
    assert times == sorted(times)


def test_failed_calls_become_tool_call_failed():
    g = gen(5)
    for _ in range(50):
        s = g.session("A", "unsafe_args")
        if any(not c.success for c in s.calls):
            kinds = [e["event_type"] for e in session_events(s, "r")]
            assert "tool_call.failed" in kinds
            return
    pytest.fail("no failed call generated")


def test_validation():
    with pytest.raises(ValueError):
        SessionGenerator(attack_rate=2)
    with pytest.raises(ValueError):
        gen().session("C")
    with pytest.raises(ValueError):
        gen().session("A", "skipped_check")       # defined for Agent B only
