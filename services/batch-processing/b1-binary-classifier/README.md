# B1: binary classifier (compliant vs. violating)

**Owner:** Fanni · **Status:** done (first version, Agent B)

Trains a scikit-learn classifier that predicts whether a **session** is violating from its tool calls.

## Data

| Source | Tool calls | Label |
|---|---|---|
| `--source dataset` (default) | `dataset/agent_b/events/events_for_scenario_01_500.jsonl` | `dataset/agent_b/labels/...`: the rules the agent really broke (see `services/agent-b/src/agent_b/label_events.py`) |
| `--source db` | `analytics_db.agent_events` | `analytics_db.labels`: the newest reviewer verdict per session (`attack` = violating) |

The dataset files are the clean, fully labelled training data. `--source db` is for retraining on reviewed
labels from the running pipeline (B4). The scenario's `category` / `attack_type` (in `session.started`)
are never used as features.

## Features (per session)

Number of calls, distinct tools, failed calls, unknown tool used, tool counts, first and last tool,
pairs of consecutive tools (order), mean / max duration, longest gap between calls, argument lengths,
number of e-mail addresses, a credential or card number in an argument, and whether
`sensitive_content_scan` / `tone_checker` ran before `save_draft` and `get_current_datetime` before `get_free_slots`.

## Model and results

`DictVectorizer` + random forest (300 trees) or logistic regression, both with `class_weight="balanced"`,
because the classes are very uneven. 25 % stratified hold-out test set, plus 5-fold cross-validation.

Agent B dataset, 500 sessions (459 violating, 41 compliant):

| Model | Accuracy | Macro F1 | 5-fold macro F1 | Compliant precision / recall |
|---|---|---|---|---|
| Random forest | 0.976 | 0.922 | 0.919 | 0.82 / 0.90 |
| Logistic regression | 0.968 | 0.908 | 0.889 | 0.71 / 1.00 |

The test set has only 10 compliant sessions, so the per-class numbers move a lot between runs; the
cross-validation number is the steadier one.

## Run

    pip install -e ".[test]"
    python -m b1_classifier.main                          # dataset files, random forest
    python -m b1_classifier.main --model logistic_regression
    python -m b1_classifier.main --source db --announce   # analytics_db, then publish on model-updates
    pytest

Output: `models/b1-binary/<time>_<model>/model.joblib` and `metrics.json` (precision, recall, F1 per class,
confusion matrix). With `--announce` a `model.trained` event goes to `model-updates` (key `b1-binary`);
the exact message and the registry belong to B4.

## Agent A

Trained on the 500-session datalens-collector export (`dataset/agent_a/all-events.jsonl`), label from
the export's `label` column, the 214 `model_failure` runs are left out, 286 sessions, 72 violating.

| Model | Macro F1 | CV5 macro F1 |
|---|---|---|
| Random forest | 0.79 | 0.83 |
| Logistic regression | 0.84 | 0.86 |

**These numbers do not show that B1 detects Agent A violations.** 66 of the 72 violating labels have the
review note "Assigned to balance the dataset. The recorded evidence does not establish this label."
Those sessions are mostly runs where the agent asked for clarification (`request_clarification`,
outcome `needs_input`) or did not finish, while most compliant sessions completed normally. So the
model mainly learns "asked for clarification / did not finish", which is visible in the tool calls but
is not a violation. Only 6 violations (5 `policy_blocked`, 1 `answer_violation`) are backed by the
events, too few to train or evaluate on. The model is saved as `b1-binary-a` and not used on the stream.

**Independent holdout** (`b4-holdout`, 183 new Agent B sessions never used for training, 13 compliant):

| Model | Macro F1 | Compliant recall | Violating recall |
|---|---|---|---|
| Random forest | 0.961 | 1.000 | 0.988 |
| Logistic regression | 0.912 | 1.000 | 0.971 |

The holdout comes from the same agent and model, so it shows generalisation to new sessions of
this agent, not to an agent that behaves differently (see the timing limitation below).