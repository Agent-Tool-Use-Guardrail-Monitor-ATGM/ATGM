# Spec: Real-Time Markov Order Check for Tool-Call Streams

Data science master's course project · stream mining companion to the B3 batch spec · v0.2 · Nov 22, 2026 · @Agnes

**S08: Markov order check**

**Pipeline:** real-time sequence-order check of each tool call against a learned, per-agent Markov model of normal tool order.

**Vulnerability:** agent goal hijack through prompt injection (direct, or hidden in tool-returned content), which makes the agent use legitimate tools in an order its normal workflow does not follow: jumping to an action, skipping a step, looping. \[1\] \[2\]

**Mitigation:** score every tool call against the model as it happens, flag improbable transitions as `out_of_order`, and publish a calibrated session score, so the deviation is visible before the session ends. It complements S07, which enforces explicit rules; S08 catches the deviations nobody wrote a rule for. \[3\] \[4\]

**Citations:**

- &#91;1\] [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), 2025: ASI01 Agent Goal Hijack, ASI02 Tool Misuse and Exploitation
- &#91;2\] Liu et al., [TraceAegis](https://arxiv.org/abs/2510.11203), 2025 (execution order disturbance as a structural anomaly)
- &#91;3\] Du et al., DeepLog, ACM CCS 2017 (online next-event check against a learned model)
- &#91;4\] Sha et al., multi-order Markov chain anomaly detection, IEEE Trans. Cloud Computing 2018 (the B3 model)

Owner: Agnes

## 1. Purpose and scope

Score live tool-call events from Agent A and Agent B against the learned B3 Markov model of each agent while the session is still running, and raise an alert as soon as a call breaks the learned order. The batch pipeline (B3, separate spec) learns one model per agent offline and announces it. This pipeline is its serving side: it reads the models from `model-updates` and applies them, one event at a time, to `tool-calls.A` and `tool-calls.B`. It publishes `anomaly.scored` events to `scores` under two detector names: `markov_order` for call-level alerts and `markov` for session scores (Sec. 7).

**What it flags:**

- `out_of_order`: a call (or the end of a session) whose transition from the last K calls is too improbable under the agent's model, using a threshold calibrated on normal data (Secs. 5.2 and 6).
- A **session score** at `session.ended`. This is the B3 score (B3 Sec. 13.4: sequence plus argument flags for Agent B, sequence only for Agent A), which until now was published by the batch spec's `scorer.py`. It moves here (Sec. 2).

For Agent A, call-level alerts are computed but not published by default: with its small training set they would be mostly false alarms. Its session scores are published (Sec. 6).

**Not flagged here:** calls to tools outside the agent's toolset. S07 (allow-list policy check) already flags them as `tool_not_allowed`, using the authoritative `toolset-config` (Sec. 5.1). Unknown tools still enter this pipeline's model as `<UNK>`.

**Stream mining constraints.** One pass over the events. Constant work per event. Memory bounded by the number of active sessions, not by stream length. Output within milliseconds of the triggering event. Correct results when events arrive late, twice or out of delivery order (Sec. 4).

**Out of scope:** updating the model from the stream (online learning, see Sec. 8.3); training models (B3 does that, per agent); rule-based policy checks such as the tool allow-list, required preconditions, call limits and argument rules (S07 does those); argument-level call alerts (only the session score uses arguments; see Sec. 11); and acting on alerts, for example blocking the agent.

## 2. Split of responsibilities with the batch pipeline

**Recommendation: move live scoring out of the batch spec into this pipeline.** The B3 spec v0.2 currently has a `scorer.py` that consumes `tool-calls.B` and `model-updates` and publishes `anomaly.scored` (detector `b3_markov`) at `session.ended`. Keeping it next to this pipeline would mean two services reading the same model and the same events, each publishing scores for the same sessions under two detector names. Consumers of `scores` would count every session twice. It would also mean two copies of the streaming code (session buffering, model reload) to keep in step.

| Concern | Batch (B3 spec, from v0.3) | Stream (this spec) |
| --- | --- | --- |
| Read historical events (dataset files, `analytics_db`) | yes | no |
| Fit transition counts, smoothing, argument emissions | yes | no |
| Calibrate thresholds by 10-fold CV on normal sessions | yes, including the new call-level threshold (Sec. 6) | no, reads them from the model |
| Offline evaluation (ROC-AUC, recall per attack type) | yes | replay evaluation of the live checks only (Sec. 9) |
| Announce `model.trained` on `model-updates` | yes | consumes it |
| Read `tool-calls.A` / `tool-calls.B` | no | yes |
| Call-level `out_of_order` | no | yes |
| Session score at `session.ended` | no (removed) | yes |
| Publish to `scores` | no (removed) | yes, detectors `markov` (session scores) and `markov_order` (call alerts) |

This is the usual split between a batch layer that rebuilds a model from all history and a speed layer that serves it with low latency (the Lambda architecture; Kiran et al. 2015). The model file is the contract between them.

&#91;embedded content: data flow between the B3 batch pipeline and this stream pipeline\]

The batch pipeline is the only writer to `model-updates`, and this pipeline is the only writer to `scores` for the Markov detector.

**One scoring implementation.** The scoring arithmetic (padding, order-K states, smoothing, NLL, argument flags) must give the same number in both places, because the batch side uses it for calibration and evaluation and this side for alerts. So this pipeline does not reimplement it. It imports the pure `domain/` modules of the B3 package (`sequences`, `scoring`, `arguments`), which do no I/O. A parity test (Sec. 10.4) fails if the stream and batch scores of any session differ by more than 1e-9.

**What changes for consumers of `scores`.** Detector name `b3_markov` is replaced by `markov` for session scores; call-level alerts are published under a second name, markov\_order. The session score keeps its meaning (B3 Sec. 13.4, default `joint`). New call-level events appear (Sec. 7). Any dashboard or fusion step (B4) that reads `b3_markov` must be switched over in the same release.

**Relation to S07 (allow-list policy check).** S07 is the other real-time guard on the same topics. It is deterministic: a hand-written policy plus the current `toolset-config`, publishing `violation.flagged` events to `flags`. The two are designed to complement each other, not to overlap.

|  | S07 allow-list | S08 Markov order check (this spec) |
| --- | --- | --- |
| Basis | hand-written policy per agent + `toolset-config` | model of normal tool order learned from data (B3) |
| Training, warm-up | none | B3 batch training and calibration per agent |
| Unknown or revoked tool | `tool_not_allowed` | no alert; scored as `<UNK>` |
| Order | `precondition_missing` (named prerequisites), `max_calls_exceeded` (counts) | `out_of_order`: any improbable transition, including orders no rule names |
| Arguments | explicit argument rules (recipient, secrets, dates, paths) | only inside the session score (Agent B) |
| Errors | false negatives where no rule exists | false alarms at a calibrated rate (Sec. 6) |
| Output | `violation.flagged` on `flags` | `anomaly.scored` on `scores` |

