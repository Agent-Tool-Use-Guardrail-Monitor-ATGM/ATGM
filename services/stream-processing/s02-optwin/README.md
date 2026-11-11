# S02: OPTWIN drift detection on classifier errors

**Owner:** Maxim · **Pipeline:** P6 (review and retraining) · **Status:** not started

**Paper:** M. D. L. Tosi, M. Theobald, *OPTWIN: Drift Identification with Optimal Sub-Windows*, ICDEW 2024, 331–337.

**Task:** Detect when the classifier's error rate changes (compare error means and variances across sub-windows with t/F tests) and signal that retraining is needed.

| | |
|---|---|
| **Reads** | S01's predictions joined with `labels` (prediction correct or not, per reviewed session) |
| **Publishes** | `drift.detected` on `drift` (detector `optwin`, `monitored: "online_bls_error"`). Triggers B4 retraining; could also reset ACI's step size. |
| **Connects to** | S01 (its input), B4 (retraining). |

See `../README.md` for the message formats and the layout. `s04-online-forest/` is a complete example of a stage that reads tool calls and publishes scores.
