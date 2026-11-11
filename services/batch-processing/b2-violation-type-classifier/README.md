# B2: violation-type classifier

**Owner:** Asmar · **Status:** not started

For violating sessions, predict **which kind** of violation it is:

| `violation_type` | Meaning |
|---|---|
| `unauthorized_tool` | a tool outside the agent's toolset |
| `unsafe_args` | dangerous arguments (secrets, path traversal, too many columns) |
| `skipped_check` | a required check was not run |
| `out_of_order` | tools called in the wrong order |

- **Input:** sessions with `verdict = 'attack'` from `labels` (or `attack_type` from `scenario_db.ground_truth`), joined with their tool calls (query in `../README.md`).
- **Features (ideas):** the same as B1, plus the tool sequence (bigrams), argument length and "secret-looking" arguments.
- **Model:** scikit-learn multi-class classifier; report a confusion matrix and per-class F1.
- **Output:** the trained model and metrics; announced on `model-updates` (see B4).
