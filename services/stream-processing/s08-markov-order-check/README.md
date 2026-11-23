# S08: Markov order check

Pipeline: Real-time sequence-order check of each tool call against a learned, per-agent Markov model of normal tool order.

Vulnerability: agent goal hijack through prompt injection (direct, or hidden in tool-returned content), which makes the agent use legitimate tools in an order its normal workflow does not follow: jumping to an action, skipping a step, looping. [1] [2]

Mitigation: score every tool call against the model as it happens, flag improbable transitions as `out_of_order`, and publish a calibrated session score, so the deviation is visible before the session ends. It complements S07, which enforces explicit rules; S08 catches the deviations nobody wrote a rule for. [3] [4]

**Citations:**
- [1] [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), 2025
    - ASI01: Agent Goal Hijack
    - ASI02: Tool Misuse and Exploitation
- [2] Liu et al., [TraceAegis](https://arxiv.org/abs/2510.11203), 2025 (execution order disturbance)
- [3] Du et al., DeepLog: Anomaly Detection and Diagnosis from System Logs through Deep Learning, ACM CCS 2017
- [4] Sha et al., Statistical Learning for Anomaly Detection in Cloud Server Systems: A Multi-Order Markov Chain Framework, IEEE Trans. Cloud Computing 2018 (the B3 model)

Owner: Agnes

Specification: *Spec: Real-Time Markov Order Check for Tool-Call Streams* (S08), together with the B3 batch spec.

## Overview

The Markov order check is the serving side of the B3 Markov chain. B3 learns one model of normal tool order per agent offline and announces it on `model-updates`. This component reads those models and scores the live tool calls of Agent A and Agent B **one event at a time**. The model arithmetic is B3's own: S08 depends on the `b3-markov-chain` package (`services/batch-processing/b3-markov-chain`) and scores every transition with `b3_markov.domain.scoring.step` and every call's arguments with B3's `Featurizer.flags_for_call`, so batch and stream give the same numbers.

- **Call level:** every transition from the last K calls to the next call (and to the end of the session) is scored. A transition whose smoothed log-probability is below the calibrated `call_threshold` is published as an `out_of_order` alert (detector `markov_order`), while the session is still running.
- **Session level:** when a session closes, the B3 session score (sequence plus argument flags for Agent B, sequence only for Agent A) is published (detector `markov`).

It does **not** check the tool allow-list (S07 does, from `toolset-config`); unknown tools enter the model as `<UNK>`. It never updates the model from the stream.

## Architecture

```text
model-updates ──> model consumer (read from the beginning at start-up) ──┐
                                                                         v
tool-calls.A ─┐                                                   ModelRegistry (one model per agent)
tool-calls.B ─┴─> tool consumer ─> MarkovOrderPipeline ─> MarkovOrderDetector (per agent) ─> producer ─> scores
                                                  (session state, ordering, checks, session score)
```

| File | Role |
|---|---|
| `consumer.py` | Kafka glue: model bootstrap, main loop, produce, flush, then commit. The only module that imports Kafka |
| `detector.py` | `MarkovOrderPipeline` (routing per agent) and `MarkovOrderDetector` (per-session state, reordering, closing, checks, session score) |
| `models.py` | Per-agent model registry: parses and validates `model.trained`, version pinning happens per session |
| `scoring.py` | Thin adapter over `b3_markov`: rebuilds the model with `training.from_table`, scores with `scoring.step`, featurizes with `Featurizer.flags_for_call`; adds validation, thresholds and the running form of B3's session scores |
| `events.py` | Event parsing (flat payload and `agent-run-events-v2`), `anomaly.scored` builder in S04's envelope |
| `drift.py` | Counters and a Page-Hinkley test on session scores |
| `config.py` | Defaults; every value can be overridden by an environment variable |
| `replay.py` | Replay harness and evaluator (in-process, or publish to Kafka) |
| `demo.py` | Demo models and sessions for trying the pipeline without B3 |
| `send_test_events.py` | Publishes sample sessions (and optionally demo models) for local runs |

### Processing rules

- Calls are ordered by `data.session_call_index`; completeness is judged by the gapless envelope `sequence`. `occurred_at` is never used for ordering (in Agent A's recorded data it contradicts the event order in 35 of 130 sessions).
- `session.ended` closes the session only when every lower `sequence` has arrived, or after `MARKOV_REORDER_TIMEOUT_S`.
- A session whose `session.started` has not arrived holds its calls until it arrives or the reorder timeout passes; then its context is unknown and its first K transitions are not checked.
- Lost calls (a gap still open after the timeout) reset the context and mark the session `complete: false`; they never produce a false alert.
- Duplicates (same `event_id`, `sequence`, `tool_call_id` or call index) are ignored. Output event ids are deterministic (uuid5), so a replayed alert has the same id.
- Sessions idle for `MARKOV_IDLE_TIMEOUT_S` are closed as incomplete, without the `<END>` transition.
- Each session keeps the model version it started with when a new model arrives.

## Kafka Input

| Topic | Content |
|---|---|
| `tool-calls.A`, `tool-calls.B` | Keyed by `session_id`. `session.started`, `tool_call.completed` / `tool_call.failed` (both are calls), `session.ended`. `tool_call.requested` + result with the same `tool_call_id` count as one call; `model_call.*` events are only counted for completeness. |
| `model-updates` | `model.trained` with key `b3-markov-chain.A` / `b3-markov-chain.B` and the transition table embedded in `data.transition_table`. The legacy key `b3-markov-chain` (B3 up to v0.3) is read as Agent B's model. Other keys are ignored. |

Example tool call (flat payload):

```json
{"schema_version": "1.0", "event_id": "8bdd2276-...", "event_type": "tool_call.completed",
 "occurred_at": "2026-11-22T11:46:40.494228+00:00", "run_id": "5bf8a059-...",
 "session_id": "d787821f-...", "sequence": 5, "request_id": null,
 "data": {"agent_id": "A", "tool_call_id": "85866ea0-...", "tool_name": "correlate_columns",
          "arguments": {"dataset_id": "ds-21", "columns": ["visits", "spend"], "method": "spearman"},
          "duration_ms": 42, "success": true, "session_call_index": 4, "time_since_previous_call_ms": 642}}
```

## Model

The model is B3's transition table (one per agent), turned back into B3's `Detector` by `b3_markov.domain.training.from_table`: counts per (state, next), the smoothing configuration (`additive`, `floor` or `backoff`; backoff tables carry B3's order-0 counts), the vocabulary, and the calibration:

| Field | Use |
|---|---|
| `calibration.call_threshold[K]` | Call-level threshold on ln p (B3 v0.3). Missing: the rule falls back to `unseen` (count 0) |
| `calibration.threshold[K]` | Session threshold on the configured score |
| `scoring.score` | `joint`, `joint_max`, `seq` or `args` (B3 Sec. 13.4); `seq` when the table has no `arguments` block |
| `arguments` | Agent B's featurizer and emission counts (B3 v0.2); absent for Agent A |

Default orders: K = 1 for Agent A (73 normal sessions are not enough for order 2), K = 2 for Agent B.

Rules for `out_of_order` (`MARKOV_RULE`): `threshold` (default, lp < call_threshold), `unseen` (count 0, stide-style), `topg` (next symbol not among the g most probable, DeepLog-style).

## Output

Topic `scores`, key `agent_id`. Envelope identical to S04's `anomaly.scored`; S08's extension fields follow the shared core in `data`.

```json
{
  "schema_version": "1.0", "event_id": "<uuid5>", "event_type": "anomaly.scored",
  "occurred_at": "<UTC time of scoring>", "run_id": "...", "session_id": "...", "sequence": 3, "request_id": null,
  "data": {
    "scored_event_id": "<event_id of the tool call>", "agent_id": "B",
    "detector": "markov_order", "model_version": "<version>", "score": 7.41,
    "scope": "call", "check": "out_of_order", "threshold": 5.92, "is_anomaly": true, "rule": "threshold",
    "order": 2, "call_index": 2,
    "transition": {"state": "<START>>find_contact", "next": "save_draft", "count": 0, "state_total": 4, "p": 0.0006},
    "scored_event_occurred_at": "<event time of the tool call>", "latency_ms": 3
  }
}
```

| | Call-level alert | Session score |
|---|---|---|
| `detector` | `markov_order` | `markov` |
| when | as soon as a call (or `<END>`) is below the threshold | once per session, when it closes |
| `score` | `-ln p` of the transition (nats) | configured B3 score (`joint` for B, `seq` for A) |
| other fields | `order`, `call_index`, `transition`, `rule` | `score_kind`, `seq_score`, `arg_score`, `arg_max`, `worst_arg`, `n_unseen`, `min_p`, `worst_transition`, `n_calls`, `max_run_length`, `empty_session`, `complete`, `violations` |

Agent policies (spec Secs. 5.2 and 6):

- **Agent A's call alerts are computed but not published** by default (`MARKOV_CALL_ALERTS_A=false`): with 73 normal training sessions they would be mostly false alarms. Its session scores are published. The replay output still contains the unpublished alerts.
- **Empty sessions** (no tool call): `alert` for Agent A (an empty session is a real signal there), `tag` for Agent B (published with `empty_session: true`, `is_anomaly: false`; B3 identifies them as generator failures), or `drop`.

## Installation

Python 3.11 is recommended. S08 needs the B3 package from the same repository; install it first. From the component directory (`services/stream-processing/s08-markov-order-check`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e ../../batch-processing/b3-markov-chain
pip install -e ".[test]"
```

## Running Locally

Make sure the Kafka infrastructure is running and reachable at `localhost:29092` (from the repository root: `docker compose up -d kafka kafka-init`).

1. Make a model available on `model-updates`. Either train and announce B3's model (`docker compose --profile batch run --rm b3-train`), or publish small demo models for both agents:

   ```bash
   PYTHONPATH=src python -m markov_order_check.send_test_events --with-demo-model --models-only
   ```

   Do not publish demo models on a shared broker where B3 announces real ones: the newest message per key wins.

2. Start the check from the component directory:

   ```bash
   PYTHONPATH=src python -m markov_order_check.consumer
   ```

   It loads the models first (log line `Model bootstrap done: loaded=[...]`), then subscribes to `tool-calls.A` and `tool-calls.B`.

   B3 announces real models with `docker compose --profile batch run --rm b3-train` (Agent B) and `... run --rm b3-train-a` (Agent A).

3. Send sample sessions (normal ones, plus one out-of-order session per agent at the end):

   ```bash
   PYTHONPATH=src python -m markov_order_check.send_test_events
   ```

   Watch the results in Kafka UI (http://localhost:8080, topic `scores`) or with
   `docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic scores`.
   The mock agents (`docker compose --profile mocks up -d`) or the real agents work as a source too.

### Replay and evaluation (spec Sec. 9)

In-process replay of a dataset file against a model file, without Kafka:

```bash
PYTHONPATH=src python -m markov_order_check.replay --agent A \
    --dataset-file ../../../dataset/agent_a/events.jsonl \
    --model-file <models-dir>/b3-markov-chain/A/<version>/transition_table.json \
    --out replay_a.jsonl
```

It prints recall per attack type, false-alarm rates, earliness (`median_calls_to_alert`, `median_calls_saved`), each with and without empty sessions, and writes every output (with `"published": true/false`) to `--out`. Options: `--shuffle 3`, `--duplicate-rate 0.05`, `--drop-rate 0.01`, `--restart-at 0.5` (robustness), `--with-s07-flags s07.jsonl` (overlap with S07), `--fold-models <model>/folds` (held-out false-alarm rates). The dataset can be Agent A's recorded records (`{"category": ..., "event": {...}}`) or flat events (Agent B).

**Held-out false alarms.** The final model has seen every normal session, so replaying normal sessions through it under-states false alarms. Train with `--save-fold-models` in B3 and pass the `folds/` directory: each normal session is then scored by the fold model that never saw it. The replay rebuilds B3's folds (`kfold` over the normal sessions in the order B3's loader returns them, with the seed stored in the tables) and checks every fold against its table's `training.input_sha256`, so the dataset file must be the one B3 trained on. For example, with Agent A's recorded file:

```bash
python -m b3_markov.main --agent A --dataset-file agent_a.jsonl --models-dir models --save-fold-models
PYTHONPATH=src python -m markov_order_check.replay --agent A --dataset-file agent_a.jsonl \
    --model-file models/b3-markov-chain/A/<version>/transition_table.json \
    --fold-models models/b3-markov-chain/A/<version>/folds
```

On the recorded file this gives the same rates as B3's cross-validation (normal sessions: 5.5% call alerts, 5.5% session flags; injected sessions: 10.5% session recall).

To publish a dataset to Kafka for the running service instead: add `--publish` (and `--speed`, sessions per second).

## Configuration

Defaults are in `src/markov_order_check/config.py`; every one can be overridden by an environment variable:

| Variable | Default |
|---|---|
| `KAFKA_BOOTSTRAP` | `localhost:29092` |
| `KAFKA_GROUP_ID` | `markov-order-check` |
| `TOPICS` | `tool-calls.A,tool-calls.B` |
| `MODEL_TOPIC` | `model-updates` |
| `SCORES_TOPIC` | `scores` |
| `MARKOV_ORDER_A` / `MARKOV_ORDER_B` | `1` / `2` |
| `MARKOV_RULE` | `threshold` (or `unseen`, `topg`) |
| `MARKOV_TOPG` | `2` |
| `MARKOV_REORDER_TIMEOUT_S` | `5` |
| `MARKOV_IDLE_TIMEOUT_S` | `1800` |
| `MARKOV_MODEL_BOOTSTRAP_TIMEOUT_S` | `15` |
| `MARKOV_PH_DELTA` / `MARKOV_PH_LAMBDA` | `0.05` / `50` |
| `MAX_SESSIONS` | `10000` (oldest idle session is closed first) |
| `MARKOV_CALL_ALERTS_A` / `MARKOV_CALL_ALERTS_B` | `false` / `true` |
| `MARKOV_EMPTY_SESSION_A` / `MARKOV_EMPTY_SESSION_B` | `alert` / `tag` (or `drop`) |

## Testing

Run the unit tests from the component directory (no broker needed; Kafka is replaced by fakes). With the packages installed as in [Installation](#installation):

```bash
pytest
```

Without installing anything but pytest, the tests also find B3 in the repository (`../../batch-processing/b3-markov-chain/src`):

```bash
PYTHONPATH=src pytest
```

| Test file | Covers |
|---|---|
| `test_events.py` | flat and `agent-run-events-v2` parsing, `<UNK>`, envelope = S04 core |
| `test_detector.py` | checks, rules, ordering and closing, lost calls, late and duplicate events, idle sessions, empty-session and Agent A policies |
| `test_models.py` | per-agent keys, legacy key, validation, fallback to `unseen`, version pinning |
| `test_parity.py` | stream scores equal B3's `Detector.score` within 1e-9: all three smoothings, orders 1 and 2, and the joint score with argument flags |
| `test_robustness.py` | shuffled, duplicated, dropped and restarted replays; deterministic ids; evaluation |
| `test_consumer.py` | models loaded before tool calls are consumed; flush before commit; detectors and keys; unpublished alerts never reach Kafka |

Optional check against Agent A's recorded file:

```bash
AGENT_A_DATASET=/path/to/agent_a_events.jsonl PYTHONPATH=src pytest tests/test_robustness.py
```

Run the tests inside the Docker image (build it as in [Docker](#docker) first):

```bash
docker run --rm atgm-markov-order-check python -m pytest -q
```

## Docker

The image contains the B3 package, so its build context is the repository's `services/` directory, not this folder. From the repository root:

```bash
docker build -f services/stream-processing/s08-markov-order-check/Dockerfile -t atgm-markov-order-check services
```

(`Dockerfile.dockerignore` next to the Dockerfile limits the context to the B3 package and this component.)

Run the container:

```bash
docker run --rm \
  --network atgm \
  -e KAFKA_BOOTSTRAP=kafka:9092 \
  -e KAFKA_GROUP_ID=markov-order-check \
  atgm-markov-order-check
```

`atgm` is the Compose network of this repository (`networks.default.name` in `docker-compose.yml`).

With Docker Compose, from the repository root (service `markov-order-check`):

```bash
docker compose up -d --build markov-order-check
docker compose logs -f markov-order-check
docker compose run --rm markov-order-check python -m pytest -q     # tests in the service image
```

After changing B3 or S08 code: `docker compose build markov-order-check`.

## Known limitations

- S08 and B3 must be deployed from the same commit: a change to B3's arithmetic changes S08's scores (the Compose service builds both from the repository).
- A table without `call_threshold` (B3 before v0.3) makes `out_of_order` use the `unseen` rule; until B3 announces an Agent A model (`b3-markov-chain.A`, `b3-train-a`), Agent A is counted as `unscored_no_model`.
- State is in memory: after a restart, in-flight sessions are scored as incomplete.
- The order check cannot see attacks whose tool sequence matches a normal session (51 of 57 injected sessions in Agent A's recorded data).
