# S03: sliding-window top-k violation counts

**Owner:** Fanni · **Pipeline:** P4 (rolling counts and alerts) · **Status:** done (without partial resolution)

**Paper:** Chen, Lv, Yu, Liu - *Sliding Window Top-K Monitoring over Distributed Data Streams*,
Data Science and Engineering 2, 2017.

**Task:** Keep rolling violation counts per tool and agent over a sliding window, and report the
top-k and spikes.

| | |
|---|---|
| **Reads** | `alerts` (DSPOT alarms), `flags` (S07 `violation.flagged`, ACI `decision.made`), `tool-calls.A/B` (to find the tool of an alarm) |
| **Publishes** | `anomaly.scored` on `scores` (detector `topk_counts`): the window count of each violation, so DSPOT decides when a count is a spike. `counts.summary` on `stats`: the top-k per agent once per time slot, with the protocol's message count. |
| **Connects to** | S09 DSPOT puts the spike threshold on the counts. |

## What is counted

| Input | Counted as |
|---|---|
| DSPOT alarm on a tool call | `anomaly:<tool>` (`anomaly:<session>` for session-level scores) |
| `violation.flagged` from S07 | `<rule>:<tool>` |
| ACI `decision.made` with decision `flag` | `aci:flag` |

Several alarms on the same call (different detectors) count once. Alarms on our own
`topk_counts` scores are ignored, so the counts do not feed back into themselves.

## How it works

The three Kafka partitions act as the paper's monitoring nodes. Each node counts violations in
its own time-based sliding window (20 slots of 30 s = 10 minutes). A coordinator keeps the global
top-k and gives every node revision factors, so each node ranks the items like the global top-k.
A node only alerts the coordinator when its local ranking breaks; the coordinator then collects
all counts, picks the new top-k and sends new revision factors (global resolution). Within
`epsilon` the top-k is always correct. The paper's partial resolution step is left out.

`counts.summary` reports `messages` (what the protocol needed) next to `naive_messages` (every
arrival and expiry sent to the coordinator), which shows the communication saving.

## Run and test

    docker compose up -d --build sliding-top-k
    docker compose logs -f sliding-top-k

    pip install pytest && pytest

Settings: `TOPK_K` (3), `TOPK_SLOT_SECONDS` (30), `TOPK_UNITS` (20), `TOPK_EPSILON` (5), `TOPK_NODES` (3).
