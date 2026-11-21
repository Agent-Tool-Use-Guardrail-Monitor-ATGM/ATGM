# B4: periodic retraining and model registry

**Owner:** Maxim · **Status:** B1 evaluation implemented

## B1 evaluation

The evaluation command fits a logistic regression baseline and a random forest challenger on the same training sessions. Both are scored on the same stratified 25% holdout using macro F1. Session IDs are sorted before the seeded split so input order does not affect the result.

Run from the ATGM root:

```sh
python -m pip install -e "./services/batch-processing/b1-binary-classifier[db]"
python services/batch-processing/b4-retraining-and-model-registry/evaluate_b1.py --dataset-dir dataset/agent_b
```

Omit `--dataset-dir` and set `ANALYTICS_DB` to evaluate reviewed Agent B sessions. The command prints evaluation metrics. The baseline is fitted for the comparison, so this report does not compare against a deployed champion.

## Remaining B4 work

Retrain B1–B3 regularly on the newest **reviewed** labels and only promote a new model if it is better than the current one (champion/challenger).

- **Schedule:** e.g. every hour while experiments run, or `docker compose run --rm b4` by hand.
- **Steps:** load data → train challenger (B1/B2/B3 code) → evaluate both models on the same held-out set → promote the winner.
- **Registry:** keep each model version with its metrics (a table in PostgreSQL, or files with a `registry.json`).
- **Announce:** publish the promoted model on `model-updates` (key = model name) so stream services hot-reload it. Proposed message in `../README.md`.
- **Report:** a plot of the metrics per retraining round shows whether the feedback loop improves the models.
