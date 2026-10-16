# Architecture Plan: Agent Tool-Use Guardrail Monitor (ATGM)

## 1. System overview

ATGM wraps two LLM agents with an instrumented tool layer. Every tool call becomes an event on Kafka. Stream processors check each call and each session in real time, a batch layer trains the models on stored logs, and a review loop feeds human labels back into retraining.

```
┌─────────────────┐   ┌─────────────────┐
│ Agent A         │   │ Agent B         │   Dataset 1 / Dataset 2
│ calc, file-read │   │ web-search,     │   (normal + prompt-injected runs
│ (LangChain)     │   │ email-draft     │    from a scenario generator)
│                 │   │ (CrewAI)        │
└───────┬─────────┘   └────────┬────────┘
        │  instrumented tool wrapper (JSON events)
        ▼                      ▼
┌──────────────────────────────────────────────────┐
│ KAFKA: tool-calls.A | tool-calls.B | toolset-    │
│ config | flags | alerts | review-queue | labels  │
│ | model-updates                                  │
└───────┬──────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────┐
│ STREAM PROCESSING (Python consumers / Faust,     │
│ River, scikit-learn models loaded from registry) │
│ S1 enrich+sessionize → S2 allow-list/args        │
│ → S3 features → S4 binary clf → S5 type clf      │
│ → S6 Markov order → S7 rolling counts/spikes     │
│ → S8 drift-vs-attack → S9 fusion+triage          │
│ → S10 feedback ingest                            │
└───────┬──────────────────────┬───────────────────┘
        ▼                      ▲ (new models)
┌───────────────────┐   ┌──────┴────────────────────┐
│ STORAGE           │──▶│ BATCH (K8s CronJob)       │
│ PostgreSQL:       │   │ B1 binary clf             │
│ sessions, labels, │   │ B2 violation-type clf     │
│ reviews, models   │   │ B3 Markov model           │
│ InfluxDB: metrics │   │ B4 periodic retrain       │
└───────┬───────────┘   └───────────────────────────┘
        ▼
┌──────────────────────────────────────────────────┐
│ GRAFANA: 5 dashboards (one per member)           │
└──────────────────────────────────────────────────┘
```

## 2. Data and event design

**Datasets (self-generated).**
- **Dataset 1:** Agent A (calculator, file-read) runs. Benign tasks include arithmetic and summarizing allowed files. Attacks include path traversal, reading secrets, and instructions hidden inside file contents.
- **Dataset 2:** Agent B (web-search, email-draft) runs. Benign tasks include research and drafting. Attacks include injected web pages that cause exfiltration emails or unauthorized recipients.
- Both come from a scenario generator that scripts tasks and injects attacks at a configurable rate. Attacks cover unauthorized tool, unsafe arguments, and out-of-order sequences. Ground-truth labels are stored separately and never sent downstream.

**Event schema:** `session_id, agent_id, step_idx, ts, tool, args, result_summary, toolset_version, scenario_id`. Separate `toolset-config` events record changes like "web-search added to Agent A v2".

**Partitioning:** key by `session_id` so one session's events stay ordered on one partition.

## 3. Stream processing stages

There are 10 stages, two per team member. Pipelines 1 to 6 from the topic description map onto them.

| Stage | Description | Pipeline | Tech |
|---|---|---|---|
| S1 | Validation, enrichment, sessionization (session windows) | – | Faust/Kafka consumer |
| S2 | Per-call allow-list and argument rules (path, domain, recipient) | P1 | Python rules |
| S3 | Sequence features: n-grams, last-k tools, arg stats | P2 | River/Pandas |
| S4 | Binary compliant/violating classification | P2 | scikit-learn model |
| S5 | Violation-type classification | P2 | scikit-learn model |
| S6 | Markov transition-probability check on tool order | P3 | custom, River-updated |
| S7 | Sliding-window violation counts per tool/agent, spike alerts | P4 | windowed aggregation, ADWIN/z-score |
| S8 | Drift-vs-attack: tool-frequency drift detection correlated with `toolset-config` events | P5 | River (ADWIN, Page-Hinkley) |
| S9 | Score fusion and triage into flag/uncertain/pass | P6 | confidence thresholds |
| S10 | Reviewed-label ingestion and retrain trigger | P6 | Kafka → Postgres |

**S8 logic (the core novelty):**
1. Detect distribution shift in tool usage with ADWIN, and in bigram distributions with divergence tests.
2. Look up recent `toolset-config` changes. If the new tool or transition appears after a registered change and fits the changed toolset, label it **explained drift**: auto-allow and update the allow-list and Markov model incrementally.
3. Otherwise label it **unexplained deviation**, which goes to review.
4. Test the hard case of attacks that mimic drift, such as an injected call to a tool that was just legitimately added.

**S9 fusion:** combine S2, S4, S5, S6 and S8 outputs into a final verdict. Rule violations are hard flags, and ML or Markov disagreement or low confidence goes to the review queue.

## 4. Batch layer

All batch jobs run as scheduled jobs reading labeled sessions from PostgreSQL. They publish versioned models to a registry (Postgres metadata plus a shared volume or MLflow), and stream stages hot-reload on a `model-updates` message.

- **B1:** binary classifier (e.g., logistic regression, random forest, gradient boosting) on sequence features.
- **B2:** multi-class violation-type classifier (unauthorized tool, unsafe args, out-of-order).
- **B3:** per-agent Markov chain of normal tool order (first-order, with a second-order comparison).
- **B4:** periodic retraining of all models on newly reviewed labels, with a champion/challenger check before promotion.

## 5. Storage

- **PostgreSQL:** raw and processed sessions, flags, review items, reviewer labels, model versions, policy and allow-lists.
- **InfluxDB:** time-series metrics such as tool-call rate, violation counts, drift scores, latency, and review backlog.

## 6. Visualization (Grafana)

Each member builds one dashboard with at least 2 panels:

1. **Live stream:** per-agent tool-call rate and tool mix (S1/S2).
2. **Detection quality:** flagged violations over time and classifier confidence distribution (S3/S4).
3. **Violation types:** counts by type and violation spikes per tool/agent (S5/S7).
4. **Order and drift:** order-violation alerts, transition heatmap, and drift-vs-attack indicator with `toolset-config` markers (S6/S8).
5. **Review queue:** queue size and age, label throughput, and model-version performance across retrain cycles (S9/S10).

## 7. Deployment (Docker Compose, optional K8s)

Containers: `zookeeper/kafka` (or KRaft), `agent-a`, `agent-b`, `scenario-generator`, `stream-s1-s2` through `stream-s9-s10` (one image, different entrypoints), `batch-trainer` (CronJob), `postgres`, `influxdb`, `grafana`, `review-ui` (simple Flask/Streamlit for labeling). Use Compose for development and K8s manifests for the stretch goal.

## 8. Testing and experiments

- **Detection quality:** precision, recall and F1 per violation type, plus a confusion matrix, on held-out sessions.
- **Ablation:** allow-list only, then adding ML, then adding Markov, then adding drift handling. This shows the value of each layer, especially the order-based violations that per-call checks miss.
- **Drift vs. attack:** inject legitimate tool additions and attacks, and measure the false-positive rate on legitimate changes against attack detection.
- **Feedback loop:** F1 across retraining cycles 0 to N with simulated reviewer labels, including the effect of label noise.
- **System performance:** end-to-end latency (call to flag), throughput in events/s, and Kafka consumer lag under load.
- **Generalization:** train on Agent A, evaluate on Agent B, and test attack types unseen in training.

## 9. Work split (5 members)

