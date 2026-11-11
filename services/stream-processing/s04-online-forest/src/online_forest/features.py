from typing import Any
from .events import payload

FEATURE_NAMES = [
    "duration_ms",
    "argument_count",
    "argument_length",
    "session_call_index",
    "time_since_previous_call_ms",
    "success",
]

def extract_features(event: dict[str, Any]) -> list[float]:
    p = payload(event)
    arguments = p.get("arguments") or {}

    return [
        float(p.get("duration_ms", 0)),
        float(len(arguments)),
        float(len(str(arguments))),
        float(p.get("session_call_index", 0)),
        float(p.get("time_since_previous_call_ms", 0)),
        1.0 if p.get("success", True) else 0.0,
    ]