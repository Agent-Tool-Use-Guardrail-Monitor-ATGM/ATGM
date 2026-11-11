# P4: sliding-window top-k of violations

Keeps the most frequent violations per agent over the last 10 minutes and sends an
alert when that list changes, e.g. when `anomaly:save_draft` suddenly becomes common.

Algorithm: Chen, Lv, Yu, Liu - *Sliding Window Top-K Monitoring over Distributed Data
Streams* (Data Science and Engineering, 2017). The Kafka partitions act as the paper's
monitoring nodes, and the service counts how many messages the protocol needs compared
with sending every update. The paper's partial resolution step is left out; every
constraint violation is solved with a global resolution.

## Topics

| Topic | In / out | What |
|---|---|---|
| `tool-calls.A`, `tool-calls.B` | in | tool calls, so an alarm can be matched to its tool |
| `alerts` | in | DSPOT alarms, counted as `anomaly:<tool>` |
| `flags` | in (later) | P1 / P3 violations, counted as `<violation_type>:<tool>` |
| `flags` | out | `topk.changed` (spike alert) and `topk.stats` (every minute) |


## Run and test

    docker compose up -d --build sliding-window-topk
    docker compose logs -f sliding-window-topk

    pip install pytest && pytest