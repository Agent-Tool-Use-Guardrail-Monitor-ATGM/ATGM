# Spec: Markov Chain Anomaly Detection for LLM Agent Tool-Call Sequences

Data science master's course project · specification v0.4 · 22 Nov 2026 (v0.2 adds argument features, see Sec. 13; v0.3 moves live scoring to a separate stream pipeline and adds a call-level threshold, see Sec. 14; v0.4 adds a separate model for Agent A and per-agent model keys, see Sec. 15)

## 1. Purpose and scope

Learn a model of **normal** tool-call behaviour of an LLM agent from event logs (JSONL), and use it to score new sessions as normal or abnormal. The learning algorithm is a discrete-time Markov chain (optionally higher-order) estimated by maximum likelihood from `category == "normal"` sessions only. The primary deliverable is a **transition table in JSON**; the secondary deliverable is a scoring and evaluation procedure that uses that table.

**Confirmed scope:** about 269 normal training sessions with at most 10 tool calls each (so at most about 2,700 calls); detection at **session level**; **argument-level features were out of scope in v0.1 and are in scope from v0.2 (Sec. 13, which supersedes this sentence, the tool-name-only wording of Sec. 4.1 and the rating of attack types in Secs. 7.3 and 7.4)**.

Also out of scope for v0.1: neural sequence models, HMMs, online/incremental updating, time-inhomogeneous chains.

**Evaluation data:** 231 adversarial sessions across 9 attack types (Sec. 7.3). No normal session contains a failed call, so the success-flag variant of the paper is dropped in v0.1.

## 2. What we take from the source paper

Source: Sha, Zhu, Chen, Huang, *Statistical Learning for Anomaly Detection in Cloud Server Systems: A Multi-Order Markov Chain Framework*, IEEE Trans. Cloud Computing 6(2), 2018 (system-call sequences, DARPA/BSM data).

| Paper idea | Use in this project |
| --- | --- |
| Train only on anomaly-free data; labels are irrelevant at training time (Sec. 3.1) | Train only on normal sessions |
| MLE of initial vector Q and transition matrix P by counting (Eq. 17-18) | Count-based MLE, **row-normalised** (see note below) |
| Sequence likelihood = initial prob x product of transition probs (Eq. 12, 31) | Session score = negative log-likelihood |
| K-th order chain via state = tuple of last K symbols; m^K states (Sec. 3.2.1) | Orders K = 1, 2, 3 as a config parameter |
| Multivariate chain: combine system call and return value into one joint state (Sec. 3.2.2) | Dropped in v0.1 (no failed calls in normal data); would be a joint state `tool_name + success flag` |
| Zero probabilities replaced by a tiny constant (1e-5) (Sec. 4.1, from Ye 2000) | Baseline smoothing mode `floor` for replication |
| Artificial state for never-seen symbols (Sec. 4.1) | `<UNK>` token |
| Non-zero table / sparse storage; log-probabilities so scoring is additions (Sec. 4.4) | Sparse dict-of-dicts JSON; log-space scoring |
| Anomaly indicator: ranking of scores across orders; for normal data -log P falls as order rises, for anomalies the order reverses (Sec. 5.3, Eq. 65-66) | Optional secondary indicator (`order_inversion`) |

**Deviations from the paper (and why):**

1. *Row normalisation.* Eq. 18 and Algorithm 1 line 19 divide all counts by the total number of transitions, which gives a joint distribution, while the worked example in Sec. 4.5 (probabilities of 1) and the constraint in Eq. 15 imply a conditional (row-stochastic) matrix. We use the conditional form: P(next | current) = count(current, next) / count(current, \*).
2. *Many short sessions instead of one long stream.* The paper trains on one stream of about 800k calls and uses an initial vector Q. Our data are many short sessions (about 4-10 calls). We pad each session with `<START>` and `<END>` tokens, so Q becomes just the row of `<START>`, and session boundaries and length are modelled explicitly.
3. *Tiny training data.* The paper's floor constant is too crude when most transitions are unseen. We add additive (Lidstone) smoothing and optional backoff as better-motivated options (compare smoothing/data models on system-call data).
4. *Scoring unit.* The paper scores sliding windows of 200 calls. We score whole sessions, with an optional window for long sessions.

## 3. Input data

### 3.1 Observed event schema

One JSON object per line. Fields used by the model:

- `event_type`: `session.started` | `tool_call.completed` | `session.ended`
- `session_id`, `run_id`, `sequence` (event order within session; `session.started` = 1)
- `session.started`: `data.category` (`normal` | `adversarial`), `data.attack_type` (null for normal, e.g. `unsafe_args`)
- `tool_call.completed`: `data.tool_name`, `data.success` (bool), `data.session_call_index` (1-based call order), `data.arguments`, `data.duration_ms`, `data.time_since_previous_call_ms`
- `session.ended`: `data.call_count`

The sample shows 6 tools: `find_contact`, `get_current_datetime`, `get_free_slots`, `tone_checker`, `sensitive_content_scan`, `save_draft`. All sample calls have `success: true`.

### 3.2 Sessionization rules

1. Read all files, skip and log malformed lines.
2. **Deduplicate** by `event_id` (the sample contains the same normal session twice).
3. Group by `session_id`; sort `tool_call.completed` events by `data.session_call_index` (fall back to `sequence`). Assert both orders agree; log violations.
4. Session label = `data.category` of its `session.started` event. Sessions without a `session.started` event get label `unknown` and are never used for training.
5. Validate `session.ended.data.call_count == number of tool calls`. Sessions failing validation or lacking `session.ended` are flagged `incomplete` and excluded from training by default (`include_incomplete: false`).
6. A session with zero tool calls is valid and yields the sequence `<START> -> <END>`.

### 3.3 Training filter

Training set = sessions with `category == "normal"` AND valid. Adversarial sessions must never touch counts, vocabulary or thresholds; they are used only for evaluation (Sec. 7). Assert this in code.

## 4. Model definition

### 4.1 Symbols and states

