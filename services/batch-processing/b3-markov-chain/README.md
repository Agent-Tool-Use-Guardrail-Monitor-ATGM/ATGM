# B3: Markov chain of the normal tool order

**Owner:** Agnes · **Status:** not started

Learn, per agent, how likely each tool is to follow the previous one in **normal** sessions. The stream stage "Markov order check" (P3) then scores live sessions by how surprising their order is.

- **Input:** tool sequences of sessions labelled normal (query in `../README.md`, `violating = false`), per `agent_id`. Add `<start>` and `<end>` states.
- **Model:** transition probabilities `P(next tool | previous tool)` (optionally 2nd order), with smoothing for unseen transitions.
- **Output:** the transition table (e.g. JSON) per agent, announced on `model-updates`. The stream stage publishes `-log P` as an `anomaly.scored` score, so DSPOT and ACI can use it directly.
