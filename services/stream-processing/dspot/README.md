# DSPOT: alarm thresholds from extreme value theory

**Owner:** Áron · **Paper:** A. Siffer, P.-A. Fouque, A. Termier, C. Largouët, *Anomaly Detection in Streams with Extreme Value Theory*, KDD 2017.

Turns a stream of anomaly scores (e.g. Online Isolation Forest, Markov "surprise") into alarms with a chosen false-alarm probability `q`, without labels, and follows drift in the scores.

## In plain words

**The question.** A detector gives every tool call a suspicion score. When is a score "too high"? A fixed line does not work: every detector has its own scale, the scale drifts, and you cannot tell how many false alarms a line will cause.

**Choose the price, not the line.** You choose `q`, the share of *normal* scores allowed to raise an alarm (`q = 0.001`: about 1 false alarm per 1000 normal calls). DSPOT computes where the line must be. `q` means the same for every detector.

**All tails look alike.** Extreme value theory says that, for almost any data, the way the extremes fade out follows one family of curves (the Generalized Pareto Distribution) with two knobs: how far out and how heavy the tail is. Like engineers sizing a dam for the "100-year flood" from 20 years of data, DSPOT fits this curve to the top 2% of scores and extends it to the 1-in-1000 point, beyond anything it has often seen.

**Example.** From 3000 warm-up scores: the top 2% start at `t = 2.05` (about 60 peaks); the curve fitted to how far they stick out above `t`, extended 20 times rarer, gives the alarm line `z ≈ 3.1`.

**Learning as it runs.** A new score below `t` is only counted; a new peak refits the curve; a score above the line is an **alarm and is not learned**, so an attacker cannot push the line up (poisoning).

**Following drift (the "D").** Each score is compared with the average of the last 20 normal scores, like judging a voice against the background noise of a library or a café. The line rises and falls with the normal level.

**Reviewer feedback.** Alarms a reviewer confirms as false alarms are learned (only those), which brings the false-alarm rate back to `q`. Wrong verdicts are dangerous: an attack labelled "false alarm" teaches DSPOT that very high scores are normal.

```
score - recent average -> top 2% (peaks) -> fit tail curve -> extend to q -> alarm line
                                     new score above the line -> ALARM -> reviewer
```

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
topic scores ──► dspot ──► topic alerts
topic labels ───┘          (session reviewed as normal → its alarms are learned; "attack" → nothing learned)
```

Messages use Agent A's event envelope (`schema_version "1.0"`, body in `data`). The `data` per event type:

| event_type | topic | data |
|---|---|---|
| `anomaly.scored` (read) | `scores` | `scored_event_id, agent_id, detector, model_version, score` (higher = more suspicious) |
| `alarm.raised` (written) | `alerts` | the fields above + `threshold, q` |
| `review.labelled` (read) | `labels` | `verdict: "false_alarm" \| "attack"`, matched by the envelope's `session_id` |

The `anomaly.scored` format is a proposal to the detector owners; only `adapters/events.py` changes if it does.

Behaviour:
- **Warm-up:** the first `DSPOT_WARMUP` scores of each stream (default 3000) calibrate it and raise no alarms. They must be normal: start each experiment with normal scenarios only.
- **Who reviews what:** DSPOT does **not** send its alarms to the review queue. ACI decides which sessions a human sees (at most one item per session, with a bounded review share), so an attacker cannot flood the reviewers with alarms.
- **Learning from verdicts, per session:** alarms are remembered per session. If the reviewer judges a session **normal**, every call in it was normal, so all of that session's alarms are learned. If it was an **attack**, we don't know which call was bad, so nothing is learned. Errors can therefore only make DSPOT more cautious, never less. Alarms of sessions that are never reviewed are simply not learned.
- **Late verdicts:** an alarm remembers the moving average at alarm time, so a verdict that arrives later is learned correctly. Unanswered alarms of the last 10,000 sessions are remembered.
- **Bad messages** are logged and skipped. **State** is in memory: after a restart every stream warms up again.

Run it with the platform (from the repository root), then try the demo:

```bash
docker compose up -d --build              # includes the dspot service
docker compose up kafka-init              # only if your stack existed before the scores topic was added
docker compose logs -f dspot

pip install -e ".[kafka]"                 # in services/stream-processing/dspot
python -m dspot.demo                      # DSPOT alone: sends demo scores, then answers each alarm as a simulated reviewer
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
