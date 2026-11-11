# S08: Markov order check

**Owner:** Agnes · **Pipeline:** P3 (order check) · **Status:** not started

**Paper:** Sha et al., IEEE Transactions on Cloud Computing 6(2), 2018; Boldt et al., Knowledge and Information Systems 62, 2020. Alternative stage: drift vs. attack, Li et al., arXiv:2403.03576, 2024.

**Task:** Score each tool call by how surprising its position in the sequence is under the learned Markov chain of normal tool order: `score = -log P(tool | previous tool)`.

| | |
|---|---|
| **Reads** | `tool-calls.A`, `tool-calls.B`; the B3 model announced on `model-updates` |
| **Publishes** | `anomaly.scored` on `scores` (detector `markov`). DSPOT and ACI use it directly; it catches `out_of_order` and `unauthorized_tool`, which the Isolation Forest cannot see. |
| **Connects to** | B3 trains its model (`services/batch-processing/b3-markov-chain`). |

See `../README.md` for the message formats and the layout. `s04-online-forest/` is a complete example of a stage that reads tool calls and publishes scores.
