# Stream processing: S01–S10

Every team member builds **two stream stages**. Each stage is its own folder and Docker service: it reads Kafka topics, runs its algorithm, and publishes its results to Kafka. The storage sink copies all results into `analytics_db` for dashboards and batch jobs.

| # | Folder | Algorithm | Owner | Publishes | Status |
|---|---|---|---|---|---|
| S01 | `s01-online-bls/` | Online-BLS classifier | Maxim | score → `scores` | to do |
| S02 | `s02-optwin/` | OPTWIN drift on classifier errors | Maxim | drift → `drift` | to do |
| S03 | `s03-sliding-top-k/` | sliding-window top-k violation counts | Fanni | counts → `stats`, `scores` | to do |
| S04 | `s04-online-forest/` | Online Isolation Forest | Fanni | score → `scores` | ✅ |
| S05 | `s05-spacesaving/` | SpaceSaving± frequent items | Asmar | counts → `stats` | to do |
| S06 | `s06-kswin/` | KSWIN change detection | Asmar | drift → `drift` | to do |
| S07 | `s07-allow-list-check/` | allow-list policy check | Agnes | violation → `flags` | to do |
| S08 | `s08-markov-order-check/` | Markov order check (or drift vs. attack) | Agnes | score → `scores` | to do |
| S09 | `s09-dspot/` | DSPOT alarm thresholds | Áron | alarm → `alerts` | ✅ |
| S10 | `s10-aci/` | ACI conformal triage | Áron | decision → `flags`, `review-queue` | ✅ |

## Input

Tool calls arrive on `tool-calls.A` and `tool-calls.B` (key = session id, so a session's calls stay in order). Until the real agents publish, start the mock agents: `docker compose --profile mocks up -d`. Each message uses the shared envelope:

```json
{"schema_version": "1.0", "event_id": "…", "event_type": "tool_call.completed",
 "occurred_at": "…", "run_id": "…", "session_id": "…", "sequence": 3, "request_id": null,
 "data": {"agent_id": "B", "tool_name": "tone_checker", "arguments": {…}, "duration_ms": 27,
          "success": true, "session_call_index": 2, "time_since_previous_call_ms": 1180}}
```

Other event types on these topics: `session.started`, `tool_call.failed`, `session.ended` (`data.call_count`).

## Output: four kinds of results

Every result uses the same envelope (copy `run_id` and `session_id` from the input event) with `data.agent_id` and `data.detector` (your stage's name), plus:

| Kind | `event_type` | Topic | Extra `data` fields | Example stages |
|---|---|---|---|---|
| **score** (higher = more suspicious) | `anomaly.scored` | `scores` | `scored_event_id`, `model_version`, `score` | S01, S04, S08 |
| **rule violation** | `violation.flagged` | `flags` | `flagged_event_id`, `rule`, `severity` | S07 |
| **drift** | `drift.detected` | `drift` | `monitored` (what changed), `details` | S02, S06 |
| **counts** | `counts.summary` | `stats` | `window_start`, `window_end`, `top: [{item, count}]` | S03, S05 |

Scores are picked up automatically by DSPOT (an alarm threshold per agent and detector) and can be used by ACI. Everything is stored by the storage sink: scores in `scores`, the rest in `other_events` (JSON).

## Layout of a stage (ports and adapters)

```
sNN-name/
  src/<package>/domain/     the algorithm; plain Python, no Kafka, so it can be tested and replayed
  src/<package>/main.py     Kafka loop: read, call the domain, publish
  tests/
  pyproject.toml
  Dockerfile
  README.md
```

Then add the stage to `docker-compose.yml` (copy the `online-forest` entry). `s04-online-forest/` (consumer, events, detector) and `s09-dspot/` are complete examples.
