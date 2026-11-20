# S01: Online-BLS online classifier

**Owner** Maxim · **Pipeline** P2 (ML classification)

## What can we tell from the calls seen so far?

S01 estimates the reviewed session class after each completed or failed tool call. Agent A and Agent B have separate model weights because their tools differ.

1. Agent A calls `inspect`. A fresh model emits risk `0.5` with `ready: false`.
2. The same session calls `aggregate`. The next prediction uses both calls. S01 saves that prediction and its features as the final prefix when the session ends.
3. A review verdict arrives later. S01 checks the saved class against the verdict if the model was ready, then trains once using the saved features and the current weights. If feedback arrives before the session ends, S01 waits for the end. Duplicate verdicts for the same session leave the weights unchanged.

## How Online-BLS learns

The prefix vector uses the current and previous tool buckets, prefix length, recent repetitions of the same tool, failure fraction and current argument count. The model projects this vector into 16 linear and 16 nonlinear features with a fixed seed. It learns two outputs from one-hot targets. Algorithm 1 updates the Cholesky factor with Givens rotations, then uses two triangular solves to adjust the output weights. [Lei et al., Online-BLS, *Science China Information Sciences*, 2026](https://doi.org/10.1007/s11432-025-4673-5) · [Author preprint, Algorithm 1](https://arxiv.org/html/2501.16932v1#S3).

The replay tests cover delayed feedback, duplicate delivery and recovery. The numerical test compares each update to a batch ridge solution.

## Kafka contract

| Direction | Topics | Contract |
|---|---|---|
| Read | `tool-calls.A`, `tool-calls.B` | One prediction per `tool_call.completed` or `tool_call.failed`, ordered by `data.session_call_index`. `session.ended` marks the final prefix. |
| Read | `labels` | `review.labelled` joins on agent and session. `false_alarm` maps to class `0`, `attack` to class `1`. |
| Write | `scores` | `anomaly.scored` keyed by agent ID. `scored_event_id` identifies the original call, `detector` is `online_bls`, and `model_version` is `bls-1`. |

`data.score` is a risk score in `[0, 1]`, with higher values meaning more suspicious. It is the output margin transformed by `(1 + tanh(margin)) / 2`. The class is `1` for margins above zero and `0` otherwise. Use the score for ranking rather than probability estimates. `data.ready` becomes true after the agent model has learned both classes. S02 can use `predicted_class`, `ready` and `session_call_index` to select the final pre-label prediction for error monitoring.

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
