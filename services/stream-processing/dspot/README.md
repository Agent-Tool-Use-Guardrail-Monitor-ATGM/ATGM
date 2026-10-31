# DSPOT: alarm thresholds from extreme value theory

**Owner:** Áron · **Paper:** A. Siffer, P.-A. Fouque, A. Termier, C. Largouët, *Anomaly Detection in Streams with Extreme Value Theory*, KDD 2017.

Turns a stream of anomaly scores (e.g. Online Isolation Forest, Markov "surprise") into alarms with a chosen false-alarm probability `q`, without labels, and follows drift in the scores.

## Status

- [x] GPD fit with Grimshaw's method (`domain/gpd.py`)
- [x] Streaming SPOT threshold updates (`domain/spot.py`)
- [x] Learning reviewer-confirmed false alarms (`SPOT.confirm_normal`)
- [x] Drift-following DSPOT variant (`domain/dspot.py`)
- [x] Offline evaluation runner (`evaluate.py`)
- [x] Kafka service (`service.py`, `adapters/`, `main.py`) + demo (`demo.py`)

## How it works

Scores above a high level `t` ("peaks") are modelled by a Generalized Pareto Distribution with shape γ and scale σ. `fit_gpd` finds the maximum-likelihood γ, σ with Grimshaw's reduction: it finds the roots of a one-dimensional function, implemented with NumPy only. `tail_quantile` then extrapolates to the alarm threshold `z_q` that normal scores exceed with probability `q`.

`SPOT` calibrates `t`, the GPD and `z_q` on an initial batch, then classifies each new score as an alarm (not learned), a peak (learned, threshold refitted) or normal. Measured on synthetic streams, it raises about 2-3x the requested false-alarm rate. The reason: excluded alarms hide the scores that would correct an early underestimate of the tail (see the docstring in `spot.py`).

`confirm_normal(score)` fixes this safely: when a reviewer (the ATGM review queue) marks an alarm as a false alarm, the score is learned like a normal one. Unreviewed alarms and confirmed attacks are never learned, so attackers cannot push the threshold up. With this feedback the measured false-alarm rate is 0.75-1.25x `q`.

`DSPOT` follows drift: it keeps the mean of the last `depth` normal scores and runs SPOT on each score's deviation from that mean, so the threshold moves with a slowly shifting normal level. Alarms do not enter the window. In the tests the level climbs by 15 standard deviations. Plain SPOT then flags over 90% of the late scores, while DSPOT stays at 1.8-2.7x `q` (0.7-1.1x `q` with review feedback). Decisions report the threshold in raw score units.

## Evaluate on a score stream

```bash
python -m dspot.evaluate --plot eval.png                    # synthetic drifting stream with 30 attacks
python -m dspot.evaluate --method spot --plot spot.png      # same stream, plain SPOT for comparison
python -m dspot.evaluate --csv scores.csv --column score --labels label --review --plot eval.png
```

The first `--init` scores (default 3000) calibrate the detector. With labels (1 = attack, 0 = normal) it prints precision, recall and the false-alarm rate on normal scores. `--review` simulates the review queue by confirming every false alarm. On the synthetic stream, DSPOT catches all 30 attacks with a 0.24% false-alarm rate. Plain SPOT flags 44% of the scores, because it cannot follow the drift.

## Kafka service

The service keeps one DSPOT per (agent, detector) score stream and runs this loop:

```
topic scores ──► dspot ──► topics alerts + review-queue
topic labels ───┘          (reviewer verdict "false_alarm" → learned; "attack" → never learned)
```

Messages use Agent A's event envelope (`schema_version "1.0"`, body in `data`). The `data` per event type:

| event_type | topic | data |
|---|---|---|
| `anomaly.scored` (read) | `scores` | `scored_event_id, agent_id, detector, model_version, score` (higher = more suspicious) |
| `alarm.raised` (written) | `alerts`, `review-queue` | the fields above + `threshold, q` |
| `review.labelled` (read) | `labels` | `scored_event_id, detector, verdict: "false_alarm" \| "attack"` |

The `anomaly.scored` format is a proposal to the detector owners; only `adapters/events.py` changes if it does.

Behaviour:
- **Warm-up:** the first `DSPOT_WARMUP` scores of each stream (default 3000) calibrate it and raise no alarms. They must be normal: start each experiment with normal scenarios only.
- **Late verdicts:** an alarm remembers the moving average at alarm time, so a verdict that arrives later is learned correctly. The last 10,000 unanswered alarms are remembered.
- **Bad messages** are logged and skipped. **State** is in memory: after a restart every stream warms up again.

Run it with the platform (from the repository root), then try the demo:

```bash
docker compose up -d --build              # includes the dspot service
docker compose up kafka-init              # only if your stack existed before the scores topic was added
docker compose logs -f dspot

pip install -e ".[kafka]"                 # in services/stream-processing/dspot
python -m dspot.demo                      # sends demo scores, then answers alarms as a simulated reviewer
```

## Run the tests

```bash
cd services/stream-processing/dspot
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -e ".[test]"         # includes matplotlib for the plot test
pytest
```

SciPy is used in the tests only, as an independent reference for the maximum-likelihood fit.
