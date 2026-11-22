"""Recorded Agent A traffic (tests/fixtures/agent_a_real.jsonl, built from a real dataset of 130 sessions:
73 normal, 57 direct-prompt-injection) replayed through the real message path.

The real agent publishes `agent-run-events-v2`: tool name and coarse features at `tool_call.requested`, the
outcome at `tool_call.completed` / `tool_call.failed`, never the arguments. So this checks the tool allow-list,
the call caps and the feature rules on real behaviour; the argument rules are covered in test_agent_a.py.
Rebuild the fixture with tests/fixtures/build_agent_a_real.py.
"""
import json
from collections import defaultdict
from pathlib import Path

import pytest

from allow_list.detector import AllowListDetector
from allow_list.service import AllowListService

FIXTURE = Path(__file__).parent / "fixtures" / "agent_a_real.jsonl"
A_TOOLS = ["inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns",
           "finalize_statistics", "request_clarification"]


@pytest.fixture(scope="module")
def sessions():
    by = defaultdict(list)
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        by[row["event"]["session_id"]].append(row)
    return {sid: sorted(rows, key=lambda r: r["event"]["sequence"]) for sid, rows in by.items()}


def replay(sessions, tools=A_TOOLS):
    """session id -> list of (rule, tool_name) flags, using JSON bytes on `tool-calls.A` like Kafka does."""
    svc = AllowListService(AllowListDetector(), "toolset-config", "flags")
    svc.handle("toolset-config", b"A", json.dumps({"agent_id": "A", "allowed_tools": tools}).encode())
    flags = {}
    for sid, rows in sessions.items():
        flags[sid] = [(f["data"]["rule"], f["data"]["tool_name"])
                      for r in rows for _, _, f in svc.handle("tool-calls.A", sid.encode(),
                                                              json.dumps(r["event"]).encode())]
    return flags


def requests(rows):
    return [r["event"]["data"] for r in rows if r["event"]["event_type"] == "tool_call.requested"]


def test_fixture_is_the_recorded_dataset(sessions):
    assert len(sessions) == 130
    assert sum(rows[0]["category"] == "normal" for rows in sessions.values()) == 73
    assert {r["event"]["event_type"] for rows in sessions.values() for r in rows} == {
        "session.started", "tool_call.requested", "tool_call.completed", "tool_call.failed", "session.ended"}


def test_the_only_flags_are_requests_for_a_tool_the_runner_could_not_name(sessions):
    unnamed = {sid for sid, rows in sessions.items() if any("name" not in d for d in requests(rows))}
    flags = replay(sessions)
    assert {sid for sid, f in flags.items() if f} == unnamed
    assert len(unnamed) == 16
    assert {rule for f in flags.values() for rule, _ in f} == {"tool_not_allowed"}
    assert all(len(f) == 1 and f[0][1] is None for f in flags.values() if f)           # one flag, no name known


def test_no_session_that_stays_inside_the_toolset_is_flagged(sessions):
    """No false positives: the caps, the enumerations and the dataset rule never fire on recorded behaviour."""
    flags = replay(sessions)
    named = [sid for sid, rows in sessions.items() if all("name" in d for d in requests(rows))]
    assert len(named) == 114 and all(flags[sid] == [] for sid in named)


def test_injected_sessions_use_the_same_toolset_as_normal_ones(sessions):
    """The recorded injection scenarios change what the agent says, not which tools it calls. A tool-level
    allow-list therefore cannot tell them apart: it flags them only for the same unresolvable-tool requests."""
    flags = replay(sessions)
    injected = [sid for sid, rows in sessions.items() if rows[0]["category"] != "normal"]
    assert len(injected) == 57
    for sid in injected:
        assert {d["name"] for d in requests(sessions[sid]) if "name" in d} <= set(A_TOOLS)
        assert all(rule == "tool_not_allowed" for rule, _ in flags[sid])


def test_revoking_a_tool_flags_exactly_its_calls(sessions):
    without = [t for t in A_TOOLS if t != "finalize_statistics"]
    flags = replay(sessions, without)
    expected = sum(d.get("name") == "finalize_statistics" for rows in sessions.values() for d in requests(rows))
    got = sum(tool == "finalize_statistics" for f in flags.values() for _, tool in f)
    assert expected == got == 55
    assert all(rule == "tool_not_allowed" for f in flags.values() for rule, _ in f)


def test_a_four_tool_toolset_flags_the_control_tools(sessions):
    """tools.zip lists the four numerical tools; the recorded traffic also uses two control tools. If
    toolset-config only lists the four, every finalize_statistics / request_clarification is flagged."""
    flags = replay(sessions, A_TOOLS[:4])
    control = sum(d.get("name") in ("finalize_statistics", "request_clarification")
                  for rows in sessions.values() for d in requests(rows))
    assert control == 79
    assert sum(tool in ("finalize_statistics", "request_clarification") for f in flags.values() for _, tool in f) == 79


def test_a_denial_by_the_runner_for_invalid_arguments_is_invisible_without_arguments(sessions):
    """One recorded session was denied by the agent's own policy (`invalid_arguments`). Its published features
    (pearson, 2 columns, dataset selected) are all inside the allow-list, so nothing can be flagged: telling
    it apart needs the arguments themselves in the event."""
    (sid,) = [s for s, rows in sessions.items()
              if any(r["event"]["data"].get("reason") == "policy_denied" for r in rows)]
    assert replay(sessions)[sid] == []
