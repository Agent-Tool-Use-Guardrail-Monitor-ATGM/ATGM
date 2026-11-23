# Allow-list policy check

## Overview

The allow-list component is a deterministic tool-call guard. It consumes the tool calls of Agent A (the statistics agent) and Agent B (the e-mail drafting agent), checks every call against the agent's **current toolset** and a static **per-agent policy** (call caps, ordering, argument values), and publishes one `violation.flagged` event per broken rule to the `flags` topic.

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
| `policy.py` | Severity per rule, the assembled `DEFAULT_POLICY` and the JSON loader |
| `policies/agent_a.py`, `policies/agent_b.py` | One policy per agent |
| `rules.py` | Argument checks used by the policies |
| `events.py` | The two tool-call message shapes (`ToolCall`), `toolset-config` parsing, `violation.flagged` builder |
| `config.py` | Environment variables |
| `publish_toolset_config.py` | Publishes toolsets for local runs (like `send_test_events.py` in the forest) |

## Kafka

### Input

| Topic | Content |
|---|---|
| `tool-calls.A`, `tool-calls.B` | Agent A's envelope: `session.started`, tool-call events, `session.ended`. Two shapes of tool-call event are understood, see below. The key should be the session id so a session stays ordered. |
| `toolset-config` | The current allowed tools per agent. Read from the beginning at start-up, then followed live; the newest message per agent wins. |

`toolset-config` message (one per agent, keyed by agent id; the body may also be inside `data`):

```json
{"agent_id": "B", "allowed_tools": ["find_contact", "get_current_datetime", "get_free_slots", "save_draft", "tone_checker", "sensitive_content_scan"]}
```

Agent A's toolset is the four numerical tools of `tools.zip` (`inspect_dataset`, `describe_columns`, `aggregate_statistics`, `correlate_columns`) **plus two control tools that the recorded traffic uses in 79 calls: `finalize_statistics` and `request_clarification`**. If `toolset-config` lists only the four, every call to the control tools is flagged `tool_not_allowed`.

A single message for several agents (`{"toolsets": {"A": [...], "B": [...]}}`) is accepted too. **This schema is an assumption; adjust `events.parse_toolset_update` if your config service publishes something else.** If no toolset is known for an agent yet, the tool allow-list is skipped for it (a warning is logged once); all other rules still run.

### Tool-call message shapes

| Shape | Events | Judged |
|---|---|---|
| **flat** (mock agents, Agent B) | one `tool_call.completed` / `tool_call.failed` per call with `data.tool_name`, `data.arguments`, `data.success` | when it arrives, on the raw arguments |
| **run-events** (the real Agent A, `agent-run-events-v2`) | `tool_call.requested` with `data.name` and `data.features` (`operation`, `method`, `missing_policy`, `column_count`, `dataset_selection`), then `tool_call.completed` / `tool_call.failed` with only `tool_call_id` and `status` | once, at the request (before the tool ran); the outcome only tells the detector whether the call succeeded |

The real agent never publishes the arguments, only their hash and these features. Every argument rule works on whichever of the two is present and is skipped when the value it looks at is absent. A request with no `name` (the runner could not resolve the tool; recorded as `unknown_tool`) is flagged `tool_not_allowed`.

Agent A events carry no `agent_id` in `data` in the run-events shape; the agent is taken from the topic suffix (`tool-calls.A`).

### Output

One event per call and broken rule, on `flags`, keyed by agent id:

```json
{
  "schema_version": "1.0", "event_id": "…", "event_type": "violation.flagged",
  "occurred_at": "…", "run_id": "…", "session_id": "…", "sequence": 6, "request_id": null,
  "data": {
    "flagged_event_id": "<event_id of the tool call>", "agent_id": "B", "tool_name": "save_draft",
    "detector": "allow_list", "policy_version": "allow-list-2",
    "rule": "recipient_not_allowed", "severity": "high",
    "detail": "domain 'mailcollector.example' is not an allowed recipient domain"
  }
}
```

