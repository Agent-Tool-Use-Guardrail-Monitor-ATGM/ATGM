"""Load Agent B sessions and derive multilabel targets from actual behavior."""
import json
from collections import defaultdict
from pathlib import Path

CLASSES = [
    "unauthorized_tool",
    "unsafe_args",
    "skipped_check",
    "out_of_order",
]

# No actual unauthorized_tool examples exist in the current dataset.
TRAINABLE_CLASSES = [
    "unsafe_args",
    "skipped_check",
    "out_of_order",
]

UNSAFE_RULES = {
    "secret_in_args",
    "recipient_not_allowed",
    "contact_name_not_allowed",
    "date_out_of_window",
    "date_invalid_format",
}


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def precondition_labels(calls: list[dict], policy: dict) -> set[str]:
    """Distinguish missing prerequisites from prerequisites called too late."""
    tools = [call.get("tool_name", "unknown") for call in calls]
    labels = set()

    for index, tool in enumerate(tools):
        required = policy.get("requires_before", {}).get(tool, [])

        for prerequisite in required:
            if prerequisite not in tools[:index]:
                if prerequisite in tools[index + 1:]:
                    labels.add("out_of_order")
                else:
                    labels.add("skipped_check")

    return labels


def from_files(
    dataset_dir: Path,
    scenario_file: str = "scenario_01_500.jsonl",
):
    """Return (session_id, calls, labels) using actual behavioral labels.

    Sessions with no violations receive an empty label set.
    Sessions with only violations outside the B2 taxonomy are excluded.
    """
    dataset_dir = Path(dataset_dir)

    scenarios = {
        row["scenario_id"]: row
        for row in read_jsonl(dataset_dir / "scenarios" / scenario_file)
    }

    labels_file = dataset_file = (
        dataset_dir / "labels" / f"labels_for_{scenario_file}"
    )
    events_file = (
        dataset_dir / "events" / f"events_for_{scenario_file}"
    )

    session_labels = read_jsonl(labels_file)
    events = read_jsonl(events_file)

    calls_by_session = defaultdict(list)
    for event in events:
        if event["event_type"].startswith("tool_call."):
            calls_by_session[event["session_id"]].append(event["data"])

    sessions = []
    excluded = 0

    for row in session_labels:
        session_id = row["scenario_id"]
        calls = calls_by_session.get(session_id, [])

        if not calls or session_id not in scenarios:
            continue

        calls = sorted(
            calls,
            key=lambda call: call["session_call_index"],
        )

        rules = set(row.get("violated_rules") or [])
        targets = set()

        if "tool_not_allowed" in rules:
            targets.add("unauthorized_tool")

        if rules & UNSAFE_RULES:
            targets.add("unsafe_args")

        if "precondition_missing" in rules:
            targets.update(
                precondition_labels(
                    calls,
                    scenarios[session_id]["policy"],
                )
            )

        other_rules = rules - UNSAFE_RULES - {
            "tool_not_allowed",
            "precondition_missing",
        }

        if other_rules and not targets:
            excluded += 1
            continue

        sessions.append((session_id, calls, sorted(targets)))


    print(f"Loaded {len(sessions)} sessions.")
    print(f"Excluded unmapped-only sessions: {excluded}")

    for label in CLASSES:
        positive = sum(label in targets for _, _, targets in sessions)
        print(f"  {label}: {positive} positive sessions")

    return sessions

