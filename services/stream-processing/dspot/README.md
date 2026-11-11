# DSPOT: alarm thresholds from extreme value theory

**Owner:** Áron · **Paper:** A. Siffer, P.-A. Fouque, A. Termier, C. Largouët, *Anomaly Detection in Streams with Extreme Value Theory*, KDD 2017.

Turns a stream of anomaly scores (e.g. Online Isolation Forest, Markov "surprise") into alarms with a chosen false-alarm probability `q`, without labels, and follows drift in the scores.

## DSPOT explained

### 1. The question

A detector watches the agents and gives every tool call a **suspicion score**: higher means weirder.

```
0.31  0.28  0.35  0.30  0.27  0.33  0.81  0.29  0.32 ...
```

We want to raise an alarm when a score is "too high". But **what counts as too high?** That's the whole question DSPOT answers.

### 2. Why the obvious answers fail

**Idea 1: "pick a number, say 0.6".**
- Detectors have different scales: one gives scores around 0.3, another around 2, another around 50. One number can't fit all of them.
- Even for one detector, how many false alarms will 0.6 cause? You don't know until it's too late.

**Idea 2: "take the highest 0.1% of past scores".** To know where the top 0.1% begins, you need to have seen *many* extremes. With 1000 scores you've seen exactly **one** score in the top 0.1%, so the line is basically a guess based on one example.

So we need a way to find the line **from few extremes**, for **any** detector.

### 3. Turning it around: choose the price, not the line

DSPOT flips the question. You don't choose the line; you choose **how many false alarms you'll accept**:

> "Among normal tool calls, at most **1 in 1000** may trigger an alarm."

That number is called `q` (here 0.001). DSPOT then **computes** where the line must be. That's useful because `q` means the same thing for every detector: *"about 10 false alarms per 10,000 normal calls."*

### 4. The key insight: all tails look alike

Think about the **heights of people**. Most are between 160 and 185 cm, and nobody cares about the middle. Now look only at people **taller than 190 cm**. How quickly do they become rarer as you go to 195, 200, 205? That "fading out" has a typical shape.

The surprising mathematical fact (**extreme value theory**) is that for almost **any** kind of data (heights, floods, earthquakes, our anomaly scores), the way the extremes fade out follows **the same family of curves**. It's called the **Generalized Pareto Distribution**, and it has just two knobs:
- **how far out** the extremes go (the scale, σ)
- **how heavy** the tail is: do extremes stop at some point, fade out steadily, or occasionally get huge (the shape, γ)

That's the magic: we don't need to know the whole distribution, only these **two knobs of the tail**.

**An analogy:** engineers build dams for the "100-year flood" without having watched the river for 100 years. They measure the big floods of the last 20 years, fit this curve, and **extend it** to find how high a once-in-100-years flood would be. DSPOT does the same, for "once in 1000 normal calls".

### 5. Step by step, with numbers

Say the detector's first 3000 scores are normal (the **warm-up**).

1. **Draw a "high but common" line.** Take the score that only the top 2% exceed: say **t = 2.05**. About 60 scores out of 3000 lie above it. These are the **peaks**, and we look only at them from now on.
2. **Fit the curve to the peaks.** DSPOT looks at *how far* each peak sticks out above 2.05 (0.1, 0.3, 0.05, 0.8, …) and finds the two knobs that best explain that pattern (`domain/gpd.py`, `fit_gpd`).
3. **Extend the curve to 1 in 1000.** The peaks are the top **2%**; we want the top **0.1%**, which is 20 times rarer than "being a peak". The fitted curve says how far out you must go for that (`tail_quantile`). The answer is **z ≈ 3.1**: the alarm line.

The 60 peaks were enough to place a line that's **rarer than anything common in the data**. That's the extrapolation from step 4.

### 6. Learning while it runs ("streaming")

After the warm-up, every new score is one of three kinds (`domain/spot.py`, `SPOT.update`):

| New score | What DSPOT does |
|---|---|
| below 2.05 (most scores) | just counts it |
| between 2.05 and 3.1 (a new peak) | adds it to the peaks and **refits the curve**, so the line moves a little |
| above 3.1 | **ALARM**, and it does **not** learn from it |

Why not learn from alarms? Otherwise an attacker could send many slightly-too-high calls, the curve would learn "high is normal", the line would creep up, and real attacks would hide below it. Ignoring alarms makes DSPOT **resistant to this "poisoning"**.

### 7. The "D": following drift

Agents change: busier days, a new tool, longer prompts. All scores might slowly rise from about 1 to about 5. A fixed line at 3.1 would then flag **almost everything**.

DSPOT's fix (`domain/dspot.py`): instead of the raw score, it looks at **how far a score is above the recent normal level** (the average of the last 20 normal scores):

```
raw score 5.4, recent average 4.8   →   it looks at 0.6
```

**An analogy:** in a quiet library, talking at normal volume is "loud". In a busy café, the same voice is unremarkable. DSPOT judges every score against the **current background noise**, so the alarm line rises and falls with it. That's the red line climbing in the evaluation plot.

### 8. Learning from the reviewer

Alarms go to the `alerts` topic. **ACI decides which sessions a human reviews** (at most one item per session), so an attacker can't flood the reviewers with alarms. When a reviewer judges a session:

- **"Normal" (false alarm):** every call in it was normal, so DSPOT learns all of that session's alarms after all ("these can be normal"), and the line becomes a bit more relaxed.
- **"Attack":** some call was bad, but we don't know which, so **nothing is learned**.

This matters because ignoring all alarms (step 6) makes DSPOT a bit too nervous: about 2–3 false alarms per 1000 instead of 1. Learning only **confirmed** false alarms brings it back to about 1 in 1000, **without** reopening the poisoning door.

**A warning from our experiments:** if the reviewer makes mistakes and calls real attacks "false alarms", DSPOT learns very high scores as normal, the line jumps up, and it starts missing attacks. With 10% wrong verdicts, it caught 367 of 498 attacks instead of all 498.

### 9. The whole thing in one picture

```
scores ──► compare with recent average (drift)
               │
               ▼
      look only at the top 2% (peaks)
               │
               ▼
      fit the "tail curve" (2 knobs)
               │
               ▼
      extend it to 1-in-1000  ──►  alarm line
               │
      new score above line? ──► ALARM ──► alerts
                                            ┊ (ACI sends some sessions to a reviewer)
                     reviewer: session "normal" → learn its alarms
                               session "attack" → learn nothing

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
