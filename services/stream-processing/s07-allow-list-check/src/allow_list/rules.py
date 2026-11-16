"""Argument checks. Each takes (spec, value, today) and returns [(rule_id, detail)] for what it found.

Details never contain secret values: credentials are reported by type only.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

_ADDRESS = re.compile(r"[^\s@,;<>\"']+@([^\s@,;<>\"']+\.[A-Za-z]{2,})")
_NAME = re.compile(r"[A-Za-z][A-Za-z.' -]{0,39}")
_WILDCARD_NAMES = {"all", "everyone", "everybody", "any", "anyone"}
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# name -> regex; "credit_card" is additionally Luhn-checked
SECRET_PATTERNS = {
    "credential": r"\b(?:password|passwd|pwd|passcode|secret|api[_ -]?key|access[_ -]?key|token)\b\s*[:=]\s*['\"]?[^\s'\",;]{4,}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "aws_access_key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "api_key": r"\bsk-[A-Za-z0-9_-]{20,}\b",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    "credit_card": r"\b(?:\d[ -]?){12,18}\d\b",
}
PATH_PATTERNS = {"path_traversal": r"(?:^|[\\/])\.\.(?:[\\/]|$)|^[\\/~]|^[A-Za-z]:\\"}
_BUILTIN_SETS = {"secrets": SECRET_PATTERNS, "paths": PATH_PATTERNS}


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _show(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return repr(text[:60] + ("..." if len(text) > 60 else ""))


def check_date_window(spec, value, today: date):
    """get_free_slots.date must be a real YYYY-MM-DD date inside [today - days_back, today + days_ahead]."""
    try:
        if not isinstance(value, str) or not _DATE.fullmatch(value):
            raise ValueError
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return [("date_invalid_format", f"{_show(value)} is not a YYYY-MM-DD date")]
    lo, hi = today - timedelta(days=spec.get("days_back", 0)), today + timedelta(days=spec.get("days_ahead", 30))
    if not lo <= d <= hi:
        return [("date_out_of_window", f"{value} is outside {lo}..{hi}")]
    return []


def check_single_address(spec, value, today):
    """One well-formed address (no list, no line break) whose domain is on the allow-list."""
    m = _ADDRESS.fullmatch(value) if isinstance(value, str) else None
    if m is None:
        return [("recipient_not_allowed", f"{_show(value)} is not a single e-mail address")]
    domain = m.group(1).lower()
    if domain not in {d.lower() for d in spec.get("allowed_domains", [])}:
        return [("recipient_not_allowed", f"domain {domain!r} is not an allowed recipient domain")]
    return []


def check_plain_name(spec, value, today):
    """A person's name, not a wildcard or an injected expression."""
    if not isinstance(value, str) or not _NAME.fullmatch(value.strip()) or value.strip().lower() in _WILDCARD_NAMES:
        return [("contact_name_not_allowed", f"{_show(value)} is not a plain contact name")]
    return []


def check_forbidden_pattern(spec, value, today):
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    patterns = dict(_BUILTIN_SETS[spec["set"]]) if "set" in spec else {}
    patterns.update({f"pattern_{i}": r for i, r in enumerate(spec.get("regexes", []))})
    found = []
    for name, regex in patterns.items():
        for m in re.finditer(regex, text, re.IGNORECASE if name != "credit_card" else 0):
            if name == "credit_card":
                digits = re.sub(r"\D", "", m.group())
                if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                    continue
            found.append((spec["rule"], f"{name.replace('_', ' ')} in argument"))
            break
    return found


def check_max_items(spec, value, today):
    if isinstance(value, (list, tuple, dict, str)) and len(value) > spec["max"]:
        return [(spec["rule"], f"{len(value)} items, at most {spec['max']} allowed")]
    return []


def check_no_newlines(spec, value, today):
    if isinstance(value, str) and re.search(r"[\r\n]", value):
        return [(spec.get("rule", "header_injection"), "line break in a value written into a file header")]
    return []


CHECKS = {
    "date_window": check_date_window,
    "single_address": check_single_address,
    "plain_name": check_plain_name,
    "forbidden_pattern": check_forbidden_pattern,
    "max_items": check_max_items,
    "no_newlines": check_no_newlines,
}
