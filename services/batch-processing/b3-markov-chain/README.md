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
```
pip install -e ".[test]" && pytest
python -m b3_markov.main                                  # dataset files
python -m b3_markov.main --events-file events.jsonl --orders 1 2 3
python -m b3_markov.main --source db --announce           # as in the Docker image
docker build -t b3-markov-chain . && docker run --rm --network host -e ANALYTICS_DB=... b3-markov-chain
python -m b3_markov.scorer                                # live scoring: tool-calls.B + model-updates -> scores
```
Options are CLI flags (`--orders --smoothing --alpha --epsilon --percentile --folds --seed --bootstrap
--normal-by --models-dir --announce`); env: `ANALYTICS_DB`, `KAFKA_BOOTSTRAP` (localhost:29092),
`MODELS_DIR`, `DATASET_DIR`; scorer: `B3_INPUT_TOPICS`, `B3_MODELS_DIR`, `B3_MODEL_KIND`.
Output: `models/b3-markov-chain/<UTC time>_<smoothing>/{transition_table.json, metrics.json}`; `--announce`
publishes one `model.trained` message (key `b3-markov-chain`) to `model-updates` with the table embedded.

## Next
Run on the full 269 + 231 dataset; decide the live order/threshold (`calibration.primary_order`, `threshold`).