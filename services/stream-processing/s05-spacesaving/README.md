# S05: Integrated SpaceSaving± Frequent-Item Summaries

**Owner:** Asmar  
**Pipeline:** P4 (rolling counts and alerts)  
**Status:** Implemented; unit tests passing

**Paper:** F. Zhao et al., *SpaceSaving±: An Optimal Algorithm for Frequency Estimation and Frequent Items in the Bounded-Deletion Model*, PVLDB 15(6), 2022.

## Overview

S05 implements the Integrated SpaceSaving± algorithm to estimate frequent items in a data stream using bounded memory.

It tracks:
- Frequently used tool names.
- Frequently occurring argument patterns.
- Violation types identified through review labels.

The algorithm supports both insertions and deletions. When a reviewed tool call is labelled as a false alarm, its tracked contributions are withdrawn from the corresponding summary.

## Input Topics

| Topic | Information used |
|---|---|
| `tool-calls.A` | Tool calls from agent A |
| `tool-calls.B` | Tool calls from agent B |
| `labels` | Review verdicts and violation types |

Tool-call events contribute to tool-name and argument-pattern counts.

Review labels are handled as follows:
- `attack`: increments the corresponding violation-type count.
- `false_alarm`: withdraws the matching tool-call and argument-pattern contributions.

A label is matched using `scored_event_id`. If its original contribution is no longer retained, the service skips the update rather than assigning it to an incorrect window.

## Output

**Topic:** `stats`  
**Event type:** `counts.summary`  
**Detector:** `spacesaving`

Each summary contains:
- `agent_id`
- `window_start`
- `window_end`
- `top`: the most frequent items and their estimated counts.

## Implementation

The implementation is organized into three main parts:

- `domain/integrated_spacesaving.py`: Core Integrated SpaceSaving± algorithm.
- `adapters/events.py`: Parsing and validation of tool-call and review-label events.
- `service.py`: Event processing, per-agent/window summaries, deduplication, retention and review-label handling.
- `main.py`: Kafka consumer and producer entry point.

The algorithm maintains separate bounded sketches for each agent, item category and time window.

## Configuration

| Environment variable | Default | Description |
|---|---:|---|
| `KAFKA_BOOTSTRAP` | `localhost:29092` | Kafka broker address |
| `KAFKA_GROUP_ID` | `spacesaving-consumer` | Consumer group |
| `TOPICS` | `tool-calls.A,tool-calls.B,labels` | Input topics |
| `COUNTER_CAPACITY` | `100` | Maximum counters per sketch |
| `WINDOW_SECONDS` | `60` | Time-window duration |
| `TOP_K` | `10` | Maximum number of summary items |

The service also uses bounded event-tracking stores and retains a configurable number of recent windows.

## Tests

Run the unit tests from this directory:

```powershell
python -m pytest tests -v
```

The test suite covers:
- SpaceSaving± insertion and deletion.
- Counter capacity and replacement.
- Event parsing and validation.
- Tool-call and argument-pattern counting.
- False-alarm withdrawals and attack labels.
- Duplicate-event handling.
- Per-agent isolation.
- Invalid configuration and missing review contributions.

**Current test result:** 26 passed.

## Docker

Build the service image from the repository root:

```powershell
docker compose build spacesaving
```

Run it with the full ATGM stack:

```powershell
docker compose up -d spacesaving
```

See `../README.md` for the overall stream-processing architecture and message formats.
