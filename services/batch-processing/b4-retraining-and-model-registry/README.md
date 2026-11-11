# B4: periodic retraining and model registry

**Owner:** Maxim · **Status:** not started

Retrain B1–B3 regularly on the newest **reviewed** labels and only promote a new model if it is better than the current one (champion/challenger).

- **Schedule:** e.g. every hour while experiments run, or `docker compose run --rm b4` by hand.
- **Steps:** load data → train challenger (B1/B2/B3 code) → evaluate both models on the same held-out set → promote the winner.
- **Registry:** keep each model version with its metrics (a table in PostgreSQL, or files with a `registry.json`).
- **Announce:** publish the promoted model on `model-updates` (key = model name) so stream services hot-reload it. Proposed message in `../README.md`.
- **Report:** a plot of the metrics per retraining round shows whether the feedback loop improves the models.
