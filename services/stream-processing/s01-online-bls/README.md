# S01: Online-BLS online classifier

**Owner** Maxim · **Pipeline** P2 (ML classification)

## Paper

Chunyu Lei, Guang-Ze Chen, C. L. Philip Chen, and Tong Zhang. *An accurate and efficient online broad learning system for data stream classification*. Science China Information Sciences, 69 (2026), article 139101. [Published paper](https://doi.org/10.1007/s11432-025-4673-5) · [Open preprint, §3 and Algorithm 1](https://arxiv.org/html/2501.16932v1#S3).

## What can we tell from the calls seen so far?

S01 estimates the reviewed session class after each completed or failed tool call. Agent A and Agent B have separate model weights because their tools differ.

1. Agent A calls `inspect`. A fresh model emits risk `0.5` with `ready: false`.
2. The same session calls `aggregate`. The next prediction uses both calls. S01 saves that prediction and its features as the final prefix when the session ends.
3. A review verdict arrives later. S01 checks the saved class against the verdict if the model was ready, then trains once using the saved features and the current weights. If feedback arrives before the session ends, S01 waits for the end. Duplicate verdicts for the same session leave the weights unchanged.

## How Online-BLS learns

S01 implements the base Online-BLS update from Algorithm 1. The weights for both class outputs start at zero. The model keeps a Cholesky factor of the ridge-regularized feature matrix so it can learn from one new labeled example at a time.

1. **Build features (§3.2).** The current and previous tool buckets, prefix length, recent repetitions, failure fraction, and argument count form the input. A fixed linear map yields 16 features. A second map applies `tanh` to produce 16 enhancement features. The combined 32-element vector is `a`.
2. **Predict (§3.2).** Multiply `a` by the current weight matrix `W` to obtain two class scores. S01 uses the attack score minus the normal score as its classification margin.
3. **Update (§§3.3–3.4).** When the session verdict is available, encode it as a one-hot vector `y`. Add the new sample's contribution `a aᵀ` to the regularized feature matrix by updating its Cholesky factor with Givens rotations. Compute the weight correction from the outer product of `a` and the prediction residual `y − Wᵀa`. Two triangular solves give the correction to add to `W`, reusing the updated factor.

ATGM adapts the paper's test-then-train loop to delayed labels. The service saves the final prefix and its original prediction. When the verdict arrives, it evaluates that original prediction and computes the training residual using the current weights. [Model implementation](src/online_bls/domain/model.py) · [Session and label handling](src/online_bls/service.py).

The replay tests cover delayed feedback, duplicate delivery and recovery. The numerical test compares each update to a batch ridge solution.

## Kafka contract

| Direction | Topics | Contract |
|---|---|---|
| Read | `tool-calls.A`, `tool-calls.B` | One prediction per `tool_call.completed` or `tool_call.failed`, ordered by `data.session_call_index`. `session.ended` marks the final prefix. |
| Read | `labels` | `review.labelled` joins on agent and session. `false_alarm` maps to class `0`, `attack` to class `1`. |
| Write | `scores` | `anomaly.scored` keyed by agent ID. `scored_event_id` identifies the original call, `detector` is `online_bls`, and `model_version` is `bls-1`. |
| Write | `classifier-errors` | One `classifier.error` per reviewed session whose final prediction was ready. `data.error` is 0 for correct and 1 for incorrect. S02 consumes this result. |

`data.score` is a risk score in `[0, 1]`, with higher values meaning more suspicious. It is the output margin transformed by `(1 + tanh(margin)) / 2`. The class is `1` for margins above zero and `0` otherwise. Use the score for ranking rather than probability estimates. `data.ready` becomes true after the agent model has learned both classes. S01 computes the error from the saved pre-label prediction and commits it to the outbox alongside the training update.

Parallel tool calls can finish out of order. S01 holds later calls until earlier indexes arrive, or scores all available calls in index order when `session.ended` arrives. Consumers ordering scores within a session should use `data.session_call_index`. The envelope's `sequence` identifies the source event's position in the producer stream.

## Run and verify

From the ATGM root with its Compose environment configured:

```text
docker compose up -d --build online-bls
docker compose logs -f online-bls
```

From this stage folder:

```text
python -m pip install -e ".[test]"
python -m pytest -q
```

`KAFKA_BOOTSTRAP` defaults to `localhost:29092`, `ONLINE_BLS_GROUP_ID` to `online-bls` and `ONLINE_BLS_STATE` to `online-bls.sqlite3`. Run one replica. Keep the state volume paired with its Kafka group across restarts. SQLite stores the model, one checkpoint per observed session and scores awaiting broker acknowledgement. Session checkpoints grow with the number of distinct sessions. Broker delivery is at least once, so consumers can deduplicate using the stable score event ID.
