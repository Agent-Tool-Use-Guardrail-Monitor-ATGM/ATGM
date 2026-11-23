"""Agent A: the real statistics tools, in both message shapes the service understands.

flat        `tool_call.completed` with tool_name / arguments / success (mock agents; the example message of
            tool-calls.A), judged on the raw arguments.
run-events  the real agent's `tool_call.requested` (name + features) and `tool_call.completed` (outcome).
"""
import pytest

from allow_list.detector import AllowListDetector

A_TOOLS = ["inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns",
           "finalize_statistics", "request_clarification"]
DAY = "2026-11-22T11:46:40.494228+00:00"
UUID = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"


def detector(started=True):
    d = AllowListDetector()
    d.set_toolset("A", A_TOOLS)
    if started:
        d.start_session("s1")
    return d


def rules(violations):
    return [v.rule for v in violations]


# ----- flat events -----
def flat(d, tool, args=None, success=True, session="s1"):
    event = {"event_type": "tool_call.completed" if success else "tool_call.failed", "event_id": "e",
             "session_id": session, "occurred_at": DAY,
             "data": {"agent_id": "A", "tool_name": tool, "arguments": args or {}, "success": success}}
    return d.process(event, "A")


def test_the_example_message_of_tool_calls_a_is_clean():
    d = detector()
    event = {"schema_version": "1.0", "event_id": "8bdd2276-1537-4804-8924-13261df6ba37",
             "event_type": "tool_call.completed", "occurred_at": DAY, "run_id": "r",
             "session_id": "d787821f-27cb-4f76-bb71-afe6cdfde0d0", "sequence": 5, "request_id": None,
             "data": {"agent_id": "A", "tool_call_id": "85866ea0", "tool_name": "correlate_columns",
                      "arguments": {"dataset_id": "ds-21", "columns": ["visits", "spend"], "method": "spearman"},
                      "duration_ms": 42, "success": True, "session_call_index": 4,
                      "time_since_previous_call_ms": 642}}
    assert d.process(event, "A") == []


@pytest.mark.parametrize("tool,args", [
    ("inspect_dataset", {"dataset_id": UUID}),
    ("describe_columns", {"dataset_id": UUID, "columns": ["price", "quantity"], "missing_policy": "omit"}),
    ("describe_columns", {"dataset_id": UUID, "columns": ["price"], "missing_policy": "error"}),
    ("aggregate_statistics", {"dataset_id": UUID, "column": "price", "operation": "sum", "group_by": "region",
                              "missing_policy": "omit"}),
    ("aggregate_statistics", {"dataset_id": "ds-3", "column": "price", "operation": "count",
                              "group_by": None, "missing_policy": "error"}),
    ("correlate_columns", {"dataset_id": UUID, "x_column": "price", "y_column": "quantity", "method": "pearson",
                           "missing_policy": "pairwise_complete"}),
    ("finalize_statistics", {}),
    ("request_clarification", {}),
])
def test_every_real_tool_with_valid_arguments_is_clean(tool, args):
    assert flat(detector(), tool, args) == []


def test_a_session_may_start_with_any_numerical_tool_and_finalize_right_after():
    d = detector()                                    # the real agent mostly starts with aggregate_statistics
    assert flat(d, "aggregate_statistics", {"dataset_id": UUID, "column": "price", "operation": "mean"}) == []
    assert flat(d, "aggregate_statistics", {"dataset_id": UUID, "column": "quantity", "operation": "max"}) == []
    assert flat(d, "finalize_statistics") == []
    d.start_session("s2")                              # ... or finalize with nothing computed ("unsupported")
    assert flat(d, "finalize_statistics", session="s2") == []


def test_tools_outside_the_toolset_are_flagged():
    d = detector()
    for tool in ("export_dataset", "send_email", "run_shell"):
        (v,) = flat(d, tool, {"dataset_id": UUID, "destination": "https://paste.example/upload"}, session=tool)
        assert (v.rule, v.severity) == ("tool_not_allowed", "high")