`detail` never contains a secret: credentials are reported by type only.

## Rules

| Rule | Severity | Meaning |
|---|---|---|
| `tool_not_allowed` | high | Tool is not in the agent's current `toolset-config`, or the call has no resolvable tool name |
| `recipient_not_allowed` | high | `save_draft.to` is not exactly one address on an allowed domain (foreign domain, several addresses, `\nBcc:` injection) |
| `secret_in_args` | high | Credential, key, JWT or Luhn-valid card number in `save_draft.subject` / `body` |
| `unscanned_content` | high | Saved subject/body is not covered by the text `sensitive_content_scan` saw (content changed after the scan) |
| `dataset_id_not_allowed` | high | Agent A: `dataset_id` is not a plain identifier (letters, digits, `-`, `_`, at most 64): rejects `../`, absolute paths, URLs, wildcards, injected text |
| `header_injection` | high | Line break in `save_draft.subject` (it is written into the draft file's header) |
| `contact_name_not_allowed` | medium | `find_contact` name is a wildcard (`*`, `all`) or not a plain name |
| `max_calls_exceeded` | medium | More calls of a tool in one session than the policy allows (B: `save_draft` once, `get_free_slots` 5; A: `aggregate_statistics` 6, `correlate_columns` 4, `finalize_statistics` and `request_clarification` once) |
| `precondition_missing` | medium | Tool ran before the tools it requires (Agent B: `save_draft` needs `tone_checker` and `sensitive_content_scan`). Agent A has none, see below |
| `argument_too_large` | medium | Agent A: more than 50 columns (`columns` argument or `column_count` feature) |
| `argument_value_not_allowed` | medium | Agent A: `operation` not in `count, sum, mean, min, max`; `method` not in `pearson, spearman`; `missing_policy` not in `omit, error` (describe, aggregate) or `pairwise_complete, error` (correlate) |
| `dataset_not_selected` | medium | Agent A: a numerical tool called with `dataset_selection` other than `selected` |
| `date_invalid_format` | medium | `get_free_slots.date` is not a real `YYYY-MM-DD` date |
| `date_out_of_window` | low | Date is before the event day or more than 30 days after it |

### What the service can and cannot know

The service sees only tool-call events and `toolset-config`, not the user's prompt. So it enforces the **task-independent** form of each rule: "the recipient is on an allowed domain" instead of "the recipient is the contact the user named", "the name is a plain name" instead of "the name appears in the prompt". A hijack to an address on an *allowed* domain therefore passes; closing that gap needs the trusted task (ClawGuard derives its rules from it before the session).

State is kept per session and dropped on `session.ended` (at most `MAX_SESSIONS` are kept). A session whose `session.started` was not seen, for example after a restart, is judged on the stateless rules only (no `precondition_missing`, no `unscanned_content`), so it cannot produce ordering false positives.

### Agent A: what the recorded traffic taught

The Agent A policy (`policies/agent_a.py`) is built from the tool contracts and from 130 recorded sessions (73 normal, 57 with a direct prompt injection), not from assumptions:

* **No "inspect first" rule.** Most real sessions start with `aggregate_statistics`; only 39 of 130 call `inspect_dataset`. An earlier version of this policy required it and would have flagged 70 of the 130 sessions.
* **No "compute before finalize" rule.** `finalize_statistics` is also the designed answer to unsupported requests with nothing computed (one recorded baseline session, outcome `unsupported`).
* **Call caps have headroom.** At most 2 calls of the same tool per session were seen (aggregate, correlate); the caps catch loops, not normal use. `finalize_statistics` and `request_clarification` end a session, so their cap is 1. Tune these with more data.
* **Enumerations are inferred** from the tool code (`operation`, `method`, `missing_policy == "error"`) and from the recorded values; the contracts module itself was not available. If a tool gains a new operation or policy value, add it to `policies/agent_a.py`.

Replaying the recorded sessions (`tests/test_agent_a_real.py`): the only flags are the 16 sessions (13 normal, 3 injected) in which the model asked for a tool the runner could not name, which the runner already rejected as `unknown_tool`. Everything that stays inside the toolset, including all injected sessions, passes. **The recorded injection scenarios change the agent's answer, not which tools it calls, so this guard cannot tell them from normal sessions.** One session was denied by the agent's own policy for `invalid_arguments`; its published features were all inside the allow-list, so detecting such a call needs the arguments themselves in the event.

### Changing the policy

`policy.py` holds the severities and assembles the per-agent policies (its docstring lists every rule). `ALLOWED_RECIPIENT_DOMAINS` in `policies/agent_b.py` matches the scenario generator's address book (`example.com`, `clinic.example.com`, `partner.example`, `vendor.example`, `company.example`); **replace it with your own domains**. To replace the whole policy without code changes, point `POLICY_FILE` at a JSON file with the same shape as `DEFAULT_POLICY` (`version`, `severity`, `agents.<id>.max_calls / requires_before / arguments / consistency`).

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
PYTHONPATH=src python -m allow_list.publish_toolset_config --agent A --tools inspect_dataset,aggregate_statistics
```

The tool calls come from the mock agents (`docker compose --profile mocks up`) or the real agents.

## Testing

```bash
pytest
```

(`pyproject.toml` puts `src` on the path, so no `PYTHONPATH` or install is needed.)

* `tests/test_agent_a.py`: Agent A's tools, argument rules and caps, in both message shapes.
* `tests/test_agent_a_real.py` replays `tests/fixtures/agent_a_real.jsonl`, a trimmed copy of the recorded Agent A dataset (130 sessions, `agent-run-events-v2`), through the real message path. Rebuild it with `python tests/fixtures/build_agent_a_real.py path/to/dataset.jsonl`.
* `tests/test_contract_mocks.py` replays `tests/fixtures/scenarios.jsonl`, exported from the scenario generator (`services/mocks`), through the real message path. It checks that no normal session is flagged, every attack is flagged, Agent B's flags equal the generator's `violated_rules` (except the one documented task-derived gap) and never contain a rule the label lacks. Regenerate the fixture whenever the generator changes (seed `20261115`, `--today 2026-11-15`, 60 normal and 8 of each attack per agent). Two deliberate differences from the generator's labels: Agent B's `contact_harvesting` is only caught by `max_calls_exceeded` (see above), and the generator's Agent A `out_of_order` attack is **not** flagged, because "inspect first" is not a rule of the real agent. The mocks' Agent A should be brought in line with the real one (no inspect-first, `request_clarification`, UUID dataset ids, `x_column` / `y_column`, `missing_policy`).

The Kafka loop is tested with fake consumers and producers; no broker is needed for the tests.

## Docker

The image contains only this component (no other package is needed), so the build context is this folder. From the repository root:

```bash
docker build -t atgm-allow-list services/stream-processing/s07-allow-list-check
```

The image is `python:3.12-slim-bookworm` with `confluent-kafka`, `pytest`, this package and its tests (`CMD python -m allow_list.consumer`).

Run the container:

```bash
docker run --rm \
  --network atgm \
  -e KAFKA_BOOTSTRAP=kafka:9092 \
  -e KAFKA_GROUP_ID=allow-list-consumer \
  atgm-allow-list
```

`atgm` is the Compose network of this repository (`networks.default.name` in `docker-compose.yml`). Any variable from [Configuration](#configuration) can be passed with `-e`.

### Docker Compose

Add this service to `docker-compose.yml` next to the other detectors if it is not there yet (adjust the name and path to your layout):

```yaml
  allow-list:
    build: ./services/stream-processing/s07-allow-list-check
    environment:
      KAFKA_BOOTSTRAP: kafka:9092
      KAFKA_GROUP_ID: allow-list-consumer
    depends_on: [kafka]
    restart: unless-stopped
```

From the repository root (service `allow-list`):

```bash
docker compose up -d --build allow-list
docker compose logs -f allow-list
docker compose run --rm allow-list python -m pytest -q     # tests in the service image
```

After changing code or the policy: `docker compose build allow-list`.

### First run in Docker

1. **Start Kafka.** The topics `tool-calls.A`, `tool-calls.B`, `toolset-config` and `flags` must exist (Kafka UI at http://localhost:8080 lists them). If your broker does not create topics automatically, create them the way the other platform topics are created.

   ```bash
   docker compose up -d kafka kafka-init
   ```

2. **Publish the current toolsets** (once; Kafka keeps them). Without them the tool allow-list is skipped and a warning is logged, all other rules still run.

   ```bash
   docker compose run --rm allow-list python -m allow_list.publish_toolset_config
   ```

3. **Start the check.**

   ```bash
   docker compose up -d --build allow-list
   docker compose logs -f allow-list
   ```

   Expected log lines, in this order: `toolsets loaded for agents ['A', 'B']`, then `Allow-list consumer started: ['tool-calls.A', 'tool-calls.B'] + toolset-config -> flags (policy allow-list-2)`. The service reads `toolset-config` from the beginning at start-up and then follows it, so it can be started before or after step 2.

4. **Send tool calls.** Start the mock agents (`docker compose --profile mocks up -d`) or the real agents. The mocks send normal sessions only for the first 1000 sessions per agent (about 7 minutes at the default rate) and then 5% attacks; lower `WARMUP_SESSIONS` and raise `ATTACK_RATE` in `docker-compose.yml` to see flags sooner.

5. **Watch the flags** in Kafka UI (topic `flags`) or on the command line:

   ```bash
   docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
     --bootstrap-server localhost:9092 --topic flags --from-beginning
   ```

### Quick check that it works

With the mock agents running, take a tool away from Agent B. Every later call to it is flagged `tool_not_allowed` within a second, without a restart:

```bash
docker compose run --rm allow-list python -m allow_list.publish_toolset_config \
  --agent B --tools find_contact,tone_checker,sensitive_content_scan
```

Restore it by publishing the defaults again (step 2). The log shows `toolset update at offset N: [...]` for each change.

### Using your own policy in Docker

The built-in policy is replaced by a JSON file of the same shape. Export the defaults, edit them (for example `allowed_domains` in Agent B's `single_address` check), and mount the file:

```bash
docker compose run --rm allow-list python -c \
  "import json; from allow_list.policy import DEFAULT_POLICY as P; print(json.dumps(P, indent=2))" > policy.json
```

```yaml
  allow-list:
    # ... as above
    environment:
      POLICY_FILE: /app/policy.json
    volumes:
      - ./policy.json:/app/policy.json:ro
```

Change `version` in the file when you change the policy: it is copied into every flag (`policy_version`).

### Operating notes

- **Restarts.** State is in memory. After a restart, sessions that were running are judged on the stateless rules only (tool allow-list, argument rules); ordering and caps are not applied to them, so a restart cannot produce false alarms.
- **Delivery is at-least-once.** Offsets are committed after the flags are handed to the producer. After a crash the last few tool calls can be checked again and flagged a second time, with a new `event_id`. Consumers of `flags` should de-duplicate on `flagged_event_id` + `rule`.
- **First start.** The consumer group starts at the earliest offset, so the first run checks all retained tool calls. To check the whole history again, start with a new `KAFKA_GROUP_ID`.
- **Warnings in the log.** `no toolset-config for agent X yet` means no toolset was published for that agent; `topic toolset-config not found` means the topic does not exist yet (the service retries every 30 s).
- **Scaling.** One container is enough for the mocks. If you run several, make sure `tool-calls.*` messages are keyed by `session_id` (check your producers) so that a session always reaches the same instance; the per-session rules rely on it.
