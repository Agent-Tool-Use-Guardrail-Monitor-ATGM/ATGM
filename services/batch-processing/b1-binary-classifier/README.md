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

## Agent A (experiment)

Agent A (DataLens) has 130 sessions in the datalens-collector export (copied to
`dataset/agent_a/all-events.jsonl`). Only 2 of them broke a rule (1 `policy_blocked`,
1 `answer_violation`), too few to train or cross-validate a classifier. So this experiment uses
the **planned** category as label: 57 `prompt_injected` vs. 73 `normal`. The question is whether
an injection attempt is visible in the tool calls, not whether a rule was broken.

`from_collector` pairs each `tool_call.requested` with its `completed` / `failed` event.
Arguments are only hashed in the export, so the tool's non-secret `features` stand in for them.

```bash
PYTHONPATH=src uv run python -m b1_classifier.main --agent A
PYTHONPATH=src uv run python -m b1_classifier.main --agent A --model logistic_regression
```

| Model | Accuracy | Macro F1 | CV5 macro F1 |
|---|---|---|---|
| Random forest | 0.364 | 0.354 | 0.497 |
| Logistic regression | 0.515 | 0.476 | 0.600 |

Agent A mostly resisted the injections (2 violations out of 57 attempts), so its tool calls look almost the same in both groups. Agent B, where violations
are common, reaches macro F1 0.92. The Agent A model is saved as `b1-binary-a` and not used on the
stream. The collector notes that paired scenarios should stay together when splitting; the random
split here may separate them, which at chance level does not inflate the results.