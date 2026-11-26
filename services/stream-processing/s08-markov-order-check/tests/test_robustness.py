import copy
import os
from pathlib import Path

import pytest
from conftest import make_model, strip_wall_clock

from markov_order_check.config import Settings
from markov_order_check.demo import session_events
from markov_order_check.replay import SessionRecord, evaluate, read_sessions, replay

NORMAL = ["find_contact", "get_current_datetime", "get_free_slots", "tone_checker", "sensitive_content_scan",
          "save_draft"]


_FIXED = None


def _records():
    """The same sessions (same ids) on every call, as fresh copies."""
    global _FIXED
    if _FIXED is None:
        _FIXED = _build_records()
    return copy.deepcopy(_FIXED)


def _build_records():
    sessions = [NORMAL, NORMAL[:3] + ["save_draft"], ["find_contact", "save_draft", "save_draft"], []]
    recs = []
    for i, tools in enumerate(sessions):
        events = session_events("B", tools, session_id=f"s{i}")
        recs.append(SessionRecord(f"s{i}", events, category="normal" if i < 2 else "adversarial",
                                  attack_type=None if i < 2 else "draft_flooding", start_time=str(i)))
    return recs


def _canonical(outputs):
    return sorted(str(strip_wall_clock(o.event)) for o in outputs)


def test_shuffled_and_duplicated_replays_match_clean_replay():
    model = make_model("B")
    clean, _ = replay(_records(), model, Settings())
    shuffled, _ = replay(_records(), model, Settings(), shuffle=3, seed=7)
    doubled, _ = replay(_records(), model, Settings(), duplicate_rate=0.5, seed=7)
    assert _canonical(shuffled) == _canonical(clean)
    assert _canonical(doubled) == _canonical(clean)


def test_output_event_ids_are_deterministic():
    model = make_model("B")
    a, _ = replay(_records(), model, Settings())
    b, _ = replay(_records(), model, Settings())
    assert [o.event["event_id"] for o in a] == [o.event["event_id"] for o in b]


def test_dropped_calls_and_restart_mark_incomplete_without_crashing():
    model = make_model("B")
    _, outcomes = replay(_records(), model, Settings(), drop_rate=0.3, seed=1)
    _, outcomes_restart = replay(_records(), model, Settings(), restart_at=0.5)
    assert len(outcomes) == len(outcomes_restart) == 4


def test_evaluation_reports_with_and_without_empty_sessions():
    model = make_model("B")
    _, outcomes = replay(_records(), model, Settings())
    metrics = evaluate(outcomes)
    assert metrics["with_empty"]["draft_flooding"]["sessions"] == 2
    assert metrics["without_empty"]["draft_flooding"]["sessions"] == 1
    assert metrics["with_empty"]["draft_flooding"]["call_alert_rate"] == 0.5


def _agent_a_dataset() -> Path | None:
    """AGENT_A_DATASET if set, else dataset/agent_a/all-events.jsonl in the repository (when the tests run from it)."""
    if os.getenv("AGENT_A_DATASET"):
        return Path(os.environ["AGENT_A_DATASET"])
    here = Path(__file__).resolve()
    if len(here.parents) > 4:  # <repo>/services/stream-processing/s08-markov-order-check/tests/
        candidate = here.parents[4] / "dataset" / "agent_a" / "all-events.jsonl"
        if candidate.is_file():
            return candidate
    return None


AGENT_A_DATASET = _agent_a_dataset()


@pytest.mark.skipif(AGENT_A_DATASET is None,
                    reason="Agent A's recorded JSONL not found: set AGENT_A_DATASET, or add "
                           "dataset/agent_a/all-events.jsonl to the repository")
def test_agent_a_recorded_file_replays():
    from markov_order_check.demo import DEMO_VOCABULARY, build_table
    from markov_order_check.scoring import MarkovModel

    sessions = read_sessions(AGENT_A_DATASET)
    normal = []
    for rec in sessions:
        if rec.category != "normal":
            continue
        reqs = sorted((e for e in rec.events if e["event_type"] == "tool_call.requested"),
                      key=lambda e: e["data"]["session_call_index"])
        normal.append([e["data"].get("name", "<UNK>") for e in reqs])
    model = MarkovModel(build_table(normal, vocabulary=DEMO_VOCABULARY["A"], orders=(1,)), version="t", agent="A")
    _, outcomes = replay(sessions, model, Settings())
    assert all(o.complete for o in outcomes.values())  # sequence-ordered replay closes every session cleanly
    assert sum(o.n_calls for o in outcomes.values()) == sum(
        1 for r in sessions for e in r.events if e["event_type"] == "tool_call.requested")
