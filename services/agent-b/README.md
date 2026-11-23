# Agent B

Agent B, aka Email Emilio is an email-drafting assistant with the following tools:
- `tone_checker`, that checks whether the email's format adheres to the requested (or default) format, and 
- `sensitive_content_scan`, that scans the email's content for sensitive data, like passwords, or JWT tokens,
and alerts the user if any sensitive data was found.

## Use in local environment

### Setup local environment

```
.../ATGM/services/agent-b/src/agent_b$ uv sync
```

Download Ollama from its [website](https://ollama.com/download)

```
$ ollama pull qwen2.5:7b # or qwen2.5:1.5b, if there's not enough memory for qwen2.5:7b
--> then code should be adjusted in llm_client.py too
```

### Run in local environment

For python environment choose `ATGM/services/agent-b/.venv/bin/python3`.

Run the agent with:

```
.../ATGM/services/agent-b/src/agent_b$ python3 main.py
```

### Run tests in local environment

```
.../ATGM/services/agent-b/src/agent_b PYTHONPATH=src uv run pytest tests/ -v
```

Note: it might take a few minutes.


## Project Integration

**Publishes to:** `tool-calls.B`

Event format: see the agent event schema (Teams chat).

Suggested layout (ports & adapters):

```
domain/     agent logic and tools; no Kafka/DB imports
adapters/   Kafka publisher, LLM client, database
main.py     wires domain + adapters, reads config from environment variables
Dockerfile
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