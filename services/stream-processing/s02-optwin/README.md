# S02: OPTWIN drift detection on classifier errors

**Owner** Maxim · **Pipeline** P6 (review and retraining)

## Paper

M. D. L. Tosi and M. Theobald. *OPTWIN: Drift Identification with Optimal Sub-Windows*. IEEE ICDEW 2024, pp. 331–337. See Algorithm 1 and Equation 1 in Section III. [Published paper](https://doi.org/10.1109/ICDEW61823.2024.00049) · [Open paper](https://www.wis.ewi.tudelft.nl/assets/files/dbml2024/OPTWIN_DBML_2024.pdf).

## How OPTWIN works

S01 scores tool-call prefixes before feedback arrives. Once a reviewed session ends, S01 compares the original final-prefix prediction with the verdict and emits one error for a ready classifier. A correct prediction yields `0`. An incorrect prediction yields `1`. S01 writes that error to its outbox in the same transaction as the model update.

1. **Collect errors.** Keep the last 512 reviewed errors separately for each agent and model version. Wait for at least 30 errors before testing. Feedback is processed in arrival order.
2. **Split the window.** Equation 1 relates the smallest detectable mean shift to the t and F quantiles. Among feasible whole-number splits, choose the largest historical segment. This leaves the smallest recent segment that meets the chosen robustness target. If none qualifies, split in half. Cache the cut and F threshold by window length. Defaults are confidence `0.99`, quantile `confidence^(1/4)`, and robustness `0.5`.
3. **Test for deterioration.** Compare recent and historical error rates with a one-sided Welch t statistic and their variance ratio with an F threshold. A small standard-deviation floor handles constant windows. Emit drift when the recent mean is higher and either test exceeds its threshold, following the deterioration rule in Section III-D. Clear the window after the alert.

For example, replay 15 correct predictions followed by 15 incorrect ones for the same agent and model. At the 30th review, the split falls in the middle. The historical error rate is 0 and the recent rate is 1. Both segments are internally constant, so the increase is flagged by the t test. [Detector implementation](src/optwin/detector.py).

S02 measures the errors in reviewed sessions. Changes in review coverage or review delay can change that sample. The published statistical guarantees should not be assumed for this binary feedback stream.

## Kafka contract

| Direction | Topic | Event |
|---|---|---|
| Read | `classifier-errors` | `classifier.error` from `online_bls`, with agent, session, model version, and binary error |
| Write | `drift` | `drift.detected` with detector `optwin`, monitored value `online_bls_error`, and details containing the sub-window sizes, error rates, test statistics, and thresholds |

B4 can consume the alert to trigger retraining. Run one S02 replica. Its SQLite volume persists windows, reviewed-session deduplication keys, and alerts awaiting Kafka acknowledgement. Deduplication storage grows with the number of reviewed sessions. Kafka delivery is at least once and drift event IDs are stable across retries.

## Run and verify

From the ATGM root with the Compose environment configured:

```sh
docker compose up -d kafka
docker compose run --rm kafka-init
docker compose up -d --build online-bls optwin
```

From the S02 folder:

```sh
python -m pip install -e ".[test]"
python -m pytest -q
```
