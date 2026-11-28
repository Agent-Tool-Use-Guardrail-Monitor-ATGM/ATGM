# Agent B

Agent B, aka Email Emilio, is an email-drafting assistant (LangChain + a local Ollama model) with six tools:
- `find_contact`: looks up a contact's email, role and preferred tone,
- `get_current_datetime` and `get_free_slots`: today's date and the user's free meeting slots,
- `tone_checker`: checks whether the email matches the requested (or default) tone,
- `sensitive_content_scan`: scans the email for sensitive data, like passwords or JWT tokens,
- `save_draft`: saves the finished email as a draft.

### Storage

Contacts, free slots and saved drafts live in PostgreSQL (`agent_b_db`, tables `contacts`, `free_slots`, `drafts`).
The tables are created and filled on first use. Check the saved drafts with:

```bash
docker compose exec postgres psql -U agent_b_svc -d agent_b_db -c "SELECT id, recipient, subject FROM drafts;"
```

### Guardrail

Before `save_draft` saves anything, `domain/guardrail.py` checks the draft with deterministic rules and blocks it if:
- the recipient is not one of the contacts,
- the subject contains a line break (header injection, e.g. `Bcc:`),
- the scan finds high-severity sensitive data (credentials, card numbers, ...).

A blocked draft is not saved. The model gets the reason back as a tool error, and the call is published as
`tool_call.failed`. The guardrail covers only some rules on purpose: wrong dates, wrong call order or too many
calls get through, and the stream pipelines detect them.

The guardrail is on by default. Turn it off for dataset generation, so the recorded sessions keep their violations:

```bash
AGENT_B_GUARDRAIL=off PYTHONPATH=src uv run python src/agent_b/main.py --prompt scenario_01_500.jsonl
```

## Use in local environment

### Setup local environment

```bash
cd services/agent-b
uv sync
```

Download Ollama from its [website](https://ollama.com/download), then pull the model:

```bash
ollama pull qwen3:1.7b
```

The stack must be running (`docker compose up -d` in the repo root), because the tools use `agent_b_db`
and the events go to Kafka.

### Run in local environment

For the Python environment in the IDE choose `ATGM/services/agent-b/.venv/bin/python3`.

Run the agent interactively (from `services/agent-b`):

```bash
PYTHONPATH=src uv run python src/agent_b/main.py --model qwen3:1.7b
```

### Run tests in local environment

```bash
uv run pytest
```

The tests use an in-memory store (`tests/conftest.py`), so they need no database. The live test (a real prompt
to the model) is skipped by default. To include it, start Ollama and set `AGENT_B_LIVE=1`
(PowerShell: `$env:AGENT_B_LIVE = "1"`); it takes a few minutes and can fail on a bad model answer.
CI runs the other tests on every PR (`.github/workflows/agent-b.yml`).

### What the monitor receives

One event per tool call on `tool-calls.B` (Kafka default `127.0.0.1:29092`, set `KAFKA_BOOTSTRAP` to change it).
A call is `tool_call.failed` when the tool raised, returned an error, or answered with a known error text
("No contact found", "Invalid date"). A draft blocked by the guardrail is also `tool_call.failed`.
The two checking tools add their decision in `data.result`:
`sensitive_content_scan` → `{"status": "blocked" | "review" | "clear", "finding_types": [...]}`,
`tone_checker` → `{"matches_tone": ..., "score": ...}`. The result never contains the draft text.

## Project Integration

**Publishes to:** `tool-calls.B`

Event format: see the agent event schema (Teams chat).

Layout (ports & adapters):

```
domain/     agent logic, tools and guardrail
adapters/   Kafka publisher, agent_b_db store, fake data
main.py     wires domain + adapters, reads config from environment variables
```

**Owners:** Fanni, Ági

## Learning materials:
- https://github.com/shaiqbhatti85/langchain-ollama-tool-agent
- https://medium.com/data-science/building-a-simple-agent-with-tools-and-toolkits-in-langchain-77e0f9bd1fa5
- https://www.scribd.com/document/893740609/Guide-How-to-Build-an-Agent
- https://www.langchain.com/blog/tool-calling-with-langchain

## Replay into the pipeline

Ground truth to `scenario_db.ground_truth` (category = actual behaviour from the labels file),
then the events to `tool-calls.B` at a configurable rate. Same message schema as the live agent.

```bash
docker compose down -v && docker compose up -d        # clean run (local data only)
docker compose exec postgres bash /docker-entrypoint-initdb.d/init.sh   # if init.sh failed (macOS)
docker compose restart storage-sink review-queue grafana
docker compose --profile batch run --rm b1-train
# wait until every group on tool-calls.B has a consumer (services start at the latest offset):
docker compose exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups | grep tool-calls.B
cd services/agent-b
PYTHONPATH=src uv run python src/agent_b/load_ground_truth.py scenario_01_500.jsonl
PYTHONPATH=src uv run python src/agent_b/event_publisher.py events_for_scenario_01_500.jsonl --delay 0.02
PYTHONPATH=src uv run python src/agent_b/evaluate_replay.py scenario_01_500.jsonl
```

### Results (scenario_01_500, 20 Nov 2026)

3969 events, 500 sessions (459 violating, 41 compliant), all stored in `analytics_db`.

| Detector | Sessions | AUC (session max score) | Note |
|---|---|---|---|
| `b1_classifier` | 500 | 1.000 | in-sample (model refit on all 500); held-out macro F1 0.922, CV 0.919 |
| `online_forest` | 488 | 0.239 | ranks compliant sessions higher (1 − AUC = 0.761) |

- Reviewer verdicts: 350 sessions reviewed, 350 agree with the labels.
- DSPOT alarms: 0. `online_forest` sent 2969 scores, below the 3000 warm-up.
- `topk_counts`: no scores, as S03 counts alarms and flags and there were none.
- The forest assumes violations are rare. Here 92% of sessions are violating (the agent invents
  recipients), so the 41 compliant sessions are the rare ones. Compliant sessions also have long
  gaps between calls (12 s vs 2.3 s), which the forest finds unusual.
- 12 sessions have no tool calls, so the forest has no score for them.