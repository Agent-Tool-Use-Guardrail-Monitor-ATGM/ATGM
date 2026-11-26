"""Turns one session (its tool calls in order) into features for the classifier.

Only what a detector could see is used: tool names, their order, timings, success and arguments.
The scenario's category and attack type (in session.started) are never used, they are the answer.
"""
import json
import re
from collections import Counter
from itertools import pairwise
KNOWN_TOOLS = {"find_contact", "get_current_datetime", "get_free_slots", "save_draft",
               "tone_checker", "sensitive_content_scan"}
KNOWN_TOOLS_A = {"inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns",
                 "finalize_statistics", "request_clarification"}
SECRET_LIKE = re.compile(r"password|\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def argument_text(call: dict) -> str:
    return json.dumps(call.get("arguments") or {}, ensure_ascii=False)


def session_features(calls: list[dict], known_tools: set[str] = KNOWN_TOOLS) -> dict:
    tools = [call["tool_name"] for call in calls]
    texts = [argument_text(call) for call in calls]
    durations = [call.get("duration_ms") or 0 for call in calls]
    gaps = [call.get("time_since_previous_call_ms") or 0 for call in calls[1:]]

    features = {
        "n_calls": len(calls),
        "n_distinct_tools": len(set(tools)),
        "n_failed": sum(1 for call in calls if not call.get("success", True)),
        "unknown_tool_used": int(any(tool not in known_tools for tool in tools)),
        "mean_duration_ms": sum(durations) / len(durations) if durations else 0,
        "max_duration_ms": max(durations, default=0),
        "max_gap_ms": max(gaps, default=0),
        "total_argument_length": sum(len(text) for text in texts),
        "max_argument_length": max((len(text) for text in texts), default=0),
        "secret_like_argument": int(any(SECRET_LIKE.search(text) for text in texts)),
        "n_email_addresses": sum(len(EMAIL.findall(text)) for text in texts),
        "scanned_before_save": int(_ran_before(tools, "sensitive_content_scan", "save_draft")),
        "tone_checked_before_save": int(_ran_before(tools, "tone_checker", "save_draft")),
        "datetime_before_slots": int(_ran_before(tools, "get_current_datetime", "get_free_slots")),
    }
    if tools:
        features[f"first_tool={tools[0]}"] = 1
        features[f"last_tool={tools[-1]}"] = 1
    for tool, count in Counter(tools).items():
        features[f"count:{tool}"] = count
    for previous, current in pairwise(tools):                 # tool order, as pairs
        key = f"pair:{previous}>{current}"
        features[key] = features.get(key, 0) + 1
    return features


def _ran_before(tools: list[str], first: str, then: str) -> bool:
    """True if `then` was not called, or `first` ran before its first call."""
    if then not in tools:
        return True
    return first in tools[: tools.index(then)]