# Visualization (Grafana dashboards)

**Owner of the setup:** Áron · **Owners of the dashboards:** each algorithm's owner.

Grafana shows what the pipeline stores in `analytics_db` (the storage sink copies every Kafka topic there). Open http://localhost:3000 (login `admin` / `GRAFANA_ADMIN_PASSWORD` from `.env`) and go to *Dashboards → ATGM dashboards*.

```
services/visualization/dashboards/   what Grafana shows (this folder)
  overview.json                        whole pipeline: tool calls, scores, alarms, ACI decisions
  stream/sNN-name.json                 one dashboard per stream stage (S01-S10)
  batch/bN-name.json                   one dashboard per batch job (B1-B4)
infra/grafana/provisioning/          how Grafana starts: data source + "load the dashboards folder"
```

`overview` and `stream/s09-dspot` have real panels; the others are placeholders for their owners.

## Edit your dashboard

1. Start the stack (`docker compose up -d`, with `--profile mocks` if no agent is running) and open your dashboard.
2. *Edit → Add visualization*, data source **ATGM (PostgreSQL)**, write the SQL (*Code* mode). Use `$__timeFilter(occurred_at)` so the time picker works, e.g.

   ```sql
   SELECT $__timeGroupAlias(occurred_at, '1m'), agent_id AS metric, count(*) AS value
   FROM scores WHERE detector = 'online_forest' AND $__timeFilter(occurred_at)
   GROUP BY 1, 2 ORDER BY 1
   ```
3. Save in Grafana, then *Share → Export → Save to file* and replace your JSON file in this folder. Keep its `uid`. Commit the JSON (Grafana reloads the folder every 30 s; changes made only in the UI are lost when the container is recreated).

## Tables

| Table | Rows |
|---|---|
| `agent_events` | tool calls and session start/end (`agent_id`, `tool_name`, `success`, `duration_ms`, `arguments` JSON) |
| `scores` | `anomaly.scored` events (`detector`, `score`, `scored_event_id`) |
| `alarms` | DSPOT alarms (`score`, `threshold`, `q`) |
| `labels` | reviewer verdicts (`verdict`, `violation_type`) |
| `other_events` | everything else as JSON: `decision.made` (ACI), `violation.flagged`, `drift.detected`, `counts.summary`, model updates (`event_type`, `data`) |

Grafana reads with the read-only role `grafana_ro`.
