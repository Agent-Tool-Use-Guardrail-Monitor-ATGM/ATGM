# S03: sliding-window top-k violation counts

**Owner:** Fanni · **Pipeline:** P4 (rolling counts and alerts) · **Status:** not started

**Paper:** Chen et al., Data Science and Engineering 2, 2017.

**Task:** Keep rolling violation counts per tool and agent over a sliding window, and report the top-k and spikes.

| | |
|---|---|
| **Reads** | `flags` (rule violations, ACI decisions), `alerts` (DSPOT alarms) |
| **Publishes** | `counts.summary` on `stats` (top-k per window, for dashboards), and the count per window as `anomaly.scored` on `scores` (detector `topk_counts`), so DSPOT decides when a count is a spike. |
| **Connects to** | S09 DSPOT puts the spike threshold on its counts. |

See `../README.md` for the message formats and the layout. `s04-online-forest/` is a complete example of a stage that reads tool calls and publishes scores.
