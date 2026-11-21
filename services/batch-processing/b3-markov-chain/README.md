# B3 – Markov-chain anomaly detector

**Owner:** Agnes  **Status:** v0.2 (spec Sec. 13): sequence chain plus argument features; training, calibration, evaluation and scorer implemented; Docker image not yet built in CI.

Learns the normal order of tool calls of Agent B and scores each finished session by how unlikely its
tool sequence is. Spec: the B3 specification doc (sections 1–12). Method: multi-order Markov chain,
Sha, Zhu, Chen, Huang, IEEE TCC 2018. Pure Python, no runtime dependencies (extras: `db`, `kafka`, `test`).

## Data
Same access path as B1: `dataset/agent_b/events/events_for_<file>` (+ `labels/labels_for_<file>`), or
`--source db` (analytics_db, B1's SQL; the calls query now also selects `agent_events.occurred_at`, a column to confirm). Extra: `--events-file <raw events.jsonl>`. Duplicated events
(same `event_id`) are dropped; sessions without `session.ended`, or whose call count differs from
`call_count` (truncated file), are skipped. Training uses only normal sessions: `category == "normal"`
(DB: newest reviewer verdict is not `attack`); `--normal-by label` uses the behaviour label `compliant`.

## Model
Counts of (last K tools → next tool) with `<START>` / `<END>` / `<UNK>` padding (a session of T calls gives
T+1 transitions), row-normalised. Smoothing: `additive` (default, α=0.1, unseen context → uniform),
`floor` (ε=1e-5, paper replication), `backoff` (stupid backoff 0.4). Score = mean negative log-likelihood
per transition (higher = more anomalous). **Argument features (v0.2):** each call is mapped to a few categorical flags (recipient domain known / rare / unseen /
malformed / placeholder, secret or injection patterns in text, terms or body, date invalid / out of window, body changed
after the check, ...) and a per-tool naive-Bayes emission model gives P(flags | tool), estimated on normal sessions only
(featurizer refitted inside every CV fold). Session score `joint` = (sequence NLL + argument NLL) / transitions; other
scores (`joint_max`, `seq`, `args`) are reported as ablation. Raw argument strings are never stored in the table, only
classes and recipient domains. `--no-arguments` gives the v0.1 tool-name-only model. The secret / injection lexicons are
prior knowledge (`domain/arguments.py`). Timing and the success flag are not used (no signal / no failures in normal data).
The order-inversion feature of Sec. 6 (exploratory) is **not** implemented.

## Results
`metrics.json` holds all parameters, an `ablation` block (seq / args / joint / joint_max), the data profile (incl. how many adversarial sessions have an exact
tool sequence that also occurs in normal data – no sequence-only model can flag those), per-order results
(10-fold held-out normal scores → threshold at the 99th percentile; ROC-AUC with bootstrap CI, PR-AUC,
precision/recall/F1, recall per attack type, 95/99/99.5 sensitivity), all smoothing×order combinations,
and baselines (bag of tools = order 0; stide-style unseen-bigram fraction).

## Run
Locally (Python 3.10+, no runtime dependencies):
```
python -m b3_markov.main                                  # dataset files (same path as B1)
python -m b3_markov.main --events-file events.jsonl --orders 1 2 3
python -m b3_markov.main --source db --announce           # as in the Docker image
python -m b3_markov.scorer                                # live scoring: tool-calls.B + model-updates -> scores
```
(Run from `src/` or after `pip install -e .`.)

### In Docker
From the repository root, with the stack running (`docker compose up -d`):
```
docker compose up -d b3-scorer                            # scorer: tool-calls.B -> scores (key = agent_id)
docker compose --profile batch run --rm b3-train          # train on ./dataset/agent_b and publish to model-updates
docker compose logs -f b3-scorer                          # "B3 model loaded: ...", then one line per scored session
```
- `b3-train` prints the metrics, saves `transition_table.json` and `metrics.json` to the `b3-models` volume and
  publishes one `model.trained` message (key `b3-markov-chain`, table embedded) to `model-updates`. The scorer
  reloads the model from that message; if it starts later it loads the newest model from the volume.
- Results: Kafka UI (http://localhost:8080) topics `model-updates` and `scores`; the scorer log; the files in the
  volume: `docker compose run --rm --entrypoint ls b3-scorer /models/b3-markov-chain`.
- After changing the code: `docker compose build b3-scorer b3-train`, then restart `b3-scorer`.
- Standalone image: `docker build -t b3-markov-chain .` (default command: `--source db --announce`; needs
  `ANALYTICS_DB` and `KAFKA_BOOTSTRAP`).

### Tests
The tests need only pytest and no Kafka or Docker (Kafka is replaced by a fake producer). They are not part of the image.
```
python3 -m venv .venv && source .venv/bin/activate
python -m pip install pytest        # or: python -m pip install -e ".[test]"
pytest
```
Variants: `pytest -q`, `pytest tests/test_arguments.py`, `pytest -k tamper`.

Options are CLI flags (`--orders --smoothing --alpha --epsilon --percentile --folds --seed --bootstrap
--normal-by --no-arguments --score --arg-alpha --min-domain-count --date-slack-days --models-dir --announce`); env:
`ANALYTICS_DB`, `KAFKA_BOOTSTRAP` (localhost:29092), `MODELS_DIR`, `DATASET_DIR`; scorer: `B3_INPUT_TOPICS`,
`B3_MODELS_DIR`, `B3_MODEL_KIND`.
Output: `models/b3-markov-chain/<UTC time>_<smoothing>/{transition_table.json, metrics.json}`; `--announce`
publishes one `model.trained` message (key `b3-markov-chain`) to `model-updates` with the table embedded.
The scorer publishes `anomaly.scored` to `scores` with key = agent id.

## Next
Run on the full 269 + 231 dataset; decide the live order/threshold (`calibration.primary_order`, `threshold`).