S07 catches what someone wrote a rule for. S08 catches deviations from what normal sessions do, including ones nobody anticipated, at the price of a controlled false-alarm rate. Where both fire on the same session (for example a skipped check on Agent B), that is expected; combining `flags` and `scores` is the job of the fusion step (B4), not of either guard.

## 3. Inputs

### 3.1 Tool-call topics

`tool-calls.A` and `tool-calls.B` are keyed by `session_id` (confirmed), so all events of one session land in one partition and arrive in log order. The topic decides the agent: `agent_id = A` or `B` (also in `data.agent_id`). Live events use the flat envelope, for example a `tool_call.completed` on `tool-calls.A` with `data.tool_name = correlate_columns`, `data.arguments = {dataset_id, columns, method}`, `data.session_call_index` and `data.success`. Fields used:

- All events: `event_id`, `event_type`, `session_id`, `sequence`, `occurred_at`.
- `session.started`: opens the session. `data.category` and `data.attack_type`, if present, are **never read** for scoring; live traffic has no labels. They are used only in replay evaluation (Sec. 9).
- `tool_call.completed` **and** `tool_call.failed`: both are calls. Fields: `data.tool_name`, `data.session_call_index`, `data.success`, and `data.arguments` (Agent B session score only). A failed call is a step the agent attempted, so its position in the order matters as much as a successful one. Agent A's recorded data shows the runtime failing calls with reasons `unknown_tool`, `execution_result` and `policy_denied`.
- `session.ended`: closes the session.

Other event types (`model_call.*`, `tool_call.requested`) carry no new call. If an agent emits both `tool_call.requested` and a result with the same `tool_call_id`, the call is counted once, at the result, and takes its tool name from whichever of the two has it. A call without any tool name is `<UNK>`. This makes the parser accept Agent A's recorded payload (`agent-run-events-v2`, where only the requested event has the name and unknown tools have none) as well as the flat live payload.

### 3.2 Model topic

`model-updates` carries `model.trained` messages from the batch pipeline (B3 Sec. 9). From B3 v0.4 there is **one model per agent**, announced with key `b3-markov-chain.A` or `b3-markov-chain.B` and `data.agent` naming the agent, so a compacted topic keeps the newest model of each agent (B3 Sec. 15). This pipeline reads messages whose key starts with `b3-markov-chain.` and takes from `data`: `agent`, `version` and `transition_table` (the table of B3 Sec. 5, with `calibration.threshold` and `calibration.call_threshold` per order from B3 Sec. 14, and for Agent B the v0.2 `arguments` block).

**Agent A** uses different tools from Agent B. Its toolset (`statistics-tools-v1`, the version every recorded session reports) has two parts:

- Four **numerical tools**, defined in the agent's `tools/` folder and executed by its `StatisticsTools` executor: `inspect_dataset`, `describe_columns`, `aggregate_statistics`, `correlate_columns`. Any other name that reaches the executor is failed with `unknown_tool`, which is the source of the unnamed calls in the recorded data.
- Two **control tools**, recorded with `kind = control` and not in that folder: `finalize_statistics` and `request_clarification`.

All six appear in the recorded normal sessions, so the learned vocabulary is complete. `describe_columns` is rare: one call in all 73 normal sessions, so transitions out of it are poorly estimated and may raise `out_of_order` on legitimate use (Sec. 11). Agent A gets its own model, trained by B3 on Agent A's dataset with this fixed vocabulary (B3 Sec. 15). That model is sequence-only, because the recorded A events carry arguments only as a hash, so Agent A's session score is the `seq` score. Events of an agent for which no model has been announced yet are counted (`unscored_no_model` metric) but not scored.

## 4. Stream processing model

### 4.1 Per-session state

The stream is keyed by `(agent_id, session_id)`. For each active session the operator keeps a small state record:

- `model_version`: the model pinned when the session started (Sec. 8.2).
- `context`: the last K symbols, initialised to `<START>`^K (B3 Sec. 4.1).
- `next_index`: the next expected `session_call_index`, starting at 1.
- `pending`: calls that arrived ahead of a gap, ordered by index (Sec. 4.2).
- Running sums for the session score: sequence log-likelihood, argument log-likelihood, number of transitions, n\_unseen, min\_p and the worst transition.
- Argument context for the v0.2 consistency flags: the last `tone_checker` draft and the last scanned text, as hashes of the whitespace-collapsed text, not the text itself.
- `violations`: the call-level alerts already emitted, so none is sent twice.
- `last_event_time`, for the idle timeout.
- `next_seq` and `seen_seq`: the next expected envelope `sequence` and the higher sequence numbers already seen, plus `end_seq`, the `sequence` of `session.ended` once it has arrived. Used only to decide when the session is complete (Sec. 4.2).

Every event updates this record in O(K) time, and K is at most 3. Memory per session is constant, so total memory grows with the number of concurrently active sessions and never with stream length. These are the defining constraints of data stream processing (Babcock et al. 2002). The Markov property is what makes this possible: the next-step probability depends only on the last K calls, so no session history beyond that has to be stored.

### 4.2 Event time, delivery order and behavioural order

Two different kinds of "out of order" must not be confused.

- **Delivery disorder** is an infrastructure effect: event i+1 reaches the consumer before event i, because of producer retries, partition rebalancing or a replay. It says nothing about the agent.
- **Behavioural disorder** is what this pipeline exists to flag: the agent really called the tools in an improbable order.

**Two counters, two jobs.** Calls are ordered by the agent's call counter, `data.session_call_index`, never by arrival time or by `occurred_at`. Completeness is judged by the envelope counter `sequence`, which numbers every event of a session (start, calls, model calls, end) without gaps; in Agent A's recorded file it is gapless in all 130 sessions. A call without `session_call_index` is placed among the calls by its `sequence`. `occurred_at` is not used for ordering at all: in Agent A's recorded file it gives a different order than `sequence` in 35 of 130 sessions, and in 32 sessions `session.ended` carries an earlier timestamp than the last tool call. This follows the event-time principle of the Dataflow Model (Akidau et al. 2015), with the agent's own counters as the most reliable event time available.

**Reordering rule.** A call with `index == next_index` is processed at once, then any directly following calls waiting in `pending`. A call with a higher index waits in `pending`. Every event, whatever its type, updates the `sequence` bookkeeping.

**Closing rule.** `session.ended` does not close the session at once. It records its `sequence` as `end_seq`, and the session closes when every `sequence` below `end_seq` has been seen, so no earlier call can still be on its way, or when `reorder_timeout` (default 5 s of processing time) passes. Only then is the `<END>` transition checked and the session score computed.

