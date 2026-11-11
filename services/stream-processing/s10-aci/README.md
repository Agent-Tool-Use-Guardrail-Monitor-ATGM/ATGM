# ACI: conformal triage (flag / pass / review)

**Owner:** Áron · **Pipeline:** P6 (review and retraining) · **Paper:** A. N. Angelopoulos, R. F. Barber, S. Bates, *Online conformal prediction with decaying step sizes*, arXiv:2402.01139, 2024. It builds on I. Gibbs, E. Candès, *Adaptive Conformal Inference Under Distribution Shift*, NeurIPS 2021.

Decides for every agent session whether to **pass** it, **flag** it, or send it to **review**, with error rates you choose, and keeps those rates under drift.

## Status

- [x] Decaying-step online conformal threshold (`domain/tracker.py`)
- [x] Class-conditional triage per agent (`domain/triage.py`)
- [x] Kafka service: session scores in, decisions out, learning from audits (`service.py`, `main.py`)
- [x] Offline evaluation, decaying vs constant step size (`evaluate.py`)

## How it works

A session's suspicion `r` is the highest anomaly score of its tool calls (detectors in `DETECTORS`), clipped to `[0, B]`. Two online thresholds per agent form a prediction set over {compliant, violating}:

| Set | Condition | Decision |
|---|---|---|
| {compliant} | `r ≤ pass_up_to` only | **pass** |
| {violating} | `r ≥ flag_from` only | **flag** |
| both, or neither | in between | **review** |

Each threshold follows eq. 4 of the paper, `q ← q + η_t (err_t − α)`, with decaying steps `η_t = c · t^(−1/2−ε)` (default `c = B/10`, `ε = 0.1`):

- `pass_up_to` learns from **normal** sessions with `α_normal`: at most 5% of normal sessions are not passed (flagged or reviewed).
- `flag_from` learns from **attack** sessions with `α_attack`: at most 10% of attacks are not flagged (passed or reviewed).

These hold in the long run for any sequence of scores (paper, Theorem 1). For stable data, the thresholds converge to the true quantiles (Theorem 3), which a constant step size cannot do.

**Safe start:** both thresholds start at 0, so every session is reviewed at first. The review band narrows as labels arrive.

**Audits:** labels come from the review queue. ACI sends a random 10% of **all** sessions (`AUDIT_RATE`) to review as audits, and learns **only** from those. Learning from the review band alone would be biased, since those sessions were already uncertain. This is also the "sampled review" safeguard of the design.

## Results (synthetic, `python -m aci.evaluate`)

Normal score ~ Exp(1), attack ~ 4 + Exp(1), 10% attacks, 30% audited, measured after the first 6000 sessions:

| Step size | Normal not passed (target ≤ 5%) | Attack not flagged (target ≤ 10%) | Attacks passed | Review share | Threshold jitter |
|---|---|---|---|---|---|
| decaying | 5.2% | 8.8% | 0.0% | 4.0% | 0.13 |
| constant (ACI 2021) | 5.3% | 9.7% | 0.04% | 4.2% | 1.47 |

With drift (all scores rise by 2 during the second half, `--drift`):

![thresholds under drift](docs/aci_drift.png)

The decaying step is **ten times steadier** but **slower to follow drift**: under drift, 7.5% of normal sessions were not passed, against the 5% target. The constant step follows drift but jitters. The paper's Theorem 2 allows **resetting** the step size after a change, keeping the guarantee. Resetting when a drift detector (OPTWIN or KSWIN) fires is a natural extension.

## Kafka service

Reads `tool-calls.A`, `tool-calls.B`, `agent.events.v1` (session ends), `scores` and `labels`. After `session.ended` it waits `GRACE_SECONDS` for late scores, then publishes `decision.made` (Agent A's envelope) to `flags`. Review decisions and audits also go to `review-queue`.

```json
{"event_type": "decision.made", "session_id": "…",
 "data": {"scored_event_id": "<session.ended event id>", "agent_id": "B", "detector": "aci",
          "decision": "review", "prediction_set": [], "session_score": 4.7, "scores_seen": 3,
          "pass_up_to": 2.9, "flag_from": 5.1, "audit": false}}
```

Configuration is through environment variables: see `main.py`.

## Run the evaluation and tests

```bash
cd services/stream-processing/s10-aci
pip install -e ".[test]"
pytest
python -m aci.evaluate --drift --plot aci.png
```
