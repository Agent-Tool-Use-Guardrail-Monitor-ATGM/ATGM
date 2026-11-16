"""Contract with the scenario generator (services/mocks).

tests/fixtures/scenarios.jsonl was exported from the mocks' SessionGenerator (seed 20261115, today
2026-11-15): 60 normal and 8 of every attack type per agent, with its ground-truth `violated_rules`.
Every scenario is replayed through the real message path (JSON bytes -> AllowListService) and the
flags are compared with the labels. Regenerate the fixture when the generator changes.
"""
import json
from collections import defaultdict
from pathlib import Path

import pytest

from allow_list.detector import AllowListDetector
from allow_list.service import AllowListService

FIXTURE = Path(__file__).parent / "fixtures" / "scenarios.jsonl"
TOOLSETS = {
    "A": ["inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns", "finalize_statistics"],
    "B": ["find_contact", "get_current_datetime", "get_free_slots", "save_draft", "tone_checker",
          "sensitive_content_scan"],
}
# The generator labels contact_harvesting with the task-derived `contact_name_not_allowed` as well. Without
# the user's prompt the service sees that rule only when the lookup is a wildcard; the call cap catches the rest.
TASK_DERIVED_GAP = {"contact_harvesting": {"contact_name_not_allowed"}}
A_EXPECTED = {"unauthorized_tool": {"tool_not_allowed"}, "out_of_order": {"precondition_missing"},
              "unsafe_args": {"path_traversal", "argument_too_large"}}


def replay(scenario) -> set[str]:
    svc = AllowListService(AllowListDetector(), "toolset-config", "flags")
    for agent, tools in TOOLSETS.items():
        svc.handle("toolset-config", agent.encode(), json.dumps({"agent_id": agent, "allowed_tools": tools}).encode())
    agent, sid, topic = scenario["agent"], scenario["scenario_id"], f"tool-calls.{scenario['agent']}"
    events = [{"event_type": "session.started", "session_id": sid, "data": {"agent_id": agent}}]
    for i, c in enumerate(scenario["reference_calls"], start=1):
        events.append({"event_type": "tool_call.completed", "event_id": f"{sid}-{i}", "session_id": sid,
                       "sequence": i + 1, "occurred_at": "2026-11-15T12:00:00+00:00",
                       "data": {"agent_id": agent, "tool_name": c["tool"], "arguments": c["arguments"],
                                "success": True, "session_call_index": i}})
    events.append({"event_type": "session.ended", "session_id": sid, "data": {"agent_id": agent}})
    flagged = set()
    for e in events:
        flagged |= {f["data"]["rule"] for _, _, f in svc.handle(topic, sid.encode(), json.dumps(e).encode())}
    return flagged


@pytest.fixture(scope="module")
def results():
    out = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        s = json.loads(line)
        out.append((s, replay(s)))
    return out


def test_fixture_covers_both_agents_and_every_attack(results):
    seen = {(s["agent"], s["attack_type"]) for s, _ in results}
    assert {("A", None), ("B", None)} <= seen
    assert len(seen) == 2 + 3 + 9


def test_normal_sessions_are_never_flagged(results):
    normal = [(s, f) for s, f in results if s["category"] == "normal"]
    assert len(normal) == 120
    assert [(s["scenario_kind"], f) for s, f in normal if f] == []


def test_every_adversarial_session_is_flagged(results):
    missed = [s["attack_type"] for s, f in results if s["category"] == "adversarial" and not f]
    assert missed == []


def test_agent_b_flags_equal_the_labels(results):
    for s, flagged in results:
        if s["agent"] == "B" and s["category"] == "adversarial":
            labels = set(s["violated_rules"])
            assert flagged <= labels, (s["attack_type"], flagged, labels)        # never a rule the label lacks
            assert flagged >= labels - TASK_DERIVED_GAP.get(s["attack_type"], set()), (s["attack_type"], flagged, labels)


def test_agent_a_attacks_are_flagged_by_the_matching_rule(results):
    for s, flagged in results:
        if s["agent"] == "A" and s["category"] == "adversarial":
            allowed = A_EXPECTED[s["attack_type"]]
            assert flagged & allowed, (s["attack_type"], flagged)
            assert flagged <= allowed | {"precondition_missing"}, (s["attack_type"], flagged)


def test_detection_per_attack_type(results):
    rules = defaultdict(set)
    for s, f in results:
        if s["category"] == "adversarial" and s["agent"] == "B":
            rules[s["attack_type"]] |= f
    assert rules["recipient_hijack"] == {"recipient_not_allowed"}       # argument-only attack: caught here only
    assert rules["invalid_date"] == {"date_invalid_format", "date_out_of_window"}
    assert rules["post_check_tamper"] == {"secret_in_args", "unscanned_content"}
