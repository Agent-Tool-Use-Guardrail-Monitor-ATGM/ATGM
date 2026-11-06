from typing import Any

FEATURE_NAMES = [
    "duration_ms",
    "argument_count",
    "argument_length",
    "session_call_index",
    "time_since_previous_call_ms",
    "success",
]


def extract_features(event: dict[str, Any]) -> list[float]:
    arguments = event.get("arguments", {})

    return [
        float(event.get("duration_ms", 0)),
        float(len(arguments)),
        float(len(str(arguments))),
        float(event.get("session_call_index", 0)),
        float(event.get("time_since_previous_call_ms", 0)),
        1.0 if event.get("success", True) else 0.0,
    ]