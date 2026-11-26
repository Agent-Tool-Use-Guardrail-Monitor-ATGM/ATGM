"""Extract observable tool-call features for B2 violation classification."""
import json
import re
from collections import Counter
from itertools import pairwise

KNOWN_TOOLS = {
    "find_contact",
    "get_current_datetime",
    "get_free_slots",
    "save_draft",
    "tone_checker",
    "sensitive_content_scan",
}

SECRET_LIKE = re.compile(
    r"password|secret|api[_-]?key|token|"
    r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b",
    re.IGNORECASE,
)

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def argument_text(call: dict) -> str:
    return json.dumps(
        call.get("arguments") or {},
        ensure_ascii=False,
        default=str,
    )


def _ran_before(tools: list[str], first: str, then: str) -> bool:
    """Check whether first ran before the first occurrence of then."""
    if then not in tools:
        return True
    return first in tools[:tools.index(then)]


def session_features(calls: list[dict]) -> dict:
    """Build features from tool calls only, never from labels or scenario metadata."""
    tools = [
        call.get("tool_name") or call.get("name") or "unknown"
        for call in calls
    ]
    texts = [argument_text(call) for call in calls]
    durations = [call.get("duration_ms") or 0 for call in calls]
    gaps = [
        call.get("time_since_previous_call_ms") or 0
        for call in calls[1:]
    ]

    features = {
        "n_calls": len(calls),
        "n_distinct_tools": len(set(tools)),
        "n_failed": sum(not call.get("success", True) for call in calls),
        "unknown_tool_used": int(
            any(tool not in KNOWN_TOOLS for tool in tools)
        ),
        "mean_duration_ms": (
            sum(durations) / len(durations) if durations else 0
        ),
        "max_duration_ms": max(durations, default=0),
        "max_gap_ms": max(gaps, default=0),
        "total_argument_length": sum(map(len, texts)),
        "max_argument_length": max(map(len, texts), default=0),
        "secret_like_argument": int(
            any(SECRET_LIKE.search(text) for text in texts)
        ),
        "n_email_addresses": sum(
            len(EMAIL.findall(text)) for text in texts
        ),
        "scanned_before_save": int(
            _ran_before(tools, "sensitive_content_scan", "save_draft")
        ),
        "tone_checked_before_save": int(
            _ran_before(tools, "tone_checker", "save_draft")
        ),
        "datetime_before_slots": int(
            _ran_before(tools, "get_current_datetime", "get_free_slots")
        ),
    }

    if tools:
        features[f"first_tool={tools[0]}"] = 1
        features[f"last_tool={tools[-1]}"] = 1

    for tool, count in Counter(tools).items():
        features[f"count:{tool}"] = count

    for previous, current in pairwise(tools):
        key = f"pair:{previous}>{current}"
        features[key] = features.get(key, 0) + 1

    return features