| Member | Stages | Batch | Dashboard | Also |
|---|---|---|---|---|
| M1 | S1, S2 | – | Live stream | Agents, scenario generator, Kafka |
| M2 | S3, S4 | B1 | Detection quality | Feature engineering |
| M3 | S5, S7 | B2 | Types and spikes | Attack variety |
| M4 | S6, S8 | B3 | Order and drift | Markov and drift research |
| M5 | S9, S10 | B4 | Review queue | Storage, deployment, review UI |

## 10. Candidate references

Aim for 10 to 15 sources from the last 10 years, with 2 or 3 older exceptions. Verify each citation before using it.
- Greshake et al. (2023), indirect prompt injection in LLM-integrated apps.
- AgentDojo (Debenedetti et al., 2024), InjecAgent (Zhan et al., 2024), and Agent Security Bench (2024) for attack scenarios and benchmarks.
- ToolEmu (Ruan et al., 2024), on risks of tool-using agents.
- River (Montiel et al., 2021, JMLR), on online ML.
- ADWIN (Bifet & Gavaldà, 2007) and Gama et al. (2014), concept drift survey, as acceptable older exceptions.
- Papers on Markov-based and n-gram anomaly detection for system-call or sequence data, and on Kafka-based stream processing architectures.

## 11. Timeline (6 weeks)

The plan overlaps the stream and batch work and starts experiments and documentation early. Ordering follows the dependency chain: the data and Kafka backbone first, then models, then the novelty stages, and finally the loop and evaluation.

### Week 1: Foundation
- M1 builds both agents, the scenario generator, the Kafka topics and the event schema, and gets S1/S2 working end to end.
- M5 sets up Docker Compose with Postgres, InfluxDB and Grafana.
- M2, M3 and M4 agree on the feature set and labels, and start reading the key papers. M2 drafts the feature extraction against a first batch of generated logs.
- **Milestone:** events flow from both agents through Kafka into Postgres.

### Week 2: Models and first stages
- Generate the full dataset (normal, adversarial, and order-violation runs).
- M2 trains B1 and builds S3/S4. M3 trains B2 and builds S5. M4 trains B3 and builds S6.
- M5 builds the model registry and hot-reload mechanism, and the first draft of the review UI.
- M1 finishes the baseline "Live stream" dashboard.
- **Milestone:** all three batch models are trained and the per-call and sequence checks run on the live stream.

### Week 3: Remaining stream stages
- M3 builds S7 (rolling counts and spikes). M4 builds S8 (drift vs. attack, including the `toolset-config` handling).
- M5 builds S9 (fusion and triage) and S10 (feedback ingest).
- Everyone builds a first version of their dashboard.
- **Milestone:** the full S1 to S10 pipeline runs end to end. This is the integration checkpoint, so start integration tests this week rather than later.

### Week 4: Feedback loop and integration
- M5 implements B4 with the champion/challenger check, and the review loop is closed with simulated reviewer labels.
- M4 and M1 create the hard drift-mimicking attack scenarios.
- Fix integration bugs, tune thresholds, and finalize all five dashboards.
- **Milestone:** one complete retraining cycle runs automatically and the new model is promoted and hot-reloaded.

### Week 5: Experiments and report
- Run the experiments: per-type metrics, the ablation, drift vs. attack, feedback-loop cycles, system performance, and generalization.
- In parallel, each member writes their section of the report: abstract, introduction, datasets, architecture, testing. Collect and verify the 10 to 15 references.
- **Milestone:** results tables and figures are final, and the report has a full first draft.

### Week 6: Finalization and presentation
- Polish the report in Github (or Overleaf), including a grammar check.
- Build the 10-slide deck, including the slide on who did what.
- Clean up the repos (code and data), write the README with run instructions, and rehearse the presentation.
- **Milestone:** submission-ready repositories, report and slides.
- Start the report skeleton and the reference list in Week 2, so Week 5 is writing up results and not writing from scratch.
- Generate the datasets in Weeks 1 and 2 with a fixed random seed, so the experiments in Week 5 are reproducible and nobody is waiting for new data.
