"""Agent B scenarios: prompts, policies and labels.

Checking calls against a policy is the job of the separate `allow-list` service; its contract test
(allow-list/tests/test_contract_mocks.py) replays scenarios exported from this generator and compares
the flags with `violated_rules`. The tests here only check the generator's own structure.
"""
import json
import random
from datetime import date

import pytest

from atgm_mocks.domain.agent_b import ATTACKS_B, CONTACTS, POLICY_ONLY_ATTACKS
from atgm_mocks.domain.policy import RULES
from atgm_mocks.domain.sessions import SessionGenerator
from atgm_mocks.envelope import session_events

TODAY = date(2026, 11, 15)


def gen(seed=0):
    return SessionGenerator(random.Random(seed), attack_rate=0, today=TODAY)


def test_normal_sessions_have_a_prompt_a_policy_and_no_labels():
    g = gen()
    kinds = set()
    for _ in range(1000):
        s = g.session("B")
        kinds.add(s.scenario_kind)
        assert s.category == "normal" and s.prompt and s.policy
        assert not s.adversarial_text and not s.violated_rules
        # a normal session follows its own policy
        assert {c.tool for c in s.calls} <= set(s.policy["allowed_tools"])
        saves = [c for c in s.calls if c.tool == "save_draft"]
        assert len(saves) <= s.policy["max_calls"]["save_draft"]
        assert all(c.arguments["to"] in s.policy["allowed_recipients"] for c in saves)
    assert kinds == {"contact_email", "meeting_request", "casual_invite", "explicit_address", "unknown_contact"}


@pytest.mark.parametrize("attack", ATTACKS_B)
def test_each_attack_is_labelled_and_its_fragment_is_in_the_prompt(attack):
    g = gen(1)
    for _ in range(300):
        s = g.session("B", attack)
        assert s.category == "adversarial" and s.attack_type == attack
        assert s.violated_rules and set(s.violated_rules) <= set(RULES)
        assert s.adversarial_text and s.adversarial_text in s.prompt


def test_every_rule_is_covered_by_some_attack():
    g, covered = gen(2), set()
    for attack in ATTACKS_B:
        for _ in range(100):
            covered |= set(g.session("B", attack).violated_rules)
    assert covered == set(RULES)


def test_all_six_tools_appear_in_normal_sessions():
    g, tools = gen(3), set()
    for _ in range(300):
        tools |= {c.tool for c in g.session("B").calls}
    assert tools == {"find_contact", "get_current_datetime", "get_free_slots", "save_draft",
                     "tone_checker", "sensitive_content_scan"}


def test_arguments_match_the_real_tool_signatures():
    g = gen(4)
    expected = {"find_contact": {"name"}, "get_current_datetime": set(), "get_free_slots": {"date"},
                "save_draft": {"to", "subject", "body"}, "tone_checker": {"draft", "requested_tone"},
                "sensitive_content_scan": {"text"}}
    for _ in range(300):
        for c in g.session("B").calls:
            assert set(c.arguments) == expected[c.tool]


def test_dates_follow_the_calendar_and_the_prompt():
    g = gen(5)
    for _ in range(200):
        s = g.session("B", None)
        for c in s.calls:
            if c.tool == "get_free_slots":
                d = date.fromisoformat(c.arguments["date"])
                assert 1 <= (d - TODAY).days <= 14 and d.weekday() < 5


def test_contacts_in_prompts_are_known_and_emails_match_the_address_book():
    g = gen(6)
    emails = {c.email for c in CONTACTS.values()}
    for _ in range(300):
        s = g.session("B")
        for c in s.calls:
            if c.tool == "save_draft" and s.scenario_kind != "explicit_address":
                assert c.arguments["to"] in emails
            if c.tool == "find_contact":
                assert c.arguments["name"] in s.prompt


def test_policy_is_json_serialisable_and_labels_stay_out_of_events():
    g = gen(7)
    s = g.session("B", "recipient_hijack")
    json.dumps(s.policy)
    text = str(session_events(s, "r"))
    assert s.prompt not in text and "recipient_hijack" not in text and "backup@" not in s.policy.__str__()


def test_policy_only_attacks_are_real_attacks():
    assert set(POLICY_ONLY_ATTACKS) <= set(ATTACKS_B)


def test_agent_a_sessions_have_no_agent_b_fields():
    s = gen().session("A")
    assert s.prompt == "" and s.policy == {} and s.violated_rules == []


def test_same_seed_same_scenarios():
    assert [gen(8).session("B", a) for a in ATTACKS_B] == [gen(8).session("B", a) for a in ATTACKS_B]


def test_export_writes_one_valid_json_line_per_scenario(tmp_path):
    from atgm_mocks.export_scenarios import main
    out = tmp_path / "s.jsonl"
    main(["--n", "40", "--seed", "1", "--attack-rate", "0.5", "--today", "2026-11-15", "--out", str(out)])
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 40 and {r["category"] for r in rows} == {"normal", "adversarial"}
    assert all(r["prompt"] and r["policy"] and r["reference_calls"] is not None for r in rows)
    main(["--n", "5", "--attack", "draft_flooding", "--seed", "2", "--out", str(out)])
    assert {json.loads(line)["attack_type"] for line in out.read_text(encoding="utf-8").splitlines()} == {"draft_flooding"}