@pytest.mark.parametrize("dataset_id", ["../../secrets/users.csv", "/etc/passwd", "~/data.csv", "C:\\data.csv",
                                        "https://paste.example/upload", "*", "ds-1; DROP TABLE x", "", " ", 7,
                                        None, "a" * 65])
def test_dataset_id_must_be_a_plain_identifier(dataset_id):
    (v,) = flat(detector(), "aggregate_statistics", {"dataset_id": dataset_id, "column": "price", "operation": "sum"})
    assert (v.rule, v.severity) == ("dataset_id_not_allowed", "high")
    assert len(v.detail) < 120                        # the offending value is shortened, never echoed whole


@pytest.mark.parametrize("tool,args,expected", [
    ("aggregate_statistics", {"dataset_id": UUID, "column": "price", "operation": "median"}, 1),
    ("aggregate_statistics", {"dataset_id": UUID, "column": "price", "operation": "sum; rm -rf"}, 1),
    ("aggregate_statistics", {"dataset_id": UUID, "column": "price", "operation": "sum", "missing_policy": "drop"}, 1),
    ("aggregate_statistics", {"dataset_id": UUID, "column": "price", "operation": "sum",
                              "missing_policy": "pairwise_complete"}, 1),              # belongs to correlate only
    ("describe_columns", {"dataset_id": UUID, "columns": ["price"], "missing_policy": "ignore"}, 1),
    ("correlate_columns", {"dataset_id": UUID, "x_column": "a", "y_column": "b", "method": "kendall"}, 1),
    ("correlate_columns", {"dataset_id": UUID, "x_column": "a", "y_column": "b", "method": "pearson",
                           "missing_policy": "omit"}, 1),                               # belongs to the others only
])
def test_enumerated_values_are_enforced_per_tool(tool, args, expected):
    out = flat(detector(), tool, args)
    assert rules(out) == ["argument_value_not_allowed"] * expected and out[0].severity == "medium"


def test_column_lists_are_capped():
    d = detector()
    assert flat(d, "describe_columns", {"dataset_id": UUID, "columns": [f"c{i}" for i in range(50)]}) == []
    d.start_session("s2")
    (v,) = flat(d, "describe_columns", {"dataset_id": UUID, "columns": [f"col_{i}" for i in range(400)]}, session="s2")
    assert (v.rule, v.severity) == ("argument_too_large", "medium")


def test_per_session_call_caps():
    d = detector()
    args = {"dataset_id": UUID, "column": "price", "operation": "sum"}
    out = [rules(flat(d, "aggregate_statistics", args)) for _ in range(8)]
    assert out == [[]] * 6 + [["max_calls_exceeded"]] * 2
    assert flat(d, "finalize_statistics") == []
    assert rules(flat(d, "finalize_statistics")) == ["max_calls_exceeded"]            # finalize ends a session


def test_failed_calls_still_count_towards_the_caps():
    d = detector()
    for _ in range(2):
        flat(d, "inspect_dataset", {"dataset_id": UUID}, success=False)
    assert rules(flat(d, "inspect_dataset", {"dataset_id": UUID})) == ["max_calls_exceeded"]


def test_several_rules_on_one_call_are_all_reported():
    out = flat(detector(), "aggregate_statistics", {"dataset_id": "../x", "column": "p", "operation": "median"})
    assert rules(out) == ["dataset_id_not_allowed", "argument_value_not_allowed"]


def test_agent_b_tools_are_not_allowed_for_agent_a():
    out = flat(detector(), "save_draft", {"to": "x@evil.example", "subject": "s", "body": "b"})
    assert rules(out) == ["tool_not_allowed"]          # and none of B's argument rules run on A's calls


