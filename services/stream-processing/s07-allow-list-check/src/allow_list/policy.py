"""The allow-list policy: severity per rule, plus one policy per agent (policies/agent_a.py, agent_b.py).

Which tools an agent may call at all comes live from the `toolset-config` topic, not from here.
Everything below is static and needs only what a tool-call event carries (tool name, arguments or
features, session). Replace the whole policy with a JSON file of the same shape via POLICY_FILE.

Per agent: max_calls (per session), requires_before (ALL listed tools must have succeeded first),
arguments (checks on argument values or features), consistency (text saved must equal text scanned).

Rules (ids are shared with the scenario generator's ground truth):
    tool_not_allowed          tool is not in the agent's current toolset (or has no resolvable name)  high
    recipient_not_allowed     save_draft.to is not ONE address on an allowed domain                    high
    secret_in_args            credential / card number in a saved draft                                high
    unscanned_content         saved subject/body differ from what the scan saw                         high
    dataset_id_not_allowed    dataset_id is not a plain identifier (path, URL, wildcard)  (Agent A)    high
    header_injection          line break in save_draft.subject                                         high
    contact_name_not_allowed  find_contact name is a wildcard / not a plain name                       medium
    max_calls_exceeded        a tool was called more often than max_calls allows                       medium
    precondition_missing      a tool ran before the tools it requires                                  medium
    argument_too_large        too many columns (Agent A)                                               medium
    argument_value_not_allowed operation / method / missing_policy outside its enum (Agent A)          medium
    dataset_not_selected      a numerical tool without a selected dataset (Agent A)                    medium
    date_invalid_format       get_free_slots.date is not a real YYYY-MM-DD date                        medium
    date_out_of_window        date is outside today .. today + days_ahead                              low
"""
from __future__ import annotations

import json

from allow_list.policies import agent_a, agent_b

POLICY_VERSION = "allow-list-2"

# Re-exported: the recipient domains of Agent B's policy (set your own through POLICY_FILE)
ALLOWED_RECIPIENT_DOMAINS = agent_b.ALLOWED_RECIPIENT_DOMAINS

DEFAULT_POLICY = {
    "version": POLICY_VERSION,
    "severity": {
        "tool_not_allowed": "high", "recipient_not_allowed": "high", "secret_in_args": "high",
        "unscanned_content": "high", "dataset_id_not_allowed": "high", "header_injection": "high",
        "contact_name_not_allowed": "medium", "max_calls_exceeded": "medium", "precondition_missing": "medium",
        "argument_too_large": "medium", "argument_value_not_allowed": "medium", "dataset_not_selected": "medium",
        "date_invalid_format": "medium", "date_out_of_window": "low",
    },
    "agents": {"A": agent_a.POLICY, "B": agent_b.POLICY},
}


def load_policy(path: str | None = None) -> dict:
    if not path:
        return DEFAULT_POLICY
    with open(path, encoding="utf-8") as f:
        policy = json.load(f)
    if not isinstance(policy.get("agents"), dict):
        raise ValueError("policy file needs an 'agents' object")
    policy.setdefault("version", "custom")
    policy.setdefault("severity", DEFAULT_POLICY["severity"])
    return policy