**Lost events.** If a call-index gap stays open past `reorder_timeout` in a running session, or sequence numbers are still missing when the closing timeout passes, the missing calls are declared lost. The context is reset to an unknown state, the order check is skipped for the next K transitions (they would compare against a context that is not known), a `gap` metric is logged, and the session score is marked `complete: false`. An event whose `sequence`, `event_id` or call index was already processed is a duplicate (Sec. 4.3). An event for a session that is already closed is counted as `late_event` and dropped; with keying by `session_id` and the closing rule above, this should not happen in normal operation.

The trade-off is latency against correctness. With keying by `session_id`, Kafka delivers one partition in log order, so in normal operation `pending` stays empty and every call is checked as soon as it arrives.

### 4.3 Duplicates and delivery guarantees

Kafka consumers get at-least-once delivery by default: after a crash, events since the last committed offset are read again. Two measures make the output correct anyway:

- Input deduplication by `event_id` within a session (as in B3 Sec. 3.2), plus the index check above.
- Deterministic output ids: each `anomaly.scored` event gets `event_id = uuid5(session_id, call_index, check, model_version)`. A replayed alert has the same id, so downstream consumers can drop the copy. Exactly-once Kafka transactions are not required for v0.1.

Offsets are committed only after the outputs for those events have been produced (flush, then commit).

### 4.4 Session start, end and timeouts

A session opens on `session.started`. If its first event is anything else (the start was lost, or the pipeline restarted mid-session), it opens on that event with an **unknown context**: the order check is skipped for its first K transitions, including the one that would start from `<START>`, and the session is marked `complete: false`. It closes by the closing rule of Sec. 4.2, which triggers the final transition to `<END>` and the session score. Sessions with no event for `idle_timeout` (default 30 min) are closed as `complete: false`, scored without the `<END>` transition, and evicted. This is a session window with an inactivity gap, in Dataflow terms. Without it, abandoned sessions would leak memory, and an agent could avoid ever being scored by never sending `session.ended`.

### 4.5 Parallelism and restart

The operator is stateless across sessions, so it scales by Kafka partition: run as many consumer instances as there are partitions in one consumer group. Session state is kept in memory. After a restart or rebalance, a session that was in flight is rebuilt only from events still unread; its earlier context is lost, so it is handled as a gap (Sec. 4.2). For a course project this is acceptable. A production version would store the state in a changelog topic (as Kafka Streams or Flink do).

## 5. Checks

For each call t (after reordering) the operator maps the tool to a symbol (`<UNK>` if unknown or unnamed), looks up the transition from `context` in the agent's model, and runs the call-level check of Sec. 5.2. At most one alert is reported per call.

### 5.1 Unknown tools and failed calls (no separate alert)

S07 already flags `tool_not_allowed` against the authoritative per-agent toolset in `toolset-config`. A second, weaker copy of that check here, based on the model's vocabulary, would only repeat S07's flag on another topic, and would be wrong whenever the toolset changes before the model is retrained. So this pipeline publishes no `unauthorized_tool` alert.

Unknown tools still matter for the model. A tool not in the vocabulary, or a call that arrives without a name, is mapped to `<UNK>`, exactly as in batch training, so scores match the batch computation. In Agent A's recorded data, 13 of the 16 unknown-tool attempts occur in **normal** sessions: the agent asks for a tool that does not exist, and the runtime fails the call with reason `unknown_tool`. For Agent A, a transition into `<UNK>` is therefore a seen, moderately probable step. It is judged by the `out_of_order` threshold like any other transition and is not an attack signal on its own.

Failed calls (`tool_call.failed`) are calls in the sequence. The model uses the tool name only; the success flag is not part of the state (B3 Sec. 4.1).

### 5.2 out\_of\_order

**Rule.** For the transition `context -> x_t` the operator computes the smoothed log-probability `lp = ln p(x_t | context)` with exactly the smoothing stored in the model (B3 Sec. 4.3). The call is flagged when

`lp < tau_call(K)`

where `tau_call(K)` is the call-level threshold for the configured order, calibrated by the batch pipeline (Sec. 6). The same test runs at `session.ended` for the transition `context -> <END>`. That catches sessions that stop in an unusual place, for example right after `find_contact`.

**Why a probability threshold and not "unseen".** The simplest rule flags any transition never seen in training (count 0). That is the stide rule of Forrest et al. and Hofmeyr et al., applied to tool bigrams. On this data it is too strict: normal sessions include rare legitimate orders (B3 Sec. 7.4: variants with `get_free_slots` before `find_contact`, `save_draft` before the checks), so a held-out normal session often contains one transition its training folds never saw. A calibrated threshold on the smoothed probability keeps the false-alarm rate at a chosen level instead. It also uses the row totals: an unseen move out of a state seen 250 times is far stronger evidence than one out of a state seen twice. Warrender et al. compared exactly these data models (lookup of seen sequences versus probabilistic models with thresholds) on system-call data. DeepLog (Du et al. 2017) uses the same pattern online: it predicts the next log key from a short history and raises an alarm on the first entry the model does not expect.

**Ablations** (Sec. 9): `--rule unseen` (stide-style, count 0) and `--rule topg` (flag when x\_t is not among the g most probable next symbols, as in DeepLog; default g = 2).

**Repetition.** A long run of one tool (calendar and draft harvesting, B3 Sec. 6) produces repeated self-loops, each only moderately improbable, so `out_of_order` may never fire. The operator therefore also tracks `run_length` and the session's call count. They are reported in the session event, not as call alerts, because v0.1 has no calibrated threshold for them; B3 already evaluates them as ablation indicators.

**Relation to S07's order rules.** S07's `precondition_missing` checks named prerequisites (for example `save_draft` needs `tone_checker` and `sensitive_content_scan` first), and `max_calls_exceeded` checks counts. `out_of_order` is the learned counterpart. It also fires for orders no rule names, such as an Agent A session that calls `finalize_statistics` before any computation if normal sessions never do that. It stays silent for rule violations that are common in normal data: B3 Sec. 7.4 found that many normal Agent B sessions skip both checks. The two guards are expected to disagree on some sessions, and the report should show where.

**Empty sessions.** A session with no tool call produces only the transition `<START> -> <END>`, which never occurs in either agent's normal sessions, so it always falls below the threshold. What that means differs by agent, so the handling is configured per agent (`MARKOV_EMPTY_SESSION_A` / `_B`):

- `alert` (default for Agent A): treated like any other session. The `<END>` check raises `out_of_order` (published only if call alerts are enabled for the agent, Sec. 6), and the session score is decided normally. For Agent A this is a real signal: 4 of the 6 sequence-visible injected sessions are empty, and no normal session is.
- `tag` (default for Agent B): no call alert. The session score is still published, with `data.empty_session: true` and `is_anomaly: false`, so consumers see the session without counting it as an anomaly. B3 Sec. 7.4 identifies Agent B's empty sessions as generator failures or blocked sessions rather than agent behaviour.
- `drop`: nothing is published; the session is counted in the `empty_sessions` metric.

