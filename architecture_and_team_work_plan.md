# Architecture Plan: Agent Tool-Use Guardrail Monitor (ATGM)

## 1. System overview

<img width="460" height="522" alt="image" src="https://github.com/user-attachments/assets/af73dec6-6974-4698-8fde-c90cb6a95f91" />


## 2. Work split

### Architecture (OST)

| Member(s)                      | Component                               |
| ------------------------------ | --------------------------------------- |
| Maxim Aleshkov, Asmar Bagirova | Agent A (build calculator agent)        |
| Agnes Biborka, Fanni Orosz     | Agent B (build email draft agent)       |
| Aron Papp Balazs               | deployment (setup Docker, Kafka and DB) |

### Stream-mining algorithms (SM) and referneces

#### Maxim Aleshkov

- **Online-BLS — classifier, 2026**: maps features into fixed random features; incrementally update output weights using Cholesky-based calculations.
  - Paper: C. Lei, G.-Z. Chen, C. L. P. Chen, T. Zhang. _An accurate and efficient online broad learning system for data stream classification_. Science China Information Sciences 69, 139101 (2026). [DOI](https://doi.org/10.1007/s11432-025-4673-5). [2025 author preprint](https://arxiv.org/abs/2501.16932).
- **OPTWIN — retraining signal, 2024**: compares error means/variances across selected subwindows using t/F tests.
  - Paper: M. D. L. Tosi, M. Theobald. _OPTWIN: Drift Identification with Optimal Sub-Windows_. ICDEW 2024, 331–337. [DOI](https://doi.org/10.1109/ICDEW61823.2024.00049).

#### Fanni Orosz

- **Sliding-window frequent item mining**: similar to maintaining a rolling count of violations per tool/agent and alert on spikes.
  - https://link.springer.com/article/10.1007/s41019-017-0053-1
- **Online Isolation Forest**
  - https://proceedings.mlr.press/v235/leveni24a.html
  - https://www.sciencedirect.com/science/article/pii/S0925231217309864?via%3Dihu

#### Aron Papp Balazs

- **DSPOT: alarm thresholds, 2017**: model the tail of the score stream with extreme value theory. Excesses over a high level `t` follow a Generalized Pareto Distribution (shape γ, scale σ), fitted by MLE using Grimshaw's 1-D root-finding trick.
  - Paper: A. Siffer, P.-A. Fouque, A. Termier, C. Largouët. _Anomaly Detection in Streams with Extreme Value Theory_. KDD 2017, 1067–1075.
- **Adaptive Conformal Inference (ACI): triage, 2021**: turn classifier scores into prediction sets over {compliant, violating} with a target error rate α under distribution shift.
  - Paper: I. Gibbs, E. Candès. _Adaptive Conformal Inference Under Distribution Shift_. NeurIPS 2021.

#### Asmar Bagirova

- **Space-Saving**: keeps approximate counts of frequent tools, argument patterns, and violation types using limited memory, supporting rolling counts and spike detection.
  - Paper: Zhao et al. (2022), SpaceSaving±, VLDB: https://doi.org/10.14778/3514061.3514068
- **KSWIN**: monitors numeric features such as argument length, failure rate, or violation scores and detecting significant changes in agent behaviour. It could complement ADWIN, which would mainly monitor classifier errors using labels.
  - Paper: Raab et al. (2020), Reactive Soft Prototype Computing for Concept Drift Streams, https://doi.org/10.1016/j.neucom.2019.11.111

#### Agnes Biborka
(At least 2 points out of 3.)

- Real-time **allow-list policy check** on each tool call
  - WASP Top 10 for LLM Applications, LLM06:2025 Excessive Agency https://docs.bytehide.com/products/radar/sast/owasp/llm06-2025
  - CLAWGUARD: A RUNTIME SECURITY
    FRAMEWORK FOR TOOL-AUGMENTED LLM
    AGENTS AGAINST INDIRECT PROMPT INJECTION (https://arxiv.org/pdf/2604.11790)
- Real-time **sequence-order check against the learned Markov model** (Batch 3)
  - Statistical Learning for Anomaly Detection
    in Cloud Server Systems: A Multi-Order
    Markov Chain Framework (https://people.ece.ubc.ca/minchen/min_paper/2018/2018-IEEE-TCC-3-Zz.pdf)
  - Anomaly detection of event sequences using multiple temporal resolutions and Markov chains (https://link.springer.com/article/10.1007/s10115-019-01365-y)
- Distinguish **legitimate behavior drift from an actual attack**
  - Unsupervised Incremental Learning with Dual Concept Drift Detection for Identifying Anomalous Sequences (https://arxiv.org/pdf/2403.03576)

## 3. Timeline

We aim for early submission.

- Week 1 (October 19th - 25th): set up agents and environment
- Week 2 (October 26th - November 1st): implement one of the stream mining algorithms
- Week 3 (November 2nd - 8th): implement other stream mining algorithm + batch processing
- Week 4 (November 9th - 15th): solve issues, if any, create visualization
- Week 5 (November 16th - 22nd): write report and create presentation
- Week 6 (November 23rd - November 26th): final touches, practice presentation

Per team member plan for Week 1:

- build agent A (Maxim, Asmar)
- build agent B (Fanni, Agnes)
- build the scenario generator, create mock data, create the Kafka topics, set up Docker Compose with Postgres, InfluxDB and Grafana (Aron)

## 4. Additional plans

### 1. Data and event design

**Datasets (self-generated).**

- **Dataset 1:** Agent A (calculator, file-read) runs. Benign tasks include arithmetic and summarizing allowed files. Attacks include path traversal, reading secrets, and instructions hidden inside file contents.
- **Dataset 2:** Agent B (web-search, email-draft) runs. Benign tasks include research and drafting. Attacks include injected web pages that cause exfiltration emails or unauthorized recipients.
- Both come from a scenario generator that scripts tasks and injects attacks at a configurable rate. Attacks cover unauthorized tool, unsafe arguments, and out-of-order sequences. Ground-truth labels are stored separately and never sent downstream.

**Event schema:** `session_id, agent_id, step_idx, ts, tool, args, result_summary, toolset_version, scenario_id`. Separate `toolset-config` events record changes like "web-search added to Agent A v2".

**Partitioning:** key by `session_id` so one session's events stay ordered on one partition.

### 2. Batch layer

All batch jobs run as scheduled jobs reading labeled sessions from PostgreSQL. They publish versioned models to a registry (Postgres metadata plus a shared volume or MLflow), and stream stages hot-reload on a `model-updates` message.

- **B1:** binary classifier (e.g., logistic regression, random forest, gradient boosting) on sequence features.
- **B2:** multi-class violation-type classifier (unauthorized tool, unsafe args, out-of-order).
- **B3:** per-agent Markov chain of normal tool order (first-order, with a second-order comparison).
- **B4:** periodic retraining of all models on newly reviewed labels, with a champion/challenger check before promotion.

### 3. Storage

- **PostgreSQL:** raw and processed sessions, flags, review items, reviewer labels, model versions, policy and allow-lists.
- **InfluxDB:** time-series metrics such as tool-call rate, violation counts, drift scores, latency, and review backlog.

### 4. Visualization (Grafana)

Each member builds one dashboard with at least 2 panels according to their SM algorithms.

### 5. Deployment (Docker Compose, optional K8s)

Containers: `zookeeper/kafka` (or KRaft), `agent-a`, `agent-b`, `scenario-generator`, `stream-s1-s2` through `stream-s9-s10` (one image, different entrypoints), `batch-trainer` (CronJob), `postgres`, `influxdb`, `grafana`, `review-ui` (simple Flask/Streamlit for labeling). Use Compose for development and K8s manifests for the stretch goal.

### 6. Testing and experiments

- **Detection quality:** precision, recall and F1 per violation type, plus a confusion matrix, on held-out sessions.
- **Ablation:** allow-list only, then adding ML, then adding Markov, then adding drift handling. This shows the value of each layer, especially the order-based violations that per-call checks miss.
- **Drift vs. attack:** inject legitimate tool additions and attacks, and measure the false-positive rate on legitimate changes against attack detection.
- **Feedback loop:** F1 across retraining cycles 0 to N with simulated reviewer labels, including the effect of label noise.
- **System performance:** end-to-end latency (call to flag), throughput in events/s, and Kafka consumer lag under load.
- **Generalization:** test attack types unseen in training.
