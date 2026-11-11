# B1: binary classifier (compliant vs. violating)

**Owner:** Fanni · **Status:** not started

Train a scikit-learn classifier that predicts whether a **session** is violating, from its tool calls.

- **Input:** one row per session from `analytics_db` (query in `../README.md`); label `violating`.
- **Features (ideas):** number of calls, tool counts per tool name, unknown tool used, first/last tool, mean and max duration, any failed call, argument length.
- **Model:** start simple (logistic regression or random forest); report precision, recall and F1 on a held-out set.
- **Output:** the trained model file and its metrics; announced on `model-updates` (see B4).