The replay evaluation reports each agent's results with and without empty sessions, as B3 Sec. 7.4 asks.

### 5.3 Session score at session.ended

When a session closes the operator emits one session-level event with exactly the B3 score: `seq` (mean NLL per transition), `arg_total`, `arg_max`, the configured combined score (default `joint`, B3 Sec. 13.4), the decision against the session threshold in `calibration.threshold`, and the indicators n\_unseen, min\_p, worst transition, worst argument flag, n\_calls and max\_run\_length. The running sums of Sec. 4.1 give this without storing the session; for the argument flags, each call is featurized when it arrives, using the stored argument context. The value is the same as the batch `scoring.py` result (parity test, Sec. 10.4).

For Agent A the model has no argument part (Sec. 3.2), so its session score is `seq`, and `arg_total`, `arg_max` and the worst argument flag are null.

## 6. Calibration of the call-level threshold

A call-level check runs once per call, so a session of n calls gets n+1 chances to raise a false alarm. A per-call threshold set at the 1st percentile of normal transition probabilities would therefore flag far more than 1% of normal sessions. The threshold is instead calibrated on the **session minimum**, so that its false-alarm rate is a per-session rate, comparable with the batch threshold.

**Statistic.** For each held-out normal session s: `m(s) = min over t of ln p(x_t | state_t)`, over all T+1 transitions including the one to `<END>`. A session raises at least one `out_of_order` alert exactly when `m(s) < tau_call`.

**Procedure (batch side, B3 v0.3).** Reuse the 10-fold cross-validation of B3 Sec. 7.1. Each normal session is scored by the model fitted on the other nine folds, giving one held-out `m(s)` per normal session. Then `tau_call(K)` = the (100 - p)-th percentile of those values, with the same p as the session threshold (default 99, so the 1st percentile). With 269 normal sessions, about 3 normal sessions fall below it. The value is written to `calibration.call_threshold[K]` in the transition table and so reaches this pipeline in the `model.trained` message.

**Why this is valid.** It is a split-conformal argument: if a new normal session is exchangeable with the calibration sessions, the chance that its `m(s)` falls below the empirical 1st percentile is about 1%. Laxhammar and Falkman (2015) use the same idea for sequential detection, where alarms are raised while a trajectory is still being observed, and show that it keeps the alarm rate calibrated. The guarantee is only approximate here: the fold models are fitted on 90% of the data, so held-out scores are slightly more pessimistic than those of the final model, which makes the threshold slightly conservative. With about 269 sessions, the 1st percentile rests on about 3 sessions; report the 95th and 99.5th percentile variants as in B3 Sec. 7.1.

**Agreement with the session threshold.** The session score (mean NLL) and the call-level check (minimum log-probability) answer different questions: "is this session improbable overall?" versus "does this session contain one improbable step?". A session can trigger one and not the other. Both use the same calibration data and percentile p, so each flags about (100 - p)% of normal sessions, and their union at most about twice that. For Agent B (p = 99) that is about 2% of normal sessions; for Agent A (p = 95, B3 Sec. 15) it is up to about 10%. Report the union rate per agent from the CV scores.

**Agent A: call alerts are evaluation-only.** On its own, Agent A's call check would flag up to about 5% of normal sessions, while it can catch at most about 11% of the injected ones (Sec. 9.3), so most of its alerts would be false. By default the pipeline therefore computes Agent A's call alerts but does not publish them (`MARKOV_CALL_ALERTS_A=false`). They are written to the replay output and counted in the metrics, so Sec. 9 still measures them. Agent A's session scores are published as usual, with `is_anomaly` decided by the session threshold. Agent B's call alerts are published (`MARKOV_CALL_ALERTS_B=true`). Switching Agent A on is a configuration change, to be made once a larger normal dataset gives a call threshold with an acceptable false-alarm rate.

**Fallback.** A v0.2 table without `call_threshold` is still loaded. The pipeline then uses the rule `unseen` for `out_of_order` and logs a warning, because no calibrated threshold exists.

## 7. Output: anomaly.scored on scores

Topic `scores`, key `agent_id` (A or B). The envelope is the one S04 (Online Forest) already publishes (`scored_event` in `s04-online-forest/src/online_forest/events.py`), so every consumer of `scores` parses both detectors the same way.

**Top level (as S04):**

| Field | Value |
| --- | --- |
| `schema_version` | `"1.0"` |
| `event_id` | a UUID. S04 uses a random one; S08 uses a deterministic uuid5 (Sec. 4.3) so a replayed alert keeps its id. Both are UUID strings. |
| `event_type` | `"anomaly.scored"` |
| `occurred_at` | UTC time the score was produced (processing time), as in S04 |
| `run_id`, `session_id`, `sequence` | copied from the scored event |
| `request_id` | `null` |

**`data`, shared core (as S04, same names and meaning):**

| Field | Value |
| --- | --- |
| `scored_event_id` | `event_id` of the scored event: the tool call for a call alert, `session.ended` for a session score (the last event seen if the session was closed by timeout) |
| `agent_id` | `A` or `B` |
| `detector` | `"markov_order"` for call-level alerts, `"markov"` for session scores (S04: `"online_forest"`) |
| `model_version` | the B3 model version pinned for the session, e.g. `<UTC time>_additive` (S04: a constant such as `"oif-1"`) |
| `score` | rounded to 6 decimals; higher means more anomalous |

