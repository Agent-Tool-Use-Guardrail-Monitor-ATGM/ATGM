# Agent A adapter

**Owner:** Áron (platform) · Translates Agent A's telemetry into the ATGM tool-call format, so every detector works on Agent A without changes.

```
DataLens (Agent A) ──► agent.events.v1 ──► agent-a-adapter ──► tool-calls.A ──► detectors, ACI, storage sink
```

DataLens (`datalens-agent`, see its `docs/kafka-telemetry.md`) publishes **privacy-preserving** telemetry: no raw tool arguments, and the tool name only on the request event. The detectors expect one event per finished tool call with its name and features. The adapter:

| DataLens event | Becomes on `tool-calls.A` |
|---|---|
| `tool_call.requested` | nothing; remembered until its result arrives |
| `tool_call.completed` / `tool_call.failed` | one tool call, joined with its request by `tool_call_id`: `tool_name`, `arguments` (DataLens' categorical features: argument shape, column count, …), `duration_ms` (request → result), `success`, `status`, `reason`, `policy_evaluation`, `session_call_index`, `time_since_previous_call_ms` |
| `session.started`, `session.ended` (+ `call_count`), `model_call.*` | passed through |

Every output event has `data.agent_id = "A"` and `data.source_event_id`, and uses the ATGM envelope (`schema_version "1.0"`).

## Reliability

- **Transactions:** DataLens writes transactionally, so the adapter reads with `isolation.level=read_committed` and never sees aborted records.
- **At least once:** DataLens may redeliver events. The adapter drops repeated `event_id`s and derives its output ids from the source ids, so a replay produces identical events, which the storage sink stores once.
- **Offsets** are committed only after a batch has been published.

## Run and test

It runs with the platform (`docker compose up -d`) and does nothing until DataLens publishes. When the real Agent A runs, switch off the mock Agent A with `MOCK_AGENTS: "B"` on the `mock-agents` service.

```bash
cd services/agent-a-adapter
pip install -e ".[test]"
pytest
```
