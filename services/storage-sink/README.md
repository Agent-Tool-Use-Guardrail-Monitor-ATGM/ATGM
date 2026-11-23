# Storage sink: Kafka → PostgreSQL

**Owner:** Áron (platform)

Copies every event from the ATGM topics into `analytics_db`, so that **Grafana dashboards** and the **batch jobs** (B1–B4) can query them with SQL. Grafana's read-only user `grafana_ro` can read these tables but not change them.

| Table | Contents | From topic(s) |
|---|---|---|
| `agent_events` | tool calls and session start/end, one row per event | `tool-calls.A`, `tool-calls.B` |
| `scores` | anomaly scores of every detector | `scores` |
| `alarms` | DSPOT alarms with score, threshold and `q` | `alerts` |
| `labels` | reviewer verdicts (`attack` / `false_alarm`, violation type) | `labels` |
| `other_events` | everything else as raw JSON (ACI decisions, rule violations, drift, counts, toolset changes) | `flags`, `drift`, `stats`, `toolset-config` |

Every table has `event_id` (primary key), `occurred_at`, `session_id` and `run_id`, plus the typed columns of its event. `agent_events.arguments` and the `data` columns are JSONB, e.g. `arguments->>'dataset_id'`.

Tool calls are understood in both styles: the mocks and Online Isolation Forest fields (`tool_name`, `duration_ms`) and Agent A's own (`name`, `latency_ms`).

## Reliability

- Events are written in batches (up to 500 or 1 second) in one transaction.
- Kafka offsets are committed **after** the database commit: after a crash, the last batch is read again.
- Inserts use `ON CONFLICT (event_id) DO NOTHING`, so a message delivered twice is stored once.
- Messages that are not in the event envelope are logged and skipped.

## Example queries for Grafana

```sql
-- alarms per minute and detector
SELECT date_trunc('minute', occurred_at) AS time, detector, count(*) FROM alarms
WHERE $__timeFilter(occurred_at) GROUP BY 1, 2 ORDER BY 1;

-- tool calls per agent and tool
SELECT agent_id, tool_name, count(*) FROM agent_events
WHERE event_type LIKE 'tool_call.%' GROUP BY 1, 2;

-- reviewer verdicts by violation type
SELECT verdict, coalesce(violation_type, '-') AS type, count(*) FROM labels GROUP BY 1, 2;
```

## Tests

```bash
cd services/storage-sink
pip install -e ".[test]"
pytest                                   # the PostgreSQL test is skipped unless ATGM_TEST_PG is set
ATGM_TEST_PG="host=localhost dbname=analytics_db user=analytics_svc password=..." pytest
```