# ----- run-events (real agent) -----
def requested(d, name, features=None, call_id="c1", session="s1", with_name=True):
    data = {"kind": "numerical" if name else "unknown", "features": features or {}, "tool_call_id": call_id,
            "session_call_index": 1, "payload_version": "agent-run-events-v2", "arguments_sha256": "ab"}
    if with_name and name:
        data["name"] = name
    event = {"event_type": "tool_call.requested", "event_id": f"req-{call_id}", "session_id": session,
             "occurred_at": DAY, "data": data}
    return d.process(event, "A")


def finished(d, call_id="c1", session="s1", status="completed", reason=None):
    event = {"event_type": "tool_call.completed" if status == "completed" else "tool_call.failed",
             "event_id": f"done-{call_id}", "session_id": session, "occurred_at": DAY,
             "data": {"status": status, "tool_call_id": call_id, "session_call_index": 1,
                      **({"reason": reason} if reason else {})}}
    return d.process(event, "A")


AGG = {"operation": "mean", "column_count": 1, "argument_shape": "not_checked", "missing_policy": "omit",
       "dataset_selection": "selected"}
COR = {"method": "spearman", "column_count": 2, "argument_shape": "not_checked", "missing_policy": "pairwise_complete",
       "dataset_selection": "selected"}
INS = {"column_count": 0, "argument_shape": "not_checked", "dataset_selection": "selected"}
CTL = {"column_count": 0, "argument_shape": "not_checked", "dataset_selection": "absent"}


def test_a_recorded_style_session_is_clean_and_completions_never_flag():
    d = detector()
    assert requested(d, "aggregate_statistics", AGG, "c1") == []
    assert finished(d, "c1") == []
    assert requested(d, "correlate_columns", COR, "c2") == []
    assert finished(d, "c2") == []
    assert requested(d, "finalize_statistics", CTL, "c3") == []
    assert finished(d, "c3") == []


def test_control_tools_need_no_dataset_but_numerical_tools_do():
    d = detector()
    assert requested(d, "request_clarification", CTL, "c1") == []
    (v,) = requested(d, "aggregate_statistics", {**AGG, "dataset_selection": "absent"}, "c2")
    assert (v.rule, v.severity) == ("dataset_not_selected", "medium")


def test_a_request_without_a_tool_name_is_a_tool_not_allowed():
    d = detector()
    (v,) = requested(d, None, {"column_count": 0, "argument_shape": "not_checked", "dataset_selection": "absent"},
                     with_name=False)
    assert (v.rule, v.severity) == ("tool_not_allowed", "high") and "without a resolvable tool name" in v.detail


def test_features_are_checked_like_arguments():
    d = detector()
    for i, (name, features, rule) in enumerate([
            ("aggregate_statistics", {**AGG, "operation": "median"}, "argument_value_not_allowed"),
            ("aggregate_statistics", {**AGG, "missing_policy": "drop"}, "argument_value_not_allowed"),
            ("correlate_columns", {**COR, "method": "kendall"}, "argument_value_not_allowed"),
            ("describe_columns", {**AGG, "column_count": 400}, "argument_too_large")]):
        assert rules(requested(d, name, features, f"x{i}", session=f"f{i}")) == [rule], name


def test_a_call_is_judged_once_at_its_request():
    d = detector()
    assert rules(requested(d, "export_dataset", INS, "c1")) == ["tool_not_allowed"]
    assert finished(d, "c1", status="failed", reason="unknown_tool") == []


def test_run_events_calls_count_towards_the_caps_from_the_request_on():
    d = detector()
    out = []
    for i in range(7):                               # no completion in between: counted when requested
        out.append(rules(requested(d, "aggregate_statistics", AGG, f"c{i}")))
    assert out == [[]] * 6 + [["max_calls_exceeded"]]


def test_a_completion_without_a_known_request_is_ignored():
    d = detector()
    assert finished(d, "never-requested") == []
    assert finished(d, "x", session="unknown-session") == []


def test_unseen_session_is_still_checked_on_stateless_rules():
    d = detector(started=False)
    assert rules(requested(d, "export_dataset", INS, "c1", session="late")) == ["tool_not_allowed"]
