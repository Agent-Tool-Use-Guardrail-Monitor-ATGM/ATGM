# S01: Online-BLS online classifier

**Owner:** Maxim · **Pipeline:** P2 (ML classification) · **Status:** not started

**Paper:** C. Lei, G.-Z. Chen, C. L. P. Chen, T. Zhang, *An accurate and efficient online broad learning system for data stream classification*, Science China Information Sciences 69, 2026 (preprint arXiv:2501.16932).

**Task:** Classify session prefixes as compliant vs. violating, updating the model with every reviewed label (Cholesky-based incremental update of the output weights).

| | |
|---|---|
| **Reads** | `tool-calls.A`, `tool-calls.B` (features per session prefix); `labels` (reviewed verdicts to learn from) |
| **Publishes** | `anomaly.scored` on `scores`, with `score` = probability of violation (detector `online_bls`). DSPOT and ACI can use it directly. |
| **Connects to** | S02 OPTWIN watches this classifier's error stream. |

See `../README.md` for the message formats and the layout. `s04-online-forest/` is a complete example of a stage that reads tool calls and publishes scores.
