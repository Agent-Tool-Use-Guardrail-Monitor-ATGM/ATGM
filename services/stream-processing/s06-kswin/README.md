# S06: KSWIN change detection on numeric features

**Owner:** Asmar · **Pipeline:** P5 (drift vs. attack) · **Status:** not started

**Paper:** C. Raab, M. Heusinger, F.-M. Schleif, *Reactive Soft Prototype Computing for Concept Drift Streams*, Neurocomputing 416, 2020.

**Task:** Kolmogorov–Smirnov windowing test on numeric features (argument length, failure rate, anomaly scores) to detect changes in agent behaviour.

| | |
|---|---|
| **Reads** | `tool-calls.A`, `tool-calls.B` (argument length, success); optionally `scores` |
| **Publishes** | `drift.detected` on `drift` (detector `kswin`, `monitored`: which feature, per agent). |
| **Connects to** | Drift vs. attack (S08 alternative), ACI step-size reset, dashboards. |

See `../README.md` for the message formats and the layout. `s04-online-forest/` is a complete example of a stage that reads tool calls and publishes scores.
