# Review queue (with a simulated reviewer)

**Owner:** Áron · Pipeline P6 (review and retraining)

Uncertain or alarming tool calls are sent to the `review-queue` topic. In the experiments a **simulated reviewer** answers them, using the scenario ground truth that the scenario generator (or the mock agents) stored in `scenario_db.ground_truth`. The verdicts go to the `labels` topic, where:

- **DSPOT** learns from confirmed false alarms (attacks are never learned),
- the **batch jobs** (B1, B2, B4) get labelled training data,
- the dashboards show how the review queue is doing.

```
DSPOT (alarm.raised) ─┐
ACI (decision.made,   ├─► review-queue ─► review queue ─► labels ─► DSPOT, batch jobs, dashboards
     decision=review) ┘                       ▲
                                  scenario_db.ground_truth
```

## Behaviour

- Each item is answered after `REVIEW_DELAY_SECONDS` (default 10 s), like a human who needs some time.
- A **session** is judged once. If a session caused several alarms, all of them get the same verdict.
- `REVIEWER_ERROR_RATE` (default 0) makes the reviewer get a share of the sessions wrong, to test robustness to label noise.
- If the ground truth is not there yet, the item is retried 5 times, then dropped.

## Messages

Input: `alarm.raised`, or `decision.made` with `decision: "review"` or `audit: true` (ACI's random audits of pass/flag decisions). The envelope's `session_id` must be the session of the scored tool call.

Output, on `labels` (Agent A's envelope, `schema_version "1.0"`):

```json
{"event_type": "review.labelled", "session_id": "…",
 "data": {"scored_event_id": "…", "detector": "mock_scorer", "verdict": "attack",
          "violation_type": "unauthorized_tool", "agent_id": "B", "reviewer": "simulated"}}
```

`verdict` is `attack` or `false_alarm`. `violation_type` is the attack type for attacks, `null` for false alarms.

## Run and test

It runs with the platform (`docker compose up -d`). To see it work end to end, start the mocks too: `docker compose --profile mocks up -d --build`, then `docker compose logs -f review-queue`.

```bash
cd services/review-queue
pip install -e ".[test]"
pytest
```