**`data`, S08 extension fields** (after the core; consumers that know only S04's fields ignore them):

| Field | Call-level alert | Session score |
| --- | --- | --- |
| `scope` | `call` | `session` |
| `check` | `out_of_order` | `session_score` |
| `score` means | `-lp`, surprise of that transition in nats | configured B3 score (default `joint` for B, `seq` for A) |
| `threshold` | `-tau_call(K)` | `calibration.threshold[K]` |
| `is_anomaly` | always `true` | `score > threshold` |
| other fields | `order`, `call_index`, `transition` {`state`, `next`, `count`, `state_total`, `p`}, `scored_event_occurred_at`, `latency_ms` | `order`, `seq_score`, `arg_score`, `worst_arg`, `n_unseen`, `min_p`, `worst_transition`, `n_calls`, `max_run_length`, `empty_session`, `complete`, `violations`, `scored_event_occurred_at`, `latency_ms` |

Example call-level alert:

```json
{
  "schema_version": "1.0", "event_id": "<uuid5>", "event_type": "anomaly.scored",
  "occurred_at": "<UTC time of scoring>", "run_id": "<run_id>", "session_id": "<session_id>",
  "sequence": 6, "request_id": null,
  "data": {
    "scored_event_id": "<event_id of the tool call>", "agent_id": "B",
    "detector": "markov_order", "model_version": "<UTC time>_additive", "score": 7.41,
    "scope": "call", "check": "out_of_order", "threshold": 5.92, "is_anomaly": true,
    "order": 2, "call_index": 4,
    "transition": {"state": "find_contact>save_draft", "next": "save_draft",
                   "count": 0, "state_total": 0, "p": 0.0006},
    "scored_event_occurred_at": "<event time of the tool call>", "latency_ms": 3
  }
}
```

A session score has the same top level and core, with `scored_event_id` pointing at `session.ended` and the session fields listed above.

**Differences in volume.** S04 publishes one score for every tool call. S08 publishes call-level events only on a violation (at most once per call), plus one session score for every session; a normal call carries no information for consumers, and scoring every call would multiply the topic volume by about 7. Consumers must therefore not assume one score per call from every detector; `data.scope` says what a score refers to.

**Two detector names.** Call alerts and session scores are on different scales. A call alert's score is the surprise of one transition (`-lp`, in nats); a session score is B3's per-transition mean (`joint` for Agent B, `seq` for Agent A). A consumer that reads only S04's core fields (`detector`, `score`) and expects one comparable score per detector, as S04 provides, would mix them. They are therefore published under two detector names: `markov_order` for call-level `out_of_order` alerts and `markov` for session scores. Within each name the score has one meaning and one threshold. `data.scope` stays as a redundant check.

**Detection latency.** Because `occurred_at` is the processing time, as in S04, the event time of the scored event travels in `data.scored_event_occurred_at`, and `data.latency_ms` is their difference (Sec. 9). The shared core is fixed by S04's format; the extension fields belong to S08 and may change with the owner of the envelope (B4).

## 8. Model lifecycle

### 8.1 Loading at startup

`model-updates` should be a compacted topic. Models are keyed per agent (`b3-markov-chain.A`, `b3-markov-chain.B`), so compaction always keeps the newest model of each agent; a single key per model name would let a new B model hide the A model. On startup the pipeline reads the topic from the earliest offset and loads the newest table for each agent before it consumes any tool-call event. Tool-call partitions stay paused until the models are loaded (or until `MARKOV_MODEL_BOOTSTRAP_TIMEOUT_S` passes, after which agents without a model are counted as `unscored_no_model`); their events wait in Kafka instead of being dropped. A table is validated before use: schema of B3 Sec. 5, `spec_version` 0.1 to 0.4, smoothing method known, the state delimiter absent from every tool name, and `data.agent` matching the key. An invalid table is rejected with an error log, and the agent's previous model stays active.

### 8.2 Hot swap and version pinning

A new `model.trained` message is loaded in the background and swapped in atomically. **Sessions already in flight keep the model they started with**; only sessions that start after the swap use the new one. Otherwise one session could be scored by two models with different vocabularies and thresholds, and neither its call alerts nor its session score would match any batch result. Old models are released when their last pinned session closes. Every output event names its `model_version`.

### 8.3 No online learning, by decision

The pipeline never updates counts from the stream, although Markov counts would be trivial to update incrementally. Three reasons:

1. **Poisoning.** Live traffic is unlabelled and contains attacks. A model that learns from it can be trained, slowly, to accept an attack pattern. Rubinstein et al. (2009) demonstrated such gradual "boiling frog" poisoning against a network anomaly detector that was retrained on live traffic.
2. **Calibration.** Thresholds come from cross-validation on clean normal sessions. Counts that drift in the stream would invalidate them silently.
3. **Reproducibility.** Every alert must be traceable to one versioned model file. That is a course requirement as much as an operational one.

Model updates therefore go only through the batch pipeline, which can filter the training data (normal category, reviewer verdict) and re-run the evaluation.

### 8.4 Drift monitoring

The model can go stale when the agent's normal workflow changes (a new tool, a new prompt). The stream is where this shows first, as a rise in alerts on traffic that is in fact normal. The pipeline does not adapt, but it watches for this (Gama et al. 2014 survey how to detect such concept drift).

- Per agent and model version it keeps counters: calls, sessions, `out_of_order` alerts, session flags, gaps and timeouts, exported as metrics and logged once per minute.
- A Page-Hinkley test runs on the stream of session scores. It accumulates deviations of each score from the running mean and signals when the accumulated sum rises more than `ph_lambda` above its minimum. Default `ph_delta` = 0.05 nats and `ph_lambda` = 50 (to tune on replay).
- A signal is logged and exported as a `drift_suspected` metric. It is **not** published to `scores` (it is not an anomaly of one session) and does not change the model. Its meaning is: retrain and re-check, or investigate a campaign.

Drift and attack look alike from inside the stream: a sustained rise could be a new legitimate workflow or a wave of attacks. Telling them apart needs a person, which is one more reason not to adapt automatically.

## 9. Evaluation

The batch spec already measures how well the model separates normal from adversarial sessions. This evaluation measures what streaming adds or changes: whether the live checks give the same answers, how early they fire, and whether they survive the conditions of a real stream.

### 9.1 Replay harness

A replayer reads a dataset file and publishes each event to the agent's topic session by session in `sequence` order, with sessions interleaved by the time of their `session.started`. It never sorts by `occurred_at`, because Agent A's recorded timestamps contradict the event order in 35 of 130 sessions (Sec. 4.2). Publishing can be sped up (`--speed`, default 100x) or run as fast as possible. For Agent B it reads the B3 dataset (B3 Sec. 9); for Agent A it reads Agent A's recorded JSONL, unwraps the `event` field of each record and publishes it unchanged, so the parser path for `agent-run-events-v2` is exercised too (Sec. 3.1). Labels (`category`, `attack_type`, and for Agent A the observed-behaviour `label`) are used only by the evaluator, which joins the pipeline's output with them by `session_id`. For unit tests and CI the same harness runs in process against the operator without Kafka. The models are the final B3 models trained on all normal sessions of each agent; the CV-based false-alarm figures come from the batch side.

**Leakage note.** The final model has seen every normal session, so normal sessions replayed through it look better than new traffic would. False-alarm rates must come from held-out data: either the CV scores, or a replay where each normal session is scored by its fold model (`--fold-models`, which loads the ten fold tables from the batch output).

### 9.2 Metrics

1. **Parity.** For every session, the stream session score equals the batch score of the same session and model within 1e-9. Any difference is a bug.
2. **Call-level detection.** Per agent and attack type: the share of sessions with at least one `out_of_order` alert (session recall of the live check, computed for every agent from the replay output, including Agent A whose call alerts are not published by default). On held-out normal sessions: the share with at least one alert (false-alarm rate, target as calibrated in Sec. 6). Report the check alone and its union with the session score.
3. **Earliness.** For each detected adversarial session: `calls_to_alert` = the index of the first alerting call, and `calls_saved` = n\_calls - calls\_to\_alert, the calls that ran after the alert. A session-end detector has calls\_saved = 0 by construction, so this is the quantity that justifies a streaming detector. Lavin and Ahmad (2015) built the same idea into the scoring of the Numenta Anomaly Benchmark, which rewards detecting an anomaly early within its window. Report the median and distribution per attack type, and for Agent B the share of detected sessions alerted before `save_draft` (the call with external effect).
4. **Overlap with S07.** Run S07 on the same replay and report, per agent and attack type, sessions flagged by S07 only, S08 only, and both. This shows what the learned check adds beyond the rules.
5. **Order ablation.** Items 2 and 3 for K = 1 and 2 (Agent A: K = 1 only, see Sec. 11) and for the rules `threshold`, `unseen` and `topg`.
6. **Robustness.** Replays with (a) shuffled delivery within each session, bounded by 3 positions, (b) 5% duplicated events, (c) 1% dropped calls, (d) a restart in the middle. Expected: (a) and (b) give exactly the output of the clean replay; (c) and (d) give gap markers and `complete: false` but no false `out_of_order` alerts caused by the gaps.
7. **Model swap.** Announce a second model for one agent in the middle of a replay. Every session is scored entirely by one version, the other agent's model is untouched, and no event is lost or duplicated.
8. **Cost.** Throughput (events/s) of one instance, latency from event arrival to output (p50, p99), and memory per active session.

### 9.3 Expected results

The live order check will catch only part of the attacks, and this is a property of the data, not of the pipeline. No order check can flag an adversarial session whose tool sequence is identical to some normal session's.

- **Agent B:** 36 of 54 adversarial sessions in the partial file have such a sequence (B3 Sec. 13.1).
- **Agent A:** in the recorded file, 51 of 57 `prompt_injected` sessions (attack type `direct_prompt_injection`) have a tool sequence identical to some normal session's. Session-level recall of any sequence-only check is therefore at most 6 of 57, about 11% (tool names only; failed and successful calls count alike). Four of those 6 have no tool call at all (`<START> -> <END>`, never seen in normal A sessions), so they are likely the only easy ones. The injections in this data mostly change what the agent says or which values it computes, not which tools it calls in which order.

The call-level check is expected to catch the sequence-visible cases early, while the argument-aware session score (Agent B) and S07's rules remain the main detectors. The report should present S08 as early warning for order deviations, with its recall, false-alarm rate, earliness and overlap with S07 side by side.

## 10. Implementation guidance

### 10.1 Layout

A new top-level folder `s08-markov-order-check/`, laid out like `s04-online-forest/`: one flat package under `src/` (Python package `markov_order_check`), a `requirements.txt` next to `pyproject.toml`, and tests in `tests/`.

```
s08-markov-order-check/
├── Dockerfile                  # python:3.11-slim-bookworm, CMD python -m markov_order_check.consumer
├── pyproject.toml              # name markov_order_check; deps confluent-kafka, b3-markov-chain (path dependency)
├── README.md                   # S07-style header, then S04's headings (overview, architecture, Kafka input, model, output, ...)
├── requirements.txt            # confluent-kafka, pytest
├── src/
│   └── markov_order_check/
│       ├── __init__.py
│       ├── config.py           # tunables: order per agent, rule, top-g, timeouts, Page-Hinkley (Secs. 4-8)
│       ├── consumer.py         # Kafka loop: tool-calls.A/B + model-updates -> scores; env vars; commit after produce
│       ├── detector.py         # MarkovOrderDetector, one per agent: session state, reordering, out_of_order, session score (Secs. 4-6)
│       ├── models.py           # per-agent model registry: load and validate model.trained, version pinning (Sec. 8)
│       ├── events.py           # is_tool_call, agent_id, payload, requested/result join, anomaly.scored builders (Secs. 3, 7)
│       ├── drift.py            # counters and Page-Hinkley test (Sec. 8.4)
│       ├── replay.py           # replay harness and evaluator (Sec. 9)
│       └── send_test_events.py # publishes sample sessions of A and B for local runs
└── tests/
    ├── test_detector.py
    ├── test_events.py
    ├── test_models.py
    ├── test_parity.py
    ├── test_robustness.py
    └── test_consumer.py
```

The roles follow S04. `consumer.py` is the only module that imports Kafka: it reads the environment variables, keeps one `MarkovOrderDetector` per agent (created when that agent's model arrives, where S04 creates one on the first event), and produces to `scores`. `detector.py` does the per-event work and returns result dicts, as S04's `OnlineForestDetector.process` does, so it can be tested without a broker. `events.py` holds the envelope helpers, extended for `tool_call.requested` and the `agent-run-events-v2` payload. `config.py` holds the default tunables, which environment variables can override (Sec. 10.2). S04 has no `models.py`, `drift.py` or `replay.py`; this pipeline needs them for announced models (Sec. 8) and the replay evaluation (Sec. 9).

Scoring arithmetic is imported from `b3_markov.domain` (`sequences`, `scoring`, `arguments`) and never copied (Sec. 2). The operator calls it one transition at a time, so `b3_markov.domain.scoring` must expose a step function, `step(table, order, context, symbol) -> (lp, count, state_total)`, and the argument featurizer must accept one call plus the argument context. Both are small refactors on the batch side (B3 v0.3).

### 10.2 Configuration

Environment variables, as in B1, B3 and S04:

| Variable | Default |
| --- | --- |
| `KAFKA_BOOTSTRAP` | `localhost:29092` |
| `KAFKA_GROUP_ID` | `markov-order-check` |
| `TOPICS` | `tool-calls.A,tool-calls.B` |
| `MODEL_TOPIC` | `model-updates` |
| `SCORES_TOPIC` | `scores` |
| `MARKOV_ORDER_A` / `MARKOV_ORDER_B` | `1` / `2` (must exist in the agent's table) |
| `MARKOV_RULE` | `threshold` (or `unseen`, `topg`) |
| `MARKOV_TOPG` | `2` |
| `MARKOV_REORDER_TIMEOUT_S` | `5` |
| `MARKOV_IDLE_TIMEOUT_S` | `1800` |
| `MARKOV_MODEL_BOOTSTRAP_TIMEOUT_S` | `15` |
| `MARKOV_PH_DELTA` / `MARKOV_PH_LAMBDA` | `0.05` / `50` |
| `MAX_SESSIONS` | `10000` (oldest idle sessions are closed first) |
| `MARKOV_CALL_ALERTS_A / MARKOV_CALL_ALERTS_B` | false / true (publish call alerts; Sec. 6) |
| `MARKOV_EMPTY_SESSION_A / MARKOV_EMPTY_SESSION_B` | alert / tag (or drop; Sec. 5.2) |

The replay CLI (`python -m markov_order_check.replay`) takes `--agent A|B`, `--dataset-file`, `--speed`, `--fold-models`, `--shuffle`, `--duplicate-rate`, `--drop-rate`, `--restart-at`, `--with-s07-flags` (a file of S07 output for the overlap metric) and `--out`.

### 10.3 Docker

Base image \`python:3.11-slim-bookworm\` as in S04 (no Java needed); installs `.[kafka]` and the B3 package. Default command `python -m markov_order_check.consumer`. Image name `atgm-markov-order-check`, run like S07's image (`--network <kafka-network> -e KAFKA_BOOTSTRAP=kafka:9092`). One replica per partition can be added later.

### 10.4 Tests (minimum)

- `test_events`: a flat `tool_call.completed` and a `tool_call.failed` each give one call; an `agent-run-events-v2` requested/completed pair gives one call with the name from the requested event; a call without a name gives `<UNK>`; `model_call.*` events give nothing.
- `test_detector (session state)`: calls delivered out of order are processed in index order; a duplicate `event_id` or index is ignored; a gap past the timeout resets the context and skips the check for K transitions; an idle session is closed with `complete: false`; a session without `session.started` opens on its first call.
- `test_detector (checks)`: a transition below `tau_call` gives `out_of_order`; the `<END>` transition is checked; an unknown tool gives no alert of its own and is scored as `<UNK>`; rule `unseen` fires on count 0 only; rule `topg` fires when the symbol is outside the top g; at most one alert per call.
- `test_models`: models for A and B are kept apart by key; a session keeps its model after a swap; a new session gets the new model; an invalid table, or one whose `data.agent` does not match its key, is rejected and the old one stays; an agent without a model is not scored and increments `unscored_no_model`; a table without `call_threshold` falls back to `unseen`.
- `test_parity`: on the worked example of B3 Sec. 8, on the sample B sessions and on the recorded A sessions, the stream session score equals `b3_markov` batch scoring within 1e-9; the minimum log-probability seen by the stream equals the batch `m(s)`.
- `test_robustness`: shuffled (within 3 positions) and duplicated replays give byte-identical output to the clean replay; output event ids are deterministic.
- `test_consumer` (fake consumer and producer): tool-call partitions stay paused until models are loaded; offsets are committed only after the produce is flushed; events go to `scores` with key `agent_id`, with detector `markov_order` for call alerts and `markov` for session scores.
- `test_detector` (ordering and closing): an Agent A session whose `session.ended` has an earlier `occurred_at` than its last call, but a higher `sequence`, is closed only after that call and gives the same result as the clean session; a `session.ended` that arrives before an event with a lower `sequence` waits for it until the timeout; with a `sequence` still missing at the timeout the session closes as `complete: false`; a session opened without `session.started` skips the check for its first K transitions; an event for a closed session is counted as `late_event`.
- `test_detector` (agent policies): an empty session gives `out_of_order` at `<END>` under `alert`, a published session score with `empty_session: true` and `is_anomaly: false` under `tag`, and nothing under `drop`; with `MARKOV_CALL_ALERTS_A=false` an Agent A call alert is computed and written to the replay output but not produced to `scores`, while Agent A's session score is produced.

### 10.5 Acceptance criteria

`PYTHONPATH=src pytest` passes without a broker. A replay of each agent's sample file produces one session event per session and call alerts only where Sec. 5 says, identical across two runs. Parity holds on every session. The README reports the metrics of Sec. 9.2 per agent, including the overlap with S07. `docker compose up` with both models already on `model-updates` publishes alerts for a replayed adversarial session within one second of its triggering call.

## 11. Limitations, decisions and open questions

**Limitations**

- Recall of the order check is bounded by the data: adversarial sessions with a normal tool sequence cannot be flagged by any order check. That is 36 of 54 for Agent B (partial file) and 51 of 57 for Agent A (Sec. 9.3).
- Agent A's model rests on 73 normal sessions with 0 to 3 calls each: 143 calls and 216 transitions, 27 distinct. Only order 1 is supportable; order 2 would be almost entirely unseen contexts. With 73 sessions the 99th percentile is effectively the maximum held-out score, so B3 uses the 95th percentile for Agent A (B3 Sec. 15).
- The call threshold of Agent B rests on about 3 tail sessions out of 269 (Sec. 6), so the real false-alarm rate on new traffic is uncertain; report it with a bootstrap interval.
- Markov and time-homogeneity assumptions carry over from B3 (B3 Sec. 10): only the last K calls matter, not the position in the session or the time of day.
- Repetition attacks (harvesting, flooding) produce moderately probable self-loops and may raise no call alert; only the session indicators show them (Sec. 5.2). S07's `max_calls_exceeded` covers the explicit limits.
- In-memory state is lost on restart; in-flight sessions are then scored as incomplete (Sec. 4.5).
- Argument anomalies are visible only in Agent B's session score at the end, not as early call alerts, and not at all for Agent A; S07's argument rules cover the explicit cases.
- Rare legitimate tools are false-alarm risks. `describe_columns` appears once in Agent A's 73 normal sessions, so almost any transition into or out of it is improbable under the model. Report `out_of_order` alerts involving it separately, and recalibrate once more normal data exists.

**Decided in this spec**

- Live scoring moves from the batch spec to this pipeline; detector `b3_markov` becomes `markov` for session scores, and call-level alerts use `markov_order` (Secs. 2, 7).
- Scoring code is shared by importing the B3 domain modules, with a parity test (Sec. 2).
- `out_of_order` uses a calibrated probability threshold on the session minimum; `unseen` and `topg` are ablations (Secs. 5.2, 6).
- No `unauthorized_tool` alert: S07 owns `tool_not_allowed`; unknown tools are scored as `<UNK>` (Sec. 5.1).
- `tool_call.failed` counts as a call; a requested/result pair counts once (Sec. 3.1).
- One model per agent, keyed `b3-markov-chain.<agent>`; Agent A's model is trained on Agent A's dataset and is sequence-only (Sec. 3.2).
- Call alerts are published only on violation; session scores always (Sec. 7).
- No online learning; drift is monitored, not adapted to (Sec. 8).
- Tool-call topics are keyed by `session_id` (confirmed).
- Folder `s08-markov-order-check/`, package `markov_order_check` (Sec. 10).
- Calls are ordered by `session_call_index`; completeness and closing use the gapless `sequence`; `occurred_at` is never used for ordering, in the pipeline or the replay (Sec. 4.2).
- Agent A's call alerts are computed but not published by default (`MARKOV_CALL_ALERTS_A=false`); its session scores are published (Sec. 6).
- Empty sessions: `alert` for Agent A, `tag` for Agent B, configurable per agent (Sec. 5.2).

**Open questions**

1. Does live `tool-calls.A` carry the flat payload of the example (with `data.tool_name` and clear `data.arguments`), the recorded `agent-run-events-v2` payload (name only in `tool_call.requested`, arguments hashed), or both? The parser accepts both (Sec. 3.1), but if live A has clear arguments, an argument part for Agent A's model becomes possible.
2. The example `tool-calls.A` message does not match Agent A's argument schemas. It shows `correlate_columns` with `columns: ["visits", "spend"]` and `dataset_id: "ds-21"`, while the tool code reads `x_column` and `y_column`, takes `dataset_id` as a UUID, and validates arguments strictly (a mismatch fails with `invalid_arguments`). Is the example from a mock agent? This matters for any argument features and for S07's Agent A argument rules, not for the order check.
3. Agent A's recorded data shows the runtime failing calls (`unknown_tool`, `policy_denied`), although agents do not refuse calls on their own initiative. Should S07 and S08 treat a `tool_call.failed` with `policy_denied` as already handled? S08 currently just counts it as a call.
4. Who owns the `anomaly.scored` envelope (B4?), and do its consumers accept the new `scope` and `check` fields?
5. Extension: call-level argument alerts (an `unlikely_argument` check on the per-call flag NLL) with their own calibrated threshold. For Agent A, flags can follow the tool schemas: `operation` (count, sum, mean, min, max), `method` (pearson, spearman), `missing_policy`, whether `group_by` is set, and the number of columns. The recorded `features` already carry most of these.

## 12. References and how they justify the design

The model itself (multi-order Markov chain, MLE, smoothing, NLL score) is justified in the B3 spec (Sha et al. 2018, Ye 2000, Chen). The papers below justify what this spec adds.

| Design choice | Paper | What it supports |
| --- | --- | --- |
| Problem framing: detect anomalous sequences against a database of normal ones, online | Chandola, Banerjee, Kumar 2012 | Survey of discrete-sequence anomaly detection; separates whole-sequence from subsequence detection and discusses the online setting. Use it to place this pipeline: session score = whole sequence, call check = online local test. |
| Per-event next-symbol check, `topg` ablation | Du, Li, Zheng, Srikumar 2017 (DeepLog) | Predicts the next log key from a short history and alerts on the first entry that deviates from the learned workflow, while the log is streaming. Same structure as our call check, with an LSTM instead of a Markov chain. |
| Order violations in LLM-agent traces | Liu et al. 2025 (TraceAegis) | Learns workflow structure from historical agent tool-call traces and flags "execution order disturbance" as a structural anomaly class. Shows the problem is studied for agents specifically (preprint). |
| Calibrating the call threshold on held-out session minima | Laxhammar and Falkman 2015 | Inductive conformal anomaly detection: a calibration set of normal examples gives a well-calibrated alarm rate, including for sequential detection while a trajectory is still being observed. |
| One pass, constant work per event, bounded memory | Babcock, Babu, Datar, Motwani, Widom 2002 | Defines the data stream model and its constraints (continuous queries, limited memory, no second pass). |
| Event time, reordering, session windows with inactivity timeout | Akidau et al. 2015 (Dataflow Model) | Event time versus processing time, watermarks for out-of-order data, session windows defined by a gap; trade-off between completeness and latency. |
| Batch model + streaming serving layer | Kiran, Murphy, Monga, Dugan, Baveja 2015 | Lambda architecture: batch layer recomputes from all data, speed layer serves low-latency results. |
| No online learning | Rubinstein et al. 2009 (ANTIDOTE) | An anomaly detector retrained on live traffic can be poisoned slowly ("boiling frog") until attacks evade it. |
| Earliness as an evaluation metric | Lavin and Ahmad 2015 (NAB) | Benchmark for streaming anomaly detection whose scoring rewards early detection within an anomaly window. |

Threat model and neighbouring guard: the OWASP Top 10 for Agentic Applications 2026 names the risks S08 watches for, chiefly ASI01 Agent Goal Hijack (malicious content alters the agent's objectives or decision path) and ASI02 Tool Misuse and Exploitation. S07's README describes the rule-based guard on the same topics; Sec. 2 compares the two.

**Bibliography**

- T. Akidau, R. Bradshaw, C. Chambers, S. Chernyak, R. J. Fernández-Moctezuma, R. Lax, S. McVeety, D. Mills, F. Perry, E. Schmidt, S. Whittle, "The Dataflow Model: A Practical Approach to Balancing Correctness, Latency, and Cost in Massive-Scale, Unbounded, Out-of-Order Data Processing," Proc. VLDB Endowment 8(12), 2015, pp. 1792–1803.
- B. Babcock, S. Babu, M. Datar, R. Motwani, J. Widom, "Models and Issues in Data Stream Systems," Proc. 21st ACM PODS, 2002, pp. 1–16. doi:10.1145/543613.543615.
- V. Chandola, A. Banerjee, V. Kumar, "Anomaly Detection for Discrete Sequences: A Survey," IEEE Trans. Knowledge and Data Engineering 24(5), 2012, pp. 823–839. doi:10.1109/TKDE.2010.235.
- M. Du, F. Li, G. Zheng, V. Srikumar, "DeepLog: Anomaly Detection and Diagnosis from System Logs through Deep Learning," Proc. ACM CCS, 2017. doi:10.1145/3133956.3134015.
- J. Gama, I. Žliobaitė, A. Bifet, M. Pechenizkiy, A. Bouchachia, "A Survey on Concept Drift Adaptation," ACM Computing Surveys 46(4), 2014, article 44. doi:10.1145/2523813.
- M. Kiran, P. Murphy, I. Monga, J. Dugan, S. S. Baveja, "Lambda Architecture for Cost-Effective Batch and Speed Big Data Processing," Proc. IEEE Int. Conf. Big Data, 2015.
- A. Lavin, S. Ahmad, "Evaluating Real-Time Anomaly Detection Algorithms – the Numenta Anomaly Benchmark," Proc. IEEE ICMLA, 2015, pp. 38–44.
- R. Laxhammar, G. Falkman, "Inductive Conformal Anomaly Detection for Sequential Detection of Anomalous Sub-Trajectories," Annals of Mathematics and Artificial Intelligence 74(1–2), 2015, pp. 67–94. doi:10.1007/s10472-013-9381-7.
- J. Liu, B. Ruan, X. Yang, Z. Lin, Y. Liu, Y. Wang, T. Wei, Z. Liang, "TraceAegis: Securing LLM-Based Agents via Hierarchical and Behavioral Anomaly Detection," arXiv:2510.11203, 2025 (preprint, not peer reviewed).

