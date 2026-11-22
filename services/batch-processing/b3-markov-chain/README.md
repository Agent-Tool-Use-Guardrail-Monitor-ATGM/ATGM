# B3 – Markov-chain anomaly detector (batch layer)

**Owner:** _(fill in)_  **Status:** spec v0.4: one model per agent (A and B), argument features for Agent B, call-level
threshold; training, calibration, evaluation and announcing on `model-updates` implemented. Docker image not yet built in CI.

Learns the normal order of an agent's tool calls from its normal sessions and announces a transition table (plus
thresholds) on `model-updates`. **Live scoring is not done here**: the stream pipeline (S08, detectors `markov` and
`markov_order`) reads the announced tables and scores `tool-calls.A` / `tool-calls.B`; this package never consumes a topic
and never publishes to `scores`. Spec: the B3 specification doc (sections 1–15). Method: multi-order Markov chain,
Sha, Zhu, Chen, Huang, IEEE TCC 2018. Pure Python, no runtime dependencies (extras: `db`, `kafka`, `test`).

## Data
- **Agent B** (default): same access path as B1: `dataset/agent_b/events/events_for_<file>` (+ `labels/labels_for_<file>`),
  or `--events-file <raw events.jsonl>`, or `--source db` (analytics_db, B1's SQL; the calls query also selects
  `agent_events.occurred_at`, a column to confirm). Calls are `tool_call.completed` and `tool_call.failed`.
- **Agent A**: `--agent A --dataset-file <recorded.jsonl>`: wrapped records (`category`, `attack_type`, `label`, `event`) with
  payload `agent-run-events-v2`. A request (`tool_call.requested`, has the tool name) and its result (`completed` /
  `failed`, joined by `tool_call_id`) are one call, counted at the result; a call without a name is `<UNK>`; failed calls
  count; `model_call.*` is ignored; order by `session_call_index`, else by `sequence`.
- Duplicated events (same `event_id`) are dropped; B sessions without `session.ended`, or whose call count differs from
  `call_count` (truncated file), are skipped. Training uses only normal sessions: `category == "normal"` (DB: newest
  reviewer verdict is not `attack`); `--normal-by label` uses the behaviour label `compliant` (Agent B).

## Model
Counts of (last K tools → next tool) with `<START>` / `<END>` / `<UNK>` padding (a session of T calls gives T+1
transitions), row-normalised. Smoothing: `additive` (default; α=0.1 for B, tuned by 10-fold CV for A: `--alpha cv`),
`floor` (ε=1e-5, paper replication), `backoff` (stupid backoff 0.4). `domain/scoring.py` exposes
`step(model, order, context, symbol) -> (ln p, count, row_total)`; whole-session scoring is a fold over it, so batch and
stream share one code path (`domain/arguments.py` likewise featurizes one call given an `ArgContext`).

- **Agent B** adds argument features (spec Sec. 13): per call a few categorical flags (recipient domain known / rare /
  unseen / malformed / placeholder, secret or injection patterns, date invalid / out of window, body changed after the
  check) with a per-tool naive-Bayes emission model fitted on normal sessions (featurizer refitted in every CV fold).
  Session score `joint` = (sequence NLL + argument NLL) / transitions; `joint_max`, `seq`, `args` are ablations. Only flag
  classes and recipient domains are stored. The secret / injection lexicons are prior knowledge.
- **Agent A** is sequence only (`--no-arguments` is forced, score `seq`): its clear arguments are not recorded. Its
  vocabulary is fixed to the declared `statistics-tools-v1` toolset (`--vocabulary` overrides), percentile default 95.
- **Call-level threshold** (Sec. 14.3): `m(s)` = lowest ln p over a session's transitions; `calibration.call_threshold[K]`
  = the (100 − p)-th percentile of the held-out `m(s)` (10-fold CV, normal sessions only; attack data never enters).

## Results
`metrics.json` holds all parameters, the data profile (including the share of adversarial sessions whose exact tool
sequence also occurs in normal data, and the resulting recall ceiling of any sequence-only model), per-order results
(held-out normal scores → threshold; ROC-AUC with bootstrap CI, PR-AUC, precision/recall/F1, recall per attack type,
90/95/99/99.5 sensitivity, false-alarm interval), a `call_level` block (held-out `m(s)` per session, false-alarm rate of the
call check / session threshold / their union, per attack type the share below `call_threshold` and the index of the first
call below it), `alpha` (chosen value and sensitivity), `ablation`, all smoothing × order combinations, and baselines
(bag of tools, stide-style unseen-bigram fraction). `--exclude-labels model_failure` also trains without those normal
sessions and reports the difference (`sensitivity_without_labels`).

## Run
Locally (Python 3.10+, no runtime dependencies; run from `src/` or after `pip install -e .`):
```
python -m b3_markov.main                                            # Agent B, dataset files (same path as B1)
python -m b3_markov.main --events-file events.jsonl --orders 1 2 3
python -m b3_markov.main --agent A --dataset-file agent_a.jsonl --exclude-labels model_failure --announce
python -m b3_markov.main --source db --announce                     # as in the Docker image (Agent B)
python -m b3_markov.main --save-fold-models                         # also <model>/folds/fold_<i>.json for replays
```

### In Docker
From the repository root, with the stack running (`docker compose up -d`):
```
docker compose --profile batch run --rm b3-train      # Agent B → key b3-markov-chain.B
docker compose --profile batch run --rm b3-train-a    # Agent A → key b3-markov-chain.A
```
- It prints the metrics, saves `transition_table.json` and `metrics.json` to the `b3-models` volume under
  `b3-markov-chain/<agent>/<version>/` and publishes **one** `model.trained` message (key `b3-markov-chain.<agent>`,
  `data.agent`, table and compact metrics embedded) to `model-updates`. Keep that topic compacted so the newest model of
  each agent is retained.
- Results: Kafka UI (http://localhost:8080) topic `model-updates`; the files in the volume:
  `docker compose run --rm --entrypoint ls b3-train /models/b3-markov-chain/B`.
- After changing the code: `docker compose build b3-train`.
- Standalone image: `docker build -t b3-markov-chain .` (default command: `--source db --announce`; needs `ANALYTICS_DB`
  and `KAFKA_BOOTSTRAP`).

### Tests
The tests need only pytest and no Kafka or Docker (Kafka is replaced by a fake producer). They are not part of the image.
```
python3 -m venv .venv && source .venv/bin/activate
python -m pip install pytest        # or: python -m pip install -e ".[test]"
pytest
```
Variants: `pytest -q`, `pytest tests/test_arguments.py`, `pytest -k tamper`.

Options are CLI flags (`--agent --orders --smoothing --alpha --epsilon --vocabulary --percentile --folds --seed
--bootstrap --normal-by --exclude-labels --no-arguments --score --arg-alpha --min-domain-count --date-slack-days
--save-fold-models --models-dir --announce`, plus the data flags above); env: `ANALYTICS_DB`, `KAFKA_BOOTSTRAP`
(localhost:29092), `MODELS_DIR`, `DATASET_DIR`.

## Next
Run Agent B on the full 269 + 231 dataset and Agent A on the recorded file; confirm the Agent A payload field names against
the real file (the reader follows the spec text, not a sample); generate `uv.lock` (needs network); decide the order and
percentile the stream pipeline should use per agent.
