# B2: Violation-Type Classifier

**Owner:** Asmar  
**Status:** Implemented — tests passing, model trained and saved.

## Objective

B2 classifies observed Agent B sessions according to the types of policy violations detected in their tool-call behavior.

The classifier uses **multilabel classification**, because one session can contain more than one violation type.

## Violation categories

| Violation type | Meaning |
|---|---|
| `unauthorized_tool` | Use of a tool that is not permitted by the agent's policy. |
| `unsafe_args` | Unsafe or disallowed arguments, including secrets and unauthorized recipients or contacts. |
| `skipped_check` | A required check was never performed before a tool call. |
| `out_of_order` | A required check was performed, but only after the tool call that needed it. |

## Dataset and labeling

- **Input:** Agent B scenario, event, and label JSONL files.
- Labels are derived from actual `violated_rules` and policy prerequisite checks.
- Planned scenario metadata, such as `attack_type`, is not used as a target or model feature.
- Features are extracted from observed tool calls.
- Normal sessions with no violations are retained as negative examples.

From the 500 available sessions:
- 12 sessions had no tool calls and were excluded.
- 10 sessions had only violation types outside the B2 taxonomy and were excluded.
- 478 sessions were used for training and evaluation.

## Features

The classifier uses observable tool-call features, including:

- Number of calls and distinct tools.
- Failed calls and tool usage counts.
- Tool sequence bigrams.
- Argument length.
- Secret-looking argument detection.
- Email address counts.
- Tool execution order and check-before-action indicators.
- Call duration and time gaps.

## Model and evaluation

- **Library:** scikit-learn.
- **Model:** Random Forest with 300 estimators.
- **Task:** Multilabel classification.
- **Evaluation:** 75% training / 25% test split.
- **Metrics:** Per-class precision, recall, F1-score, confusion matrices, and subset accuracy.

### Initial evaluation results

| Violation type | F1-score | Test support |
|---|---:|---:|
| `unsafe_args` | 0.986 | 111 |
| `skipped_check` | 0.976 | 21 |
| `out_of_order` | 1.000 | 4 |
| `unauthorized_tool` | Not available | 0 |

**Subset accuracy:** 0.967

**Important limitation:** No actual `unauthorized_tool` examples were present in the available dataset. This class is included in the output taxonomy but was not trained. The `out_of_order` result is based on only four positive test examples and should be interpreted cautiously.

These are initial results from a random holdout split, not a measurement of performance on a completely new dataset.

## Output and integration

- Trained model and evaluation metrics are saved under `models/b2-violation-type/`.
- Optional model announcement to Kafka topic `model-updates` is supported through the `--announce` argument.
- Kafka integration follows the B4 model-update interface.

## Running

From the repository root:

```bash
python -m b2_classifier.main
```

To use Logistic Regression:

```bash
python -m b2_classifier.main --model logistic_regression
```

To publish the model update to Kafka:

```bash
python -m b2_classifier.main --announce
```

## Tests

All 15 unit tests pass, covering dataset loading, behavioral labels, feature extraction, model training, evaluation, and model storage.