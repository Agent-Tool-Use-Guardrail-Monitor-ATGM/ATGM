# Dataset Description

- `dataset/scenarios` contain the scenarios that we generate with the generator
- `dataset/events` contains the events corresponding to the scenarios

### Call-level labels

`labels/call_labels_for_<file>`: one row per tool call, from the same rules as the session labels
(`label_events.py`). A session is violating exactly when at least one of its calls is flagged.

```json
{"event_id": "...", "scenario_id": "...", "session_call_index": 4, "tool_name": "save_draft",
 "flag": true, "rules": ["recipient_not_allowed"]}
```

`event_id` is the `tool_call.completed` event, so it matches `scored_event_id` in the `scores`
table: per-call detectors (online forest, S07) can be evaluated directly.

| File | Calls | Flagged |
|---|---|---|
| scenario_01_500 | 2969 | 585 (19.7%) |
| b4-holdout | 1091 | 199 (18.2%) |

92% of sessions are violating, but only ~20% of calls: usually just one call breaks a rule
(most often `save_draft` with an invented recipient).