- Observation `x_t` = `tool_name` of the t-th call. The paper's two-dimensional variant (tool plus success flag) is not implemented in v0.1, because normal data contain no failed calls; if a `variant` config parameter is kept, it is fixed to tool-name-only.
- Vocabulary V = all symbols seen in normal training sessions. Add special tokens `<START>`, `<END>`, `<UNK>`. Any symbol at inference that is not in V is mapped to `<UNK>`.
- Padded session of T calls: `<START>`^K, x\_1, ..., x\_T, `<END>`. It has T+1 predicted transitions regardless of K, which makes scores comparable across orders and sessions of equal length.
- State at step t for order K = tuple (x\_{t-K}, ..., x\_{t-1}); predicted symbol = x\_t.
- Tool names must not contain the state delimiter `>`; validate.

### 4.2 Estimation (training)

For each order K in the configured set:

1. For every normal session, pad and slide a window of K+1 symbols; increment `count[state][next]`.
2. `row_total[state] = sum over next of count[state][next]`.
3. MLE: `p_mle(next | state) = count / row_total`.
4. Store counts (source of truth) and p\_mle in the output. Smoothed probabilities are computed at scoring time from counts and the stored smoothing config.

Complexity: training O(N) over N calls with hash maps; the table has at most m^K x m entries but is stored sparsely (the paper's non-zero table idea).

### 4.3 Smoothing (config `smoothing.method`)

- `floor` (paper replication): unseen transition gets constant `epsilon` (default 1e-5); seen ones use p\_mle. Rows do not sum exactly to 1, as in the paper.
- `additive` (**default**): `p(next | state) = (count + alpha) / (row_total + alpha * |V_next|)`, with V\_next = tools + `<END>` + `<UNK>`, alpha default 0.1 (tune by 10-fold cross-validated held-out likelihood). A state never seen as context gets the uniform distribution 1/|V\_next|.
- `backoff` (optional, K >= 2): if `row_total[state] < min_support` or next is unseen, use the order K-1 distribution (stupid backoff with factor 0.4, or interpolation with lambda tuned on held-out normal sessions).

## 5. Output: transition table (JSON)

One file per trained model, containing one table per order. Sparse: only observed (state, next) pairs are stored. State keys for K > 1 join symbols with `>`.

```json
{
  "spec_version": "0.1",
  "model": {
    "type": "markov_chain",
    "state_encoding": "tool_name",
    "tokens": {"start": "<START>", "end": "<END>", "unk": "<UNK>"},
    "state_delimiter": ">",
    "smoothing": {"method": "additive", "alpha": 0.1, "epsilon": 1e-05},
    "log_base": "e"
  },
  "training": {
    "label_filter": "normal",
    "n_sessions": 2,
    "n_calls": 10,
    "input_sha256": ["<hash per input file>"],
    "trained_at": "<ISO-8601 UTC>",
    "random_seed": 42
  },
  "vocabulary": ["find_contact", "get_current_datetime", "get_free_slots", "tone_checker", "sensitive_content_scan", "save_draft"],
  "orders": {
    "1": {
      "n_transitions": 12,
      "transitions": {
        "<START>": {"total": 2, "next": {"find_contact": {"count": 2, "p_mle": 1.0}}},
        "get_free_slots": {"total": 2, "next": {"tone_checker": {"count": 1, "p_mle": 0.5}, "save_draft": {"count": 1, "p_mle": 0.5}}}
      }
    }
  },
  "calibration": {
    "method": "kfold-10",
    "score": "mean_nll_per_transition",
    "threshold": null,
    "percentile": 99,
    "call_threshold": null
  }
}
```

The `transitions` map above is abridged; the full file lists every observed state. Orders 2 and 3 use the same structure under keys `"2"` and `"3"`.

## 6. Scoring (inference)

For a session s with padded transitions t = 1..L (L = T + 1):

- `NLL(s) = - sum over t of ln p(x_t | state_t)`
- **Primary anomaly score** = `NLL(s) / L` (mean NLL per transition, length-normalised).
- Secondary indicators, all reported: `n_unseen` (transitions with zero training count), `min_p` (lowest transition probability), and `order_inversion` = true if NLL\_1 < NLL\_2 < NLL\_3 is violated in the paper's sense, i.e. the normal pattern NLL\_1 > NLL\_2 > NLL\_3 reverses (Sha et al., Sec. 5.3). Treat the last one as exploratory: the paper validated it on about 800k training calls, and the effect may not hold with a handful of sessions.
- Decision: `abnormal` if primary score > threshold (Sec. 7.1). Return the score, the decision and the single most surprising transition for explainability.

**Indicators for repetition and length.** Report both mean NLL (primary) and total NLL. Add three sequence-only indicators: `n_calls`, `exceeds_max_len` (n\_calls greater than the longest normal training session, expected 10), and `max_run_length` (longest run of the same tool). Reason: harvesting and flooding sessions repeat one tool 9-21 times. If a self-loop such as get\_free\_slots to get\_free\_slots occurs in normal data, each repeat has moderate probability and mean NLL dilutes, while total NLL and run length stay extreme. Evaluate each indicator on its own; the Markov score stays the main model, the others are ablations.

## 7. Calibration and evaluation

### 7.1 Threshold (normal data only)

Compute scores of held-out normal sessions with 10-fold cross-validation (plain session-level folds, because all sessions share one run\_id), giving a held-out score for each of the 269 normal sessions. Threshold = chosen percentile (default 99th, which leaves about 3 of 269 normal sessions above it; report the 95th and 99.5th as sensitivity checks) of those held-out scores. Report the false-positive rate this implies.

### 7.2 Evaluation (uses labelled adversarial sessions)

- Split by **session**, never by event; keep all sessions of one `run_id` in the same fold if there are several runs (the data have a single run\_id, so this does not apply).
- Metrics: ROC-AUC, PR-AUC, precision/recall/F1 at the calibrated threshold, and recall per `attack_type`.
- Compare: order K = 1, 2, 3 (1 and 2 are primary; with about 2,700 training calls, 3 is sparse, so treat it and the order-inversion indicator as exploratory); smoothing modes; baselines (a) set of seen tool-bigrams ('stide'-style lookup), (b) bag-of-tools frequency model.
- Report confidence intervals (bootstrap over sessions). Be explicit about the small sample size.

### 7.3 Attack types and what a sequence model can see

There are 231 adversarial sessions. The first three columns come from your attack table; the last two are my analysis of what a model using only tool names can detect. Per-type counts are not yet known.

| Attack | Rule(s) broken | Mock scorer sees it | Tool-name sequence sees it | Why |
| --- | --- | --- | --- | --- |
| `unauthorized_tool` | `tool_not_allowed` | yes | **yes** | Unknown tool maps to `<UNK>`, an unseen transition |
| `unsafe_args` | `secret_in_args` | yes | no | Same tool sequence as normal; the secret is in arguments |
| `skipped_check` | `precondition_missing` | yes | **partly** | Skipping only one check gives an unseen transition; skipping both may match normal sessions (see Sec. 11) |
| `recipient_hijack` | `recipient_not_allowed` | no | no | Arguments only |
| `contact_harvesting` | `contact_name_not_allowed`, `max_calls_exceeded` | yes | **yes** | Repeated find\_contact, more than 10 calls |
| `calendar_harvest` | `max_calls_exceeded` | yes | **likely** | 9-21 get\_free\_slots calls; weaker if repeats occur in normal data |
| `invalid_date` | `date_invalid_format` or `date_out_of_window` | no | no | Arguments only |
| `draft_flooding` | `max_calls_exceeded` | yes | **yes** | save\_draft repeated 9-16 times, an unseen self-loop |
| `post_check_tamper` | `secret_in_args`, `unscanned_content` | yes | no | Same sequence as normal; secret added after the scan |

Consequences for the evaluation:

- Four of nine types (`unsafe_args`, `recipient_hijack`, `invalid_date`, `post_check_tamper`) are invisible by design. If the 231 sessions are roughly balanced across types (about 26 each), overall recall cannot exceed about 56%. This is a property of the data and the no-arguments decision, not a model defect.
- Report results on two sets, fixed in advance: all 231 sessions, and the **sequence-observable subset** (`unauthorized_tool`, `skipped_check`, `contact_harvesting`, `calendar_harvest`, `draft_flooding`). Also report recall and ROC-AUC per `attack_type`, each against held-out normal sessions.
- Protocol: choose K, alpha and the threshold using only held-out normal sessions (10-fold CV). Train the final model on all 269 normal sessions and score the 231 adversarial sessions once. False-positive rate comes from the CV scores. Adversarial sessions are never used for any choice.

### 7.4 What the data actually look like (partial view)

The dataset message was cut off mid-record, so these observations come from the first part of the file only. They revise the a priori ratings in Sec. 7.3 and must be confirmed on the full file (Step 0 below).

- **Normal sessions are not one fixed workflow.** The common pattern is find\_contact, get\_current\_datetime, get\_free\_slots (1 to 3 times), tone\_checker, sensitive\_content\_scan, save\_draft (5 to 8 calls). Also normal: a 4-call variant with no checks (find\_contact, get\_current\_datetime, get\_free\_slots, save\_draft, mostly holiday requests and thesis-outline mails), variants with get\_current\_datetime or get\_free\_slots before find\_contact, variants with no get\_free\_slots, and a few odd orders (one has save\_draft before the checks). Longest normal session seen: 8 calls.
- **Repeated get\_free\_slots is normal** (2 or 3 calls in many normal sessions), so the self-loop is a seen transition. Repetition only becomes suspicious well beyond 3.
- **skipped\_check is mostly indistinguishable.** Most observed skipped\_check sessions have exactly the 4-call sequence of the normal no-check variant. Only unusual shapes (a doubled save\_draft, a 12-call session with repeated save\_draft and scan) stand out.
- **Attack sessions do not match the call counts in your table.** Observed calendar\_harvest, contact\_harvesting and draft\_flooding sessions mostly have 4 to 8 calls. The harvesting is often only in the draft text (for example, a request for the next 20 days) or in arguments. One draft\_flooding session has just 2 save\_draft calls; one contact\_harvesting session has 3 find\_contact calls.
- **No unauthorized tool names appeared** in the observed unauthorized\_tool sessions; they use only the six known tools. The `<UNK>` path may never fire. Check the full file; blocked calls may simply not be logged.
- **Zero-call sessions exist**: several calendar\_harvest and contact\_harvesting sessions have call\_count 0 (only started and ended events). They score as START to END, which is unseen in normal data. They look like generator failures or blocked sessions, not behaviour. Report results with and without them.
- **One run\_id for all sessions**, so grouping folds by run\_id is meaningless. The last record of the file is truncated, so the parser must tolerate a broken final line (already required in Sec. 3.2).

Consequence: fewer attack types are sequence-visible than Sec. 7.3 assumed, and the roughly 56% recall ceiling there is optimistic. Modest recall is an expected, reportable result, not a model defect.

**Step 0 (before modelling): profile the full file.** Report counts per category and attack\_type, the length distribution per category, the tool vocabulary, the number of zero-call sessions, and the bigram counts per label. Also compute the **exact-sequence overlap**: the share of adversarial sessions whose full tool-name sequence is identical to some normal session's sequence. That share is a hard ceiling on session-level recall for any sequence model, and it belongs in the report.

## 8. Worked example (usable as unit test)

Training on the two normal sample sessions (session 552b... with 6 calls, session 64b2... with 4 calls), order 1, variant A. Observed counts:

| State | Next | Count | p\_mle |
| --- | --- | --- | --- |
| `<START>` | find\_contact | 2 | 1.0 |
| find\_contact | get\_current\_datetime | 2 | 1.0 |
| get\_current\_datetime | get\_free\_slots | 2 | 1.0 |
| get\_free\_slots | tone\_checker | 1 | 0.5 |
| get\_free\_slots | save\_draft | 1 | 0.5 |
| tone\_checker | sensitive\_content\_scan | 1 | 1.0 |
| sensitive\_content\_scan | save\_draft | 1 | 1.0 |
| save\_draft | `<END>` | 2 | 1.0 |

Total transitions: 7 + 5 = 12. Scoring the adversarial sample session (f06c...: find\_contact, get\_current\_datetime, get\_free\_slots, get\_free\_slots, tone\_checker, sensitive\_content\_scan, save\_draft) must give exactly **one unseen transition**, `get_free_slots -> get_free_slots` (a repeated call), and it should score higher than both training sessions. Note that this session's real attack (`unsafe_args`, a card number in the arguments) is invisible to a tool-name-only model; only the structural side effect (the repeated call) is detected. See Sec. 10.

## 9. Implementation guidance

**Suggested structure**

All code lives in a new top-level folder `b3-markov-chain/`, laid out like `b1-binary-classifier/`: the same files and the same layers (`domain/` holds pure logic, `adapters/` holds I/O, `main.py` trains). From v0.3 there is no `scorer.py`: live scoring is done by the stream pipeline (Sec. 14).

```
b3-markov-chain/
├── .dockerignore          # .venv/, .pytest_cache/, **/__pycache__/, tests/, models/
├── .gitignore             # /models/
├── Dockerfile
├── README.md              # owner, status, data, model, results, run, next (B1 headings)
├── pyproject.toml         # package b3-markov-chain; extras: db, kafka, test
├── uv.lock
├── src/b3_markov/
│   ├── __init__.py
│   ├── main.py            # CLI: load sessions, fit, calibrate, evaluate, save, announce
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── sessions.py    # FinishedSession, grouping of batch events (Sec. 3.2)
│   │   ├── sequences.py   # tool-name sequence, <START>/<END>/<UNK> padding, order-K states (Sec. 4.1)
│   │   ├── training.py    # counts, smoothing, CV session + call thresholds, metrics (Secs. 4.2, 4.3, 7, 14.3)
│   │   ├── scoring.py     # step(), NLL, n_unseen, min_p, worst transition (Secs. 6, 14.3)
│   │   └── arguments.py   # flags, featurizer, emission model (Sec. 13)
│   └── adapters/
│       ├── __init__.py
│       ├── dataset.py     # dataset files and analytics_db -> sessions
│       └── model_store.py # save/load transition table, announce on model-updates
└── tests/
    ├── test_sessions.py
    ├── test_sequences.py
    ├── test_training.py
    ├── test_scoring.py
    └── test_model_store.py
```

The former `parse.py`, `model.py`, `score.py`, `evaluate.py` and `config.yaml` are replaced by this layout. Like B1, there is no config file: options are CLI flags and environment variables.

**Data access (same as B1).** `--source dataset` (default) reads `dataset/agent_b/events/events_for_<file>` and `dataset/agent_b/labels/labels_for_<file>` (default file `scenario_01_500.jsonl`) from `--dataset-dir`, env `DATASET_DIR`, default `REPO_DATASET`, computed with the same expression as in B1's `main.py` (valid because `b3-markov-chain/` sits at the same depth as `b1-binary-classifier/`). `--source db` reads `analytics_db.agent_events` and `analytics_db.labels` with B1's two SQL queries, connection string in env `ANALYTICS_DB`. `adapters/dataset.py` returns one record per session: session\_id, tool names in `session_call_index` order, category, attack\_type and the behaviour label from the labels file. Sessions without calls are kept.

**Which sessions are normal.** Dataset source: `category == "normal"` in `session.started` (the rule of Sec. 3.3). Database source: newest reviewer verdict is not `attack`, mirroring B1 (an assumption to confirm). Option `--normal-by label` trains on the behaviour label "compliant" instead. Both columns are written to `metrics.json`, because B1's README reports 459 of 500 sessions as violating by behaviour, so many sessions with category normal may break rules (Sec. 7.4).

**CLI (`python -m b3_markov.main`).** `--source dataset|db`, `--scenarios`, `--dataset-dir`, `--orders` (default 1 2), `--smoothing additive|floor|backoff` (default additive), `--alpha`, `--epsilon`, `--percentile` (default 99), `--folds` (default 10), `--seed` (default 0), `--normal-by category|label`, `--models-dir` (env `MODELS_DIR`, default `models`), `--announce`. Other environment: `ANALYTICS_DB`, `KAFKA_BOOTSTRAP` (default `localhost:29092`).

**Output.** `models/b3-markov-chain/<UTC time>_<smoothing>/transition_table.json` (the schema of Sec. 5) and `metrics.json` (CV scores, threshold and, where labels exist, ROC-AUC, PR-AUC and recall per attack type from Sec. 7). The version string `<UTC time>_<smoothing>` plays the role of B1's `<time>_<model>`.

**Docker (same as B1).** Dependencies: `scikit-learn` for fold splits and AUC, no `joblib` (the model is JSON). Extras `db` (`psycopg[binary]`), `kafka` (`confluent-kafka`), `test` (`pytest`).

```
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[db,kafka]"
CMD ["python", "-m", "b3_markov.main", "--source", "db", "--announce"]
```

**Publishing to model-updates.** With `--announce`, `model_store.announce()` sends one message to topic `model-updates` with key = model name `b3-markov-chain` (constant `MODEL_NAME`), using B1's envelope:

```
{"schema_version": "1.0", "event_id": "<uuid>", "event_type": "model.trained",
 "occurred_at": "<ISO-8601 UTC>",
 "data": {"model": "b3-markov-chain", "version": "<UTC time>_additive",
          "path": "<models folder>", "metrics": {...},
          "transition_table": {...contents of transition_table.json...}}}
```

The table is embedded because it is this model's output, so consumers need no access to the models folder. As with B1, the exact message belongs to B4 and may change.

**Live scoring (moved out in v0.3).** The former `scorer.py` (consumer of `tool-calls.B` and `model-updates`, publisher of `anomaly.scored` with detector `b3_markov`) is removed from this spec. Live events, including the session score of Secs. 6 and 13.4, are scored by the stream pipeline in [Spec: Real-Time Markov Order Check for Tool-Call Streams](https://claude.ai/artifact/CmhxLxENDtDCbT4eSCnM34), which publishes with detector `markov`. This pipeline's only Kafka output is the `model.trained` message above. See Sec. 14.

**Tests (minimum)**

1. `test_sequences`: padding with `<START>` and `<END>`, order-K states, unknown tool maps to `<UNK>`, empty session gives START to END.
2. `test_training`: the worked example in Sec. 8 reproduces the counts exactly (12 transitions); with additive smoothing every row sums to 1 (within 1e-9) over V\_next; floor mode uses epsilon for unseen transitions; a context never seen in training gets the uniform distribution.
3. `test_training`: only sessions that count as normal are used (an adversarial session never changes counts); duplicate events do not change counts.
4. `test_sessions` (carried over from B1): calls come back in `session_call_index` order, a session without a start is skipped, a session without calls is still returned.
5. `test_scoring`: an unseen transition raises `n_unseen`; an out-of-vocabulary tool gives a finite NLL (additive) or epsilon (floor); a session equal to a training session scores lower than one with a new transition.
6. `test_model_store`: save then load scores identically; `announce()` with a fake producer sends to `model-updates` with key `b3-markov-chain` and the table in `data.transition_table`.
7. `test_scorer` is removed in v0.3 (moved to the stream pipeline, stream spec Sec. 10.4); the v0.3 tests are listed in Sec. 14.5.

**Acceptance criteria:** `pytest` passes; output is deterministic for fixed input and seed; `transition_table.json` validates against the schema in Sec. 5; `metrics.json` and the README table cover all configurations in Sec. 7.2; `docker build` then running the image with the default command publishes exactly one message to `model-updates` with key `b3-markov-chain`.

## 10. Limitations and possible extensions

- Moderate data: about 269 normal sessions (at most about 2,700 calls) support orders 1 and 2 with smoothing, but order 3 is sparse, and a 99th-percentile threshold rests on only about 3 tail sessions. State this in the report.
- Markov and time-homogeneity assumptions (paper Eq. 3-4): behaviour is assumed to depend only on the last K calls and not on position in the session or wall-clock time.
- Argument-level attacks (e.g. `unsafe_args`) are out of scope by decision. The model sees only tool names (and optionally the success flag), so it can catch such sessions only through structural side effects such as repeated calls. Expect low recall for attacks that change only arguments, and report it per `attack_type`. Timing features such as `time_since_previous_call_ms` are likewise excluded in v0.1.
- Success flag: dropped in v0.1 because no normal session contains a failed call. Adversarial sessions with failed calls are scored on tool names only.

## 11. Decisions and open questions

1. **Decided:** about 269 normal sessions, at most 10 calls each. Orders 1 and 2 are primary, order 3 is exploratory, and thresholds come from 10-fold cross-validation.
2. **Decided:** detection at session level; prefix (online) scoring is not required here; from v0.3 the separate stream pipeline adds call-level online checks (Sec. 14).
3. **Decided:** no argument-level features. Four of nine attack types are then invisible (Sec. 7.3).
4. **Decided:** 231 adversarial sessions, 9 attack types; no failed calls in normal data, so the success flag is dropped.
5. **Open:** how many adversarial sessions per attack type? Balanced counts make the roughly 56% recall ceiling in Sec. 7.3 exact; skewed counts change it.
6. **Answered by the data (Sec. 7.4):** many normal sessions skip tone\_checker and sensitive\_content\_scan, so the sample session 64b2... is not a mislabel. As a result, `skipped_check` sessions with the same 4-call sequence are indistinguishable from normal. Still worth doing: run every normal session through the attack-table rules and report violations, so the report states that normal data themselves violate `precondition_missing`.
7. **Decided:** code layout follows `b1-binary-classifier` in a folder `b3-markov-chain/` (Sec. 9). Options stay as CLI flags and environment variables, not a config file; every run writes its full parameters into `metrics.json` for reproducibility.
8. **Decided:** sessions count as normal by `category == "normal"` (dataset) or by a reviewer verdict other than `attack` (database); `--normal-by label` is an option.
9. **Decided:** the transition table is embedded in the `model-updates` message, key `b3-markov-chain`.

## 12. References

- W. Sha, Y. Zhu, M. Chen, T. Huang, "Statistical Learning for Anomaly Detection in Cloud Server Systems: A Multi-Order Markov Chain Framework," IEEE Trans. Cloud Computing, vol. 6, no. 2, 2018.
- N. Ye, "A Markov Chain Model of Temporal Behavior for Anomaly Detection," IEEE SMC Workshop on Information Assurance and Security, 2000.
- N. Ye, Y. Zhang, C. M. Borror, "Robustness of the Markov-Chain Model for Cyber-Attack Detection," IEEE Trans. Reliability 53(1), 2004.
- W.-H. Ju, Y. Vardi, "A Hybrid High-Order Markov Chain Model for Computer Intrusion Detection," J. Computational and Graphical Statistics 10(2), 2001.

Note: the Sha et al. paper and the first four items appear in its own reference list; Warrender et al. and Chen and Goodman were added from general knowledge, so verify the bibliographic details before citing.

## 13. Revision v0.2: argument features

### 13.1 Why

v0.1 used tool names only. On the 124 complete sessions of the partial dataset file (70 normal, 54 adversarial) it reached ROC-AUC 0.575 (95% bootstrap interval about 0.47 to 0.67), recall 13% at a 1.4% false-positive rate. The reason is structural: 36 of the 54 adversarial sessions have exactly the same tool sequence as some normal session, so no sequence-only model can flag them (Sec. 7.4 Step 0 profile). Inspecting the arguments of those sessions shows clear differences: recipient domains never seen in normal data (mailcollector.example, secure-mail.example), placeholder or malformed recipients, card numbers and passwords in text or confidential terms, injection strings (../../etc/passwd, DROP TABLE), impossible or far-away dates (2026-11-45, 2025-10-11, +25 days), and a draft body that differs from the text that was scanned. v0.2 therefore adds argument features while keeping the Markov chain as the core.

### 13.2 Model: Markov chain plus argument-class emissions

The sequence part of Secs. 4 to 6 is unchanged. Every call is additionally mapped to a few categorical argument flags (13.3), and a per-tool emission model gives the probability of those flags given the tool:

- P(session) = P(tool sequence) from the Markov chain times the product over calls and flags of P(flag value | tool).
- Emissions are estimated by counting on normal sessions only, with additive smoothing: P(v | tool, flag) = (count + a) / (N + a \* V), where V is the number of values the flag can take and a = arg\_alpha (default 0.1). A value never seen in training gets a small but nonzero probability (about 0.0015 with 70 calls).
- Flags are treated as conditionally independent given the tool (naive Bayes). This keeps the table small and lets unseen combinations of seen values score normally. The argument classes, not raw strings, are modelled, so no free text enters the table.
- The transition table of Sec. 5 is not changed; an optional arguments block and a scoring block are added (13.6).

### 13.3 Argument flags

| Tool | Flag | Values | Rule |
| --- | --- | --- | --- |
| find\_contact | name\_kind | person, email, domain, missing | contains @: email; no spaces and dotted: domain; else person |
| get\_free\_slots | date\_kind | ok, invalid, out\_of\_window, missing | not a valid ISO date: invalid; days from the call's occurred\_at date outside the window learned on training data (min and max delta, widened by date\_slack\_days, default 3): out\_of\_window |
| tone\_checker | content | clean, secret, injection | pattern match on the draft |
| sensitive\_content\_scan | terms\_kind | empty, benign, placeholder, email, secret, injection | worst class among extra\_confidential\_terms (order: injection, secret, email, placeholder, benign) |
| sensitive\_content\_scan | content | clean, secret, injection | pattern match on text |
| sensitive\_content\_scan | text\_vs\_checked | same, changed, unchecked | text equals the last tone\_checker draft, differs, or no earlier tone\_checker call |
| save\_draft | to\_kind | known, rare\_domain, unseen\_domain, malformed, placeholder | not an e-mail address: malformed; in brackets: placeholder; domain seen at least min\_domain\_count times in training recipients (default 2): known; seen once: rare\_domain; never seen: unseen\_domain |
| save\_draft | content | clean, secret, injection | pattern match on subject and body |
| save\_draft | body\_vs\_checked | same, changed, unchecked | body equals the last scanned text (or last tone draft); differs (post-check tamper); nothing checked before |

Any absent argument gives the value missing, or clean and unchecked where that applies. Text arguments are read under any of their usual names (text, draft, body: the real dataset sends text to sensitive\_content\_scan, the mock agents send draft), and texts are compared after collapsing whitespace; if either text is absent the consistency flag is unchecked, never changed. Patterns: secret = password, passwd, card number, credit card, cvv, ssn, api key, token, iban, 16-digit groups, or a letters-plus-digits password-like string; injection = ../, SQL comment or DROP TABLE, UNION SELECT, script tags, backticks, /etc/passwd. These lexicons are prior knowledge, not learned, and must be listed in the report.

Tried and dropped: duration\_ms, time\_since\_previous\_call\_ms, requested\_tone, style\_profile and body length. In the data they show no separation between normal and adversarial sessions and would only add false alarms. Timing remains out of scope.

### 13.4 Scoring

Per session, all components are reported: seq (mean NLL per transition of the chain, as in Sec. 6), arg\_total (sum over calls of the flag NLLs), arg\_max (the worst single call), the worst flag as text, and these combined scores:

- joint = (sequence total NLL + arg\_total) / (n\_calls + 1): mean NLL per transition of the full model. This is the default and the primary score, chosen a priori because it is the likelihood of the complete model.
- joint\_max = seq mean NLL + arg\_max: emphasises one very unlikely call; mean scores dilute a single bad argument in a long session.
- seq and args (arg\_max alone) are ablations.

The threshold is calibrated exactly as in Sec. 7.1 (10-fold held-out normal scores, 99th percentile) on the chosen score, with the featurizer (known domains, date window) refitted inside every fold so that no held-out session leaks into its own features.

### 13.5 Evaluation changes

- The protocol of Sec. 7.2 is kept: adversarial sessions are never used for fitting, thresholds or choosing the default score.
- metrics.json adds an ablation block (seq, args, joint, joint\_max, each per order) and keeps the baselines of v0.1. All score variants are shown so the choice is checkable; since the variants are compared on the evaluation sessions, the best variant is optimistic and the default stays joint.
- Report the per-attack-type recall, now expected to be high for the argument-visible types (recipient\_hijack, unsafe\_args, invalid\_date, post\_check\_tamper, contact\_harvesting) and still limited for those that differ only by call count or timing (calendar\_harvest, draft\_flooding, parts of skipped\_check).
- Report what remains undetectable: sessions whose tool sequence and argument flags are both identical to a normal session (extend the Step 0 overlap count to the flagged alphabet).

### 13.6 Table and message changes

spec\_version becomes 0.2. The JSON gets two optional blocks: arguments = {featurizer: {known\_domains (domain to count), min\_domain\_count, date\_window\_days, date\_slack\_days}, emission: {alpha, tools: {tool: {flag: {n, counts}}}}} and scoring = {score: joint | joint\_max | seq | args}. A v0.1 file (no arguments block) loads as a sequence-only model. calibration.threshold is per order and refers to the configured score. The model-updates message embeds the same table. anomaly.scored keeps score = the configured score and adds seq\_score, arg\_score and worst\_arg to data (from v0.3 published by S08 as extension fields inside data of S04's anomaly.scored envelope; see Sec. 14.2).

### 13.7 Implementation changes (supersedes parts of Sec. 9)

- Sessions carry calls (tool, arguments, occurred\_at) next to tools; the stream buffer keeps arguments and the event timestamp. The database query also selects the event's occurred\_at (assumption: agent\_events has that column, to confirm).
- New module domain/arguments.py (flags, featurizer, emission model); scoring.py gets a Detector that combines the chain and the emissions; training.py fits and evaluates the detector.
- New CLI flags: --no-arguments (v0.1 behaviour), --score joint|joint\_max|seq|args, --arg-alpha, --min-domain-count, --date-slack-days.
- Dependencies: none at run time (the earlier scikit-learn note in Sec. 9 is superseded; fold splitting and AUC are implemented in pure Python).
- Extra tests: flag rules per tool and value; featurizer fitted on training only; emission rows sum to 1; unseen flag value is unlikely; post-check tamper gives body\_vs\_checked changed; detector table round trip and v0.1 compatibility; a held-out normal session with an unknown domain is not a training leak; the stream pipeline's session event carries the new fields (tested there, Sec. 14).

### 13.8 Limitations of v0.2

- The secret and injection lexicons and the flag design come from inspecting the attack types, so results on those types are partly in-sample knowledge; a new attack style that avoids these patterns would not be flagged. Say so in the report.
- With about 70 to 269 normal sessions, rare legitimate recipients (for example a one-off partner domain) become false alarms; min\_domain\_count trades this off.
- Naive Bayes ignores correlations between flags and between neighbouring calls; an order-1 dependency of flags on the previous call is a possible extension.
- The data come from one scripted generator; real agent traffic will have more varied arguments.

## 14. Revision v0.3: live scoring moves to the stream pipeline

### 14.1 Why

Up to v0.2 this spec had two jobs: learn the model from history (batch) and score live events from `tool-calls.B` (stream, `scorer.py`). A separate stream mining pipeline now checks the order of live calls against this model, specified in [Spec: Real-Time Markov Order Check for Tool-Call Streams](https://claude.ai/artifact/CmhxLxENDtDCbT4eSCnM34). Keeping both scorers would mean two services consuming the same model and events and publishing scores for the same sessions under two detector names, so downstream consumers would count each session twice, and two copies of the streaming code would have to be kept in step. v0.3 therefore narrows this spec to the batch layer: learn, calibrate, evaluate, announce. All live scoring, including the session score of Secs. 6 and 13.4, is done by the stream pipeline, which publishes it with detector `markov`. This is the batch-layer / speed-layer split of the Lambda architecture (Kiran et al. 2015). The transition table and the `model.trained` message are the contract between the two.

### 14.2 Removed

- `scorer.py`, `events.py` (the `anomaly.scored` builder) and `test_scorer.py`; the streaming `SessionBuffer` in `domain/sessions.py` (the batch grouping of Sec. 3.2 stays).
- Environment variables `B3_INPUT_TOPICS`, `B3_MODELS_DIR`, `B3_MODEL_KIND`.
- Superseded wording: the last sentence of Sec. 13.6 (the `anomaly.scored` fields `seq_score`, `arg_score`, `worst_arg` are now published by the stream pipeline under detector `markov`, as extension fields inside data of the anomaly.scored envelope that S04 (Online Forest) publishes, whose shared core is scored\_event\_id, agent\_id, detector, model\_version and score (S08 Sec. 7)), and in Sec. 13.7 the note that "the stream buffer keeps arguments and the event timestamp" (now a requirement of the stream pipeline).

### 14.3 Added

- **Call-level threshold.** The stream pipeline flags a single call as `out_of_order` when the log-probability of its transition falls below a threshold. That threshold is calibrated here, because only the batch side has the held-out normal scores. In the same 10-fold CV as Sec. 7.1, compute for each held-out normal session `m(s) = min over t of ln p(x_t | state_t)` over all T+1 transitions. Then `call_threshold[K]` = the (100 - p)-th percentile of the held-out `m(s)`, with the same p as the session threshold (default 99, so the 1st percentile). A session raises at least one call alert exactly when `m(s) < call_threshold`, so this controls the per-session false-alarm rate of the call check at about 1%, a split-conformal argument (Laxhammar and Falkman 2015; stream spec Sec. 6).
- **metrics.json additions.** Per normal session: held-out `m(s)`. The false-alarm rate of the call check, of the session threshold and of their union (CV). Per attack type: share of adversarial sessions with `m(s) < call_threshold`, and the index of the first call below it. This is an offline preview of the stream pipeline's call-level recall and earliness.
- **Step function.** `domain/scoring.py` exposes `step(table, order, context, symbol) -> (lp, count, state_total)`, and whole-session scoring is rewritten as a fold over `step`, so batch and stream share one code path. `domain/arguments.py` featurizes one call given an argument context (last tone draft, last scanned text). The stream pipeline imports these modules; it never copies them.
- **Agents.** The `model.trained` message gets `data.agents`, the agents whose traffic the model was trained on (CLI `--agents`, default `B`). The stream pipeline applies a model only to those agents.
- **Fold models.** `--save-fold-models` writes the ten CV fold tables to `models/b3-markov-chain/<version>/folds/fold_<i>.json`, so the stream replay can score each normal session with a model that never saw it.
- `spec_version` becomes 0.3. A 0.2 table (no `call_threshold`) still loads; the stream pipeline then falls back to flagging unseen transitions.

### 14.4 Calibration block (v0.3)

```json
"calibration": {
  "method": "kfold-10",
  "score": "joint",
  "percentile": 99,
  "threshold": {"1": 3.12, "2": 2.87},
  "call_threshold": {"1": -6.05, "2": -5.92},
  "call_statistic": "min_log_p_per_session"
}
```

The numbers are placeholders. `threshold` is the session threshold of Sec. 7.1 on the configured score (higher means more anomalous); `call_threshold` is a log-probability (lower means more anomalous).

### 14.5 Tests (v0.3)

- `test_training`: `call_threshold` equals the (100 - p)-th percentile of the held-out `m(s)`; adversarial sessions never change it.
- `test_scoring`: folding `step` over a session gives exactly the whole-session NLL of Sec. 6; `m(s)` equals the minimum of the step log-probabilities; the worked example of Sec. 8 gives the expected minimum.
- `test_model_store`: `announce()` includes `data.agents` and `calibration.call_threshold`; a v0.2 table without `call_threshold` loads.
- `--save-fold-models` writes ten tables, and none of them counts a session from its own fold.

### 14.6 Acceptance criteria (v0.3)

Unchanged from Sec. 9, plus: no module of this package consumes a Kafka topic or publishes to `scores`; the parity test of the stream spec (Sec. 10.4) passes against this package's `scoring.py`.

### 14.7 Decisions

- Decided: live scoring (call-level checks and session score) lives only in the stream pipeline; detector `b3_markov` is retired in favour of `markov`.
- Decided: thresholds for both checks come from this pipeline's cross-validation; the stream pipeline never fits or calibrates anything.
- Decided: the model is never updated from live traffic (poisoning risk, Rubinstein et al. 2009); retraining goes through this pipeline.

References added in v0.3 (full entries in the stream spec, Sec. 12): M. Kiran, P. Murphy, I. Monga, J. Dugan, S. S. Baveja, "Lambda Architecture for Cost-Effective Batch and Speed Big Data Processing," IEEE Big Data 2015; R. Laxhammar, G. Falkman, "Inductive Conformal Anomaly Detection for Sequential Detection of Anomalous Sub-Trajectories," Annals of Mathematics and Artificial Intelligence 74(1–2), 2015; B. I. P. Rubinstein et al., "ANTIDOTE: Understanding and Defending against Poisoning of Anomaly Detectors," ACM IMC 2009.

## 15. Revision v0.4: one model per agent, and Agent A

### 15.1 Why

The stream pipeline (S08, [Spec: Real-Time Markov Order Check for Tool-Call Streams](https://claude.ai/artifact/CmhxLxENDtDCbT4eSCnM34)) scores both `tool-calls.A` and `tool-calls.B`. Agent A uses different tools from Agent B, so a model learned from Agent B cannot score it. v0.4 trains one model per agent from that agent's own data.

### 15.2 Per-agent models (supersedes the "Agents" item of Sec. 14.3)

- New CLI flag `--agent A|B` (default `B`). One run trains one agent's model.
- Output goes to `models/b3-markov-chain/<agent>/<version>/`.
- The `model.trained` message is keyed `b3-markov-chain.<agent>` (constant `MODEL_NAME` plus the agent) and carries `data.agent`. A compacted `model-updates` topic then keeps the newest model of each agent; with a single key, a new B model would hide the A model. This replaces the `data.agents` list of Sec. 14.3.
- `tool_call.failed` events count as calls for both agents (Secs. 3.1 and 3.2 listed only `tool_call.completed`). The state stays tool-name only (Sec. 4.1), so a failed call and a successful call of the same tool are the same symbol.

### 15.3 Agent A data and adapter

Agent A's recorded dataset is a JSONL file of wrapped records. Each line has `source`, `agent` (`datalens`), `case_id`, `scenario`, `category`, `attack_type`, an observed-behaviour `label` and `label_version`, `label_evidence_event_ids`, `policy_denied_event_ids`, and the event itself under `event`. The events use payload `agent-run-events-v2`, which differs from the flat live envelope:

- The tool name is in `tool_call.requested` as `data.name`, with `data.kind`, `data.features` and `data.arguments_sha256`; the clear arguments are not recorded.
- `tool_call.completed` / `tool_call.failed` carry only `status`, a `reason` for failures and the policy evaluation, joined to the request by `tool_call_id`.
- A request for a tool that does not exist has no `name` and `kind = unknown`; the runtime fails it with reason `unknown_tool`.
- `model_call.completed` / `model_call.failed` events are interleaved.

`adapters/dataset.py` gets an Agent A reader (`--dataset-file`) that unwraps `event`, joins each request with its result by `tool_call_id`, orders calls by `session_call_index`, maps a missing name to `<UNK>`, counts failed calls, ignores `model_call.*`, and takes the session label from the wrapper's `category`. The stream pipeline parses the same payload (S08 Sec. 3.1), so batch and stream see the same sequence.

### 15.4 Profile of the recorded file (Step 0 for Agent A)

Computed on the file provided on 22 Nov 2026 (999 records):

- 130 sessions, each with its own `run_id`: 73 `normal` and 57 `prompt_injected` (attack type `direct_prompt_injection`).
- 0 to 3 tool calls per session; 237 calls in total. Named tools: `aggregate_statistics` (85), `finalize_statistics` (55), `inspect_dataset` (39), `request_clarification` (24), `correlate_columns` (15), `describe_columns` (3). Plus 16 calls to tools that do not exist, 13 of them in normal sessions.
- 20 failed calls: 16 `unknown_tool`, 3 `execution_result`, 1 `policy_denied` (in a prompt-injected session).
- Normal training data: 143 calls, 216 padded transitions, 27 distinct transitions.
- **Exact-sequence overlap:** 51 of 57 prompt-injected sessions have a tool-name sequence identical to some normal session's. Session-level recall of any sequence-only model is therefore at most 6 of 57 (about 11%). Four of the 6 have no tool call at all.
- Behaviour labels: `tool_trace_allowed` 53, `insufficient_evidence` 47, `model_failure` 28, `policy_blocked` 1, `answer_violation` 1. There are no per-rule `violated_rules` as in Agent B's labels.

### 15.5 Agent A model settings

- **Training filter:** `category == "normal"` from the wrapper (73 sessions). As a sensitivity check, also train without the 13 normal sessions labelled `model_failure` and report the difference.
- **Sequence only:** the clear arguments are not recorded, so `--no-arguments` is forced for Agent A, and the score is `seq`. The `features` (`operation`, `method`, `column_count`, `dataset_selection`) are a candidate argument alphabet for a later version.
- **Order:** K = 1 primary. With 216 transitions, order 2 contexts would be almost all unseen; report it as exploratory only.
- **Percentile:** default 95 for Agent A (`--percentile` per run). With 73 sessions, the 99th percentile is effectively the single largest held-out score, so it cannot be estimated. Report 90 and 99 as sensitivity checks, and the implied false-alarm rate with a bootstrap interval.
- **Smoothing:** additive, alpha tuned by 10-fold CV as in Sec. 4.3; with so few transitions, smoothing dominates for rare contexts, so report alpha sensitivity.
- **Fixed vocabulary:** Agent A's toolset is `statistics-tools-v1`. It has four numerical tools defined in the agent's `tools/` folder (`inspect_dataset`, `describe_columns`, `aggregate_statistics`, `correlate_columns`) and two control tools recorded with `kind = control` (`finalize_statistics`, `request_clarification`). New flag `--vocabulary` (comma-separated) fixes V to this declared list instead of the tools seen in training. All six do appear in the 73 normal sessions, so today the result is the same. The fixed list keeps |V\_next| and the smoothing stable across retrains, and gives a tool that is declared but unseen a smoothed probability instead of `<UNK>`. Rarity warning: `describe_columns` occurs once in the normal sessions, so its outgoing row is mostly smoothing; report its transitions separately.

### 15.6 Agent A evaluation

As Sec. 7, with the 57 prompt-injected sessions as positives: ROC-AUC, PR-AUC, recall at the calibrated threshold, plus recall per behaviour label. State the 6-of-57 ceiling next to every recall figure; a low recall is the expected, reportable result, because these injections mostly change what the agent says or computes, not which tools it calls in which order. S08's replay adds earliness and the overlap with S07.

### 15.7 Tests (v0.4)

- Agent A reader: a requested/completed pair gives one call with the requested name; an unnamed request gives `<UNK>`; a failed call is kept; `model_call.*` is ignored; the wrapper's `category` becomes the session label.
- Agent B reader: a `tool_call.failed` event is kept as a call.
- `test_model_store`: `announce()` uses key `b3-markov-chain.<agent>` and sets `data.agent`; models of A and B are written to separate folders.
- `--no-arguments` is enforced for `--agent A`.

### 15.8 Open

- Resolved: Agent A's tool list. The `tools/` folder of `datalens-agent` defines the four numerical tools; the executor fails any other name with `unknown_tool`. With the two control tools, all six appear in the recorded normal sessions, so no legitimate tool is missing from training.
- The example live `tool-calls.A` message passes `correlate_columns` a `columns` list and `dataset_id: "ds-21"`, but the tool's argument schema uses `x_column` / `y_column` and a UUID `dataset_id`, validated strictly. Confirm which format live Agent A sends before building argument features for it.
- If live `tool-calls.A` carries clear arguments, an argument part for Agent A's model can be added once a recorded dataset with clear arguments exists.
