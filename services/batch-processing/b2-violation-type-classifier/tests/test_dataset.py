import json

from b2_classifier.adapters.dataset import from_files


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_loads_actual_behavior_labels_and_normal_sessions(tmp_path):
    scenario = {
        "scenario_id": "session-1",
        "policy": {"requires_before": {}},
    }
    normal_scenario = {
        "scenario_id": "session-2",
        "policy": {"requires_before": {}},
    }
    labels = [
        {
            "scenario_id": "session-1",
            "violated_rules": ["secret_in_args", "recipient_not_allowed"],
        },
        {
            "scenario_id": "session-2",
            "violated_rules": [],
        },
    ]
    events = [
        {
            "session_id": "session-1",
            "event_type": "tool_call.save_draft",
            "data": {"tool_name": "save_draft", "session_call_index": 0},
        },
        {
            "session_id": "session-2",
            "event_type": "tool_call.find_contact",
            "data": {"tool_name": "find_contact", "session_call_index": 0},
        },
    ]

    write_jsonl(
        tmp_path / "scenarios" / "scenario_01_500.jsonl",
        [scenario, normal_scenario],
    )
    write_jsonl(
        tmp_path / "labels" / "labels_for_scenario_01_500.jsonl",
        labels,
    )
    write_jsonl(
        tmp_path / "events" / "events_for_scenario_01_500.jsonl",
        events,
    )

    sessions = from_files(tmp_path)

    assert len(sessions) == 2
    assert sessions[0][0] == "session-1"
    assert sessions[0][2] == ["unsafe_args"]
    assert sessions[1][0] == "session-2"
    assert sessions[1][2] == []


def test_excludes_sessions_with_only_unmapped_violations(tmp_path):
    write_jsonl(
        tmp_path / "scenarios" / "scenario_01_500.jsonl",
        [{"scenario_id": "session-1", "policy": {"requires_before": {}}}],
    )
    write_jsonl(
        tmp_path / "labels" / "labels_for_scenario_01_500.jsonl",
        [{"scenario_id": "session-1", "violated_rules": ["max_calls_exceeded"]}],
    )
    write_jsonl(
        tmp_path / "events" / "events_for_scenario_01_500.jsonl",
        [{
            "session_id": "session-1",
            "event_type": "tool_call.save_draft",
            "data": {"tool_name": "save_draft", "session_call_index": 0},
        }],
    )

    sessions = from_files(tmp_path)

    assert sessions == [] or all(row[0] != "session-1" for row in sessions)
