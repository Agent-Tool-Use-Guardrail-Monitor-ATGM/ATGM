# S07: allow-list policy check

Pipeline: Real-time allow-list policy check on each tool call.

Vulnerability: indirect prompt injection. Adversaries might embed malicious instruction within tool-returned content. [2]

Mitigation: enforce rule set at every tool-call boundary, intercept adversarial tool calls that would produce unwanted real-world effect.

**Citations:**
- [1] [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), 2025 
    - ASI02: Tool Misuse and Exploitation
    - [LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
- [2] Zhao et al., [ClawGuard](https://arxiv.org/pdf/2604.11790), 2026
- [3] Wang et al., [Runtime Policy Enforcement for MCP-Based LLM Agents](https://www.researchgate.net/publication/408199447_Runtime_Policy_Enforcement_for_MCP-Based_LLM_Agents), 2026

Owner: Agnes

## Overview

The allow-list component is a deterministic tool-call guard. It consumes the tool calls of Agent A and Agent B, checks every call against the agent's **current toolset** and a static **argument / sequence policy**, and publishes one `violation.flagged` event per broken rule to the `flags` topic.

It needs no training and no warm-up: a call is either inside the policy or it is not. It complements the anomaly detectors (for example the Online Forest), which see *unusual* behaviour but cannot see an unusual **value** in an otherwise normal call, such as a draft saved to a foreign address.

## Architecture

```text
tool-calls.A ─┐
tool-calls.B ─┼─> Kafka consumer ─> AllowListService ─> AllowListDetector ─> Kafka producer ─> flags
toolset-config ┘   (two consumers)    (routing)           (rules + session state)
```

| File | Role |
|---|---|
| `consumer.py` | Kafka glue: two consumers, producer, main loop, commits |
| `service.py` | One message in, `violation.flagged` events out (no Kafka import) |
| `detector.py` | Per-call decision, per-session state |
| `policy.py` | The built-in policy (per agent) and its JSON loader |
| `rules.py` | Argument checks used by the policy |
| `events.py` | Envelope helpers, `toolset-config` parsing, `violation.flagged` builder |
| `config.py` | Environment variables |
| `publish_toolset_config.py` | Publishes toolsets for local runs (like `send_test_events.py` in the forest) |

## Kafka

### Input

| Topic | Content |
|---|---|
| `tool-calls.A`, `tool-calls.B` | Agent A's envelope: `session.started`, `tool_call.completed` / `tool_call.failed`, `session.ended`. Calls are judged with `data.tool_name`, `data.arguments`, `data.success`; the key should be the session id so a session stays ordered. |
| `toolset-config` | The current allowed tools per agent. Read from the beginning at start-up, then followed live; the newest message per agent wins. |

`toolset-config` message (one per agent, keyed by agent id; the body may also be inside `data`):

```json
{"agent_id": "B", "allowed_tools": ["find_contact", "get_current_datetime", "get_free_slots", "save_draft", "tone_checker", "sensitive_content_scan"]}
```

A single message for several agents (`{"toolsets": {"A": [...], "B": [...]}}`) is accepted too. **This schema is an assumption; adjust `events.parse_toolset_update` if your config service publishes something else.** If no toolset is known for an agent yet, the tool allow-list is skipped for it (a warning is logged once); all other rules still run.

### Output

One event per call and broken rule, on `flags`, keyed by agent id:

```json
{
  "schema_version": "1.0", "event_id": "…", "event_type": "violation.flagged",
  "occurred_at": "…", "run_id": "…", "session_id": "…", "sequence": 6, "request_id": null,
  "data": {
    "flagged_event_id": "<event_id of the tool call>", "agent_id": "B", "tool_name": "save_draft",
    "detector": "allow_list", "policy_version": "allow-list-1",
    "rule": "recipient_not_allowed", "severity": "high",
    "detail": "domain 'mailcollector.example' is not an allowed recipient domain"
  }
}
```

`detail` never contains a secret: credentials are reported by type only.

## Rules

| Rule | Severity | Meaning |
|---|---|---|
| `tool_not_allowed` | high | Tool is not in the agent's current `toolset-config` |
| `recipient_not_allowed` | high | `save_draft.to` is not exactly one address on an allowed domain (foreign domain, several addresses, `\nBcc:` injection) |
| `secret_in_args` | high | Credential, key, JWT or Luhn-valid card number in `save_draft.subject` / `body` |
| `unscanned_content` | high | Saved subject/body is not covered by the text `sensitive_content_scan` saw (content changed after the scan) |
| `path_traversal` | high | `../` or an absolute path in Agent A's `dataset_id` |
| `header_injection` | high | Line break in `save_draft.subject` (it is written into the draft file's header) |
| `contact_name_not_allowed` | medium | `find_contact` name is a wildcard (`*`, `all`) or not a plain name |
| `max_calls_exceeded` | medium | More calls of a tool in one session than the policy allows (e.g. `save_draft` once, `get_free_slots` 5 times) |
| `precondition_missing` | medium | Tool ran before the tools it requires (e.g. `save_draft` needs `tone_checker` and `sensitive_content_scan`) |
| `argument_too_large` | medium | More than 50 columns (Agent A) |
| `date_invalid_format` | medium | `get_free_slots.date` is not a real `YYYY-MM-DD` date |
| `date_out_of_window` | low | Date is before the event day or more than 30 days after it |

### What the service can and cannot know

The service sees only tool-call events and `toolset-config`, not the user's prompt. So it enforces the **task-independent** form of each rule: "the recipient is on an allowed domain" instead of "the recipient is the contact the user named", "the name is a plain name" instead of "the name appears in the prompt". A hijack to an address on an *allowed* domain therefore passes; closing that gap needs the trusted task (ClawGuard derives its rules from it before the session).

State is kept per session and dropped on `session.ended` (at most `MAX_SESSIONS` are kept). A session whose `session.started` was not seen, for example after a restart, is judged on the stateless rules only (no `precondition_missing`, no `unscanned_content`), so it cannot produce ordering false positives.

### Changing the policy

`policy.py` holds the built-in policy (docstring: rule list). `ALLOWED_RECIPIENT_DOMAINS` there matches the scenario generator's address book (`example.com`, `clinic.example.com`, `partner.example`, `vendor.example`, `company.example`); **replace it with your own domains**. To replace the whole policy without code changes, point `POLICY_FILE` at a JSON file with the same shape as `DEFAULT_POLICY` (`version`, `severity`, `agents.<id>.max_calls / requires_before / arguments / consistency`).

## Configuration

| Variable | Default |
|---|---|
| `KAFKA_BOOTSTRAP` | `localhost:29092` |
| `KAFKA_GROUP_ID` | `allow-list-consumer` |
| `TOPICS` | `tool-calls.A,tool-calls.B` |
| `TOOLSET_TOPIC` | `toolset-config` |
| `FLAGS_TOPIC` | `flags` |
| `POLICY_FILE` | unset (built-in policy) |
| `MAX_SESSIONS` | `10000` |
| `CONFIG_BOOTSTRAP_TIMEOUT_S` | `15` |

## Running locally

```bash
pip install -e .
PYTHONPATH=src python -m allow_list.publish_toolset_config         # publish the current toolsets
PYTHONPATH=src python -m allow_list.consumer                       # run the check
```

Revoke a tool and watch later calls get flagged:

```bash
PYTHONPATH=src python -m allow_list.publish_toolset_config --agent B --tools find_contact,tone_checker,sensitive_content_scan
```

The tool calls come from the mock agents (`docker compose --profile mocks up`) or the real agents.

## Testing

```bash
PYTHONPATH=src pytest
```

`tests/test_contract_mocks.py` replays `tests/fixtures/scenarios.jsonl`, exported from the scenario generator (`services/mocks`), through the real message path. It checks that no normal session is flagged, every attack is flagged, Agent B's flags equal the generator's `violated_rules` (except the one documented task-derived gap) and never contain a rule the label lacks. Regenerate the fixture whenever the generator changes (seed `20261115`, `--today 2026-11-15`, 60 normal and 8 of each attack per agent).

The Kafka loop is tested with fake consumers and producers; no broker is needed for the tests.

## Docker

```bash
docker build -t atgm-allow-list .
docker run --rm \
  --network <kafka-network> \
  -e KAFKA_BOOTSTRAP=kafka:9092 \
  -e KAFKA_GROUP_ID=allow-list-consumer \
  atgm-allow-list
```
