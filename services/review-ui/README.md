# Review UI

**Owner:** Áron · A web page where a human reviews the sessions that ACI (S10) sends to review, and labels them as attack or normal. The verdicts go to the `labels` topic, exactly like the simulated reviewer's, so every learning component (DSPOT, ACI, S01, S05, B1–B4) uses them unchanged.

Open **http://localhost:8501** (published on `127.0.0.1` only; on Azure through the SSH tunnel).

## Who reviews what

| Session | Reviewed by |
|---|---|
| has scenario ground truth (mock agents, generated scenarios) | the **simulated reviewer** (`services/review-queue`), automatically after 10 s |
| real agents (Agent B live, Agent A or its replay) | a **human**, on this page |

The page hides the sessions the simulated reviewer answers (a sidebar checkbox shows them too), so no session is judged twice. A session is listed until it has a verdict in `analytics_db.labels`.

## What the page shows

- **Queue:** ACI's `decision.made` events with decision *review*, or picked as a random *audit* (any decision), that have no verdict yet. Newest first; filter by agent.
- **Session:** ACI's decision, the session score and the two thresholds; the tool calls; each detector's scores; rule flags (S07) and DSPOT alarms.
- **Verdict:** *Attack* (with a violation type: B2's classes `unauthorized_tool`, `unsafe_args`, `skipped_check`, `out_of_order`, or `other`) or *Normal (false alarm)*. Stored with `reviewer = "human:<your name>"`.

```
analytics_db (read-only) ──► review UI ──► topic labels ──► DSPOT, ACI, S01, S05, storage sink ──► B1–B4 retraining
```

## Run and test

It runs with the platform (`docker compose up -d`). Configuration: `KAFKA_BOOTSTRAP`, `LABELS_TOPIC` (`labels`), `DB_HOST`, `DB_PORT`, `DB_PASSWORD`, `ANALYTICS_DB`/`ANALYTICS_USER`, `SCENARIO_DB`/`SCENARIO_USER`.

```bash
cd services/review-ui
pip install -e ".[app,test]"
pytest                                      # label format and queue logic (no database needed)
streamlit run src/review_ui/app.py          # against the running stack: DB_PASSWORD from .env
```
