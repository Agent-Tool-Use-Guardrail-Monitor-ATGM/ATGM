# Batch processing (placeholders)

Batch jobs train models on the **stored** data instead of the live stream. They run on a schedule or by hand (e.g. `docker compose run --rm <job>`), read PostgreSQL, and write a trained model plus its metrics.

| Folder | Task | Owner | Used by |
|---|---|---|---|
| `b1-binary-classifier/` | B1: classify a session as compliant vs. violating | Fanni | flags sessions; baseline for the report |
| `b2-violation-type-classifier/` | B2: classify the violation type | Asmar | explains *why* a session was flagged |
| `b3-markov-chain/` | B3: per-agent Markov chain of the normal tool order | Agnes | the Markov order check (stream stage P3) |
| `b4-retraining-and-model-registry/` | B4: periodic retraining on reviewed labels, champion/challenger, model registry | Maxim | all of the above |

## Where the data is

The storage sink copies every Kafka event into **`analytics_db`** (user `analytics_svc`, password `SERVICE_DB_PASSWORD` from `.env`; from your PC: `localhost:5432`, from a container: `postgres:5432`). See `services/storage-sink/README.md` for all tables.

| Table | What you need it for |
|---|---|
| `agent_events` | the tool calls: `session_id`, `agent_id`, `tool_name`, `sequence`, `duration_ms`, `success`, `arguments` (JSON) |
| `labels` | reviewer verdicts per session: `verdict` (`attack` / `false_alarm`), `violation_type` |

One training row per **session** (tool sequence plus label):

```sql
WITH session_label AS (
    SELECT DISTINCT ON (session_id) session_id, verdict, violation_type
    FROM labels ORDER BY session_id, occurred_at DESC)
SELECT e.session_id, e.agent_id,
       array_agg(e.tool_name ORDER BY e.sequence)                      AS tools,
       count(*)                                                        AS n_calls,
       avg(e.duration_ms)                                              AS mean_duration_ms,
       bool_and(e.success)                                             AS all_succeeded,
       l.verdict = 'attack'                                            AS violating,
       l.violation_type
FROM agent_events e JOIN session_label l USING (session_id)
WHERE e.event_type LIKE 'tool_call.%'
GROUP BY e.session_id, e.agent_id, l.verdict, l.violation_type;
```

**Which labels to train on:**
- `labels` holds what a reviewer saw: ACI's random audits (unbiased) and its "review" decisions (only borderline sessions, so biased). That's realistic and what B4 should use.
- For experiments, the scenario ground truth labels **every** session: `scenario_db.ground_truth` (`scenario_id` = `session_id`, `category`, `attack_type`). Use it for test sets and to measure how good the reviewed labels are.

Until the real agents publish, the **mock agents** fill these tables: `docker compose --profile mocks up -d`, wait 10–15 minutes.

## Conventions (suggested)

- Same layout as the stream stages: `domain/` (features, training, evaluation; plain Python, testable), `adapters/` (database, model storage), `main.py`, `Dockerfile`, `tests/`.
- Use scikit-learn for B1/B2 (required by the topic description). Keep a held-out test set and report precision, recall and F1 per class.
- A trained model is announced on the **`model-updates`** topic (already exists, compacted, key = model name) so stream services can reload it. B4 defines the exact message; a minimal proposal:
  `{"event_type": "model.promoted", "data": {"model": "b1-binary", "version": "2026-11-20T10:00", "path": "...", "metrics": {...}}}`
- Store models where every container can read them (e.g. a shared Docker volume `models/`); B4 decides.
