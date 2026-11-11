# S05: SpaceSaving± frequent items

**Owner:** Asmar · **Pipeline:** P4 (rolling counts and alerts) · **Status:** not started

**Paper:** F. Zhao et al., *SpaceSaving±: An Optimal Algorithm for Frequency Estimation and Frequent Items in the Bounded-Deletion Model*, PVLDB 15(6), 2022.

**Task:** Approximate counts of the most frequent tools, argument patterns and violation types with bounded memory, including deletions (e.g. when a reviewed false alarm is withdrawn).

| | |
|---|---|
| **Reads** | `tool-calls.A`, `tool-calls.B` (tools, argument patterns); `labels` (violation types; `false_alarm` verdicts as deletions) |
| **Publishes** | `counts.summary` on `stats` (frequent items per window and agent, for dashboards and the report). |
| **Connects to** | B2 (violation types), dashboards. |

See `../README.md` for the message formats and the layout. `s04-online-forest/` is a complete example of a stage that reads tool calls and publishes scores.
