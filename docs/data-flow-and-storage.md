# ATGM: how data flows and where it is stored

Short guide for the team: who writes what to Kafka, how it ends up in PostgreSQL, and how to query it (Grafana, batch jobs).

## 1. The idea in one picture

```
agents ──► Kafka topics ──► stream stages (S01–S10) ──► Kafka topics ──┐
   │                                                                   │
   └───────────────────────────────────────────────────────────────────┴──► storage sink ──► analytics_db ──► Grafana, batch jobs (B1–B4)
```

- **Nobody writes to the database directly.** Every service only publishes events to Kafka.
- **One service, the storage sink** (`services/storage-sink`), subscribes to all topics and copies every event into **`analytics_db`**. It picks the table by the event's `event_type`.
- So to get your algorithm's output into the database, you only need to publish it to a topic the sink reads (see section 3). No database code and no migrations on your side.

## 2. The event format (all topics)

Every message is one JSON object in the shared envelope:

```json
{"schema_version": "1.0", "event_id": "uuid", "event_type": "anomaly.scored",
 "occurred_at": "2026-11-26T10:00:00Z", "run_id": "…", "session_id": "…",
 "sequence": null, "request_id": null,
 "data": {"agent_id": "A", "detector": "online_forest", "score": 0.73, "…": "…"}}
```

`event_id` and `event_type` are required. Messages without them are logged and skipped by the sink.

## 3. Topics: who writes, who reads

| Topic | Event type(s) | Written by | Read by |
|---|---|---|---|
| `agent.events.v1` | DataLens telemetry | Agent A (DataLens publisher), replayer | agent-a-adapter |
| `tool-calls.A` | `session.*`, `tool_call.*`, `model_call.*` | agent-a-adapter (or mock Agent A) | S01, S03, S04, S05, S06, S07, S08, S10, sink |
| `tool-calls.B` | `session.*`, `tool_call.*` | Agent B (or mock) | same as above, plus B1 scorer |
| `scores` | `anomaly.scored` | S01, S03, S04, S08, B1 scorer | S06, S09 DSPOT, S10 ACI, sink |
| `alerts` | `alarm.raised` | S09 DSPOT | S03, sink |
| `flags` | `violation.flagged` (S07), `decision.made` (S10) | S07, S10 | S03, sink |
| `drift` | `drift.detected` | S02, S06 | sink |
| `stats` | `counts.summary` | S03, S05 | sink |
| `classifier-errors` | `classifier.error` | S01 | S02, sink |
| `review-queue` | `decision.made` (review or audit) | S10 ACI | review queue, sink |
| `labels` | `review.labelled` | review queue (simulated reviewer) | S01, S05, S09, S10, sink |
| `toolset-config` | current allowed tools per agent | scenario generator / S07 tool | S07, sink |
| `model-updates` | `model.trained` | B1, B2, B3, B4 | B1 scorer, S08, sink |

Every service reads with **its own consumer group** (`group.id`), so every service sees every message. Two processes with the same group id split the messages between them: never run your stage from the IDE with the same group id as its running container.

## 4. Where it lands: `analytics_db`

The sink creates these tables itself on start (`CREATE TABLE IF NOT EXISTS`, no migration tool).

| Table | Filled from event types | Typed columns (besides the common ones) |
|---|---|---|
| `agent_events` | `session.*`, `tool_call.*` | `topic, agent_id, event_type, sequence, tool_name, success, duration_ms, session_call_index, arguments` (JSONB), `data` (JSONB) |
| `scores` | `anomaly.scored` | `agent_id, detector, model_version, scored_event_id, score` |
| `alarms` | `alarm.raised` | `agent_id, detector, scored_event_id, score, threshold, q` |
| `labels` | `review.labelled` | `agent_id, detector, scored_event_id, verdict` (`attack` / `false_alarm`), `violation_type, reviewer` |
| `other_events` | **everything else**: `violation.flagged`, `decision.made`, `drift.detected`, `counts.summary`, `classifier.error`, `model.trained`, `model_call.*`, toolset changes | `topic, agent_id, event_type, data` (the whole `data` object as JSONB) |

Common columns in every table: `event_id` (primary key), `occurred_at`, `session_id`, `run_id`, `stored_at`.

**`other_events` is generic on purpose:** the formats of these events were still changing. Read their fields from the JSON, e.g. `data->>'decision'`, `(data->>'session_score')::float`. Dedicated typed tables (`flags`, `drift`, `counts`, `decisions`, `models`) are planned after the demo.

**Reliability:** the sink writes in batches (up to 500 messages or 1 second) in one transaction and commits the Kafka offsets only after the database commit. Inserts use `ON CONFLICT (event_id) DO NOTHING`, so a message delivered twice is stored once.

## 5. The other databases (same PostgreSQL server)

One server, one database and login per service (no shared tables):

| Database | Login | Used for |
|---|---|---|
| `analytics_db` | `analytics_svc` (write), `grafana_ro` (read only) | everything above |
| `scenario_db` | `scenario_svc` | ground truth of generated / mocked sessions (which session was an attack); read by the simulated reviewer |
| `agent_a_db`, `agent_b_db`, `monitor_db` | `<name>_svc` | reserved per service (Agent A's real database lives in its own repo) |

Passwords come from `.env` (`SERVICE_DB_PASSWORD`, `GRAFANA_DB_PASSWORD`); never commit them.

## 6. How to look at the data

From your PC (stack running): host `localhost`, port `5432`, database `analytics_db`, user `analytics_svc`, password from `.env`. From a container: host `postgres`.

Quick look without any client:

```
docker compose exec postgres psql -U atgm_admin -d analytics_db -c "SELECT event_type, count(*) FROM other_events GROUP BY 1;"
```

Example queries:

```sql
-- tool calls per agent and tool
SELECT agent_id, tool_name, count(*) FROM agent_events
WHERE event_type LIKE 'tool_call.%' GROUP BY 1, 2;

-- scores of one detector over time (Grafana)
SELECT $__timeGroupAlias(occurred_at, '1m'), agent_id AS metric, avg(score) AS value
FROM scores WHERE detector = 'online_forest' AND $__timeFilter(occurred_at) GROUP BY 1, 2 ORDER BY 1;

-- ACI decisions (generic table, JSON fields)
SELECT data->>'agent_id' AS agent, data->>'decision' AS decision, count(*)
FROM other_events WHERE event_type = 'decision.made' GROUP BY 1, 2;

-- drift detections per detector
SELECT data->>'detector' AS detector, count(*) FROM other_events
WHERE event_type = 'drift.detected' GROUP BY 1;
```

## 7. Grafana

http://localhost:3000 (user `admin`, password `GRAFANA_ADMIN_PASSWORD` from `.env`), data source **ATGM (PostgreSQL)**.

- Dashboards: `services/visualization/dashboards/` (one JSON per algorithm, `stream/` and `batch/` folders, plus `overview.json`).
- Grafana setup (data source, loading the dashboards folder): `infra/grafana/provisioning/`.
- Edit in the Grafana UI, then *Share → Export → Save to file* and replace your JSON in the repo (keep its `uid`). Details: `services/visualization/README.md`.

## 8. Checklist for a new output

1. Publish your event in the envelope (section 2) to the right topic (section 3).
2. If it is a new topic: add it to `infra/kafka/topics.txt` **and** to the storage sink's `DEFAULT_TOPICS` (`services/storage-sink/src/storage_sink/main.py`).
3. Check it arrived: `SELECT * FROM other_events WHERE event_type = '<your type>' ORDER BY occurred_at DESC LIMIT 5;` (or `scores` for `anomaly.scored`).
4. Add a panel to your dashboard.
