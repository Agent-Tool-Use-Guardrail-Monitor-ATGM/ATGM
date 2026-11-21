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

## B4-02 champion comparison

Use a trusted, locally stored Agent B champion artifact and a separate labeled holdout that has never been used to train or select that champion. The job rejects session IDs shared by the challenger training set and the holdout. It compares both models on the same holdout and requires a strict macro F1 improvement.

```sh
python services/batch-processing/b4-retraining-and-model-registry/promote_b1.py --champion models/b1-binary/CHAMPION_VERSION --dataset-dir dataset/agent_b --training-scenarios TRAINING.jsonl --holdout-scenarios HOLDOUT.jsonl
```

Replace the scenario names with existing files in the B1 dataset layout. The default is a dry run. Add `--promote` to save a winning challenger to the local registry. Run promotion with a single registry writer and pass the current champion. A scorer restart can pick up the saved version through the existing B1 registry lookup. Kafka publication and automatic retraining remain separate B4 steps.

## B4-03 publish a promoted version

Install the B1 Kafka extra, point `KAFKA_BOOTSTRAP` at the broker, and run:

```sh
python services/batch-processing/b4-retraining-and-model-registry/publish_b1.py VERSION --models-dir models
```

Use the version directory name from B4-02's `saved_to` output. The scorer needs access to the same registry files. Publication sends `model.trained` to `model-updates` and succeeds only after broker acknowledgement. If delivery fails, retry this job with the same version.

## B4-04 report promoted versions

Export the champion and challenger macro F1 scores from the local registry:

```sh
python services/batch-processing/b4-retraining-and-model-registry/report_b1.py --models-dir models > b4-promotions.csv
```

Each row represents a saved B4 promotion and includes its holdout size. Rejected challengers and dry runs are absent because they have no saved promotion record. Compare the two scores within each row. Scores across rows may come from different holdouts.

For a paired score plot, install Matplotlib and add `--plot promotions.png` to the report command. Chart rounds follow the CSV row order. Each pair shares a holdout. The chart leaves rounds unconnected because their holdouts may differ.

## Remaining B4 work

Retrain B1–B3 regularly on the newest **reviewed** labels and only promote a new model if it is better than the current one (champion/challenger).

- **Schedule:** e.g. every hour while experiments run, or `docker compose run --rm b4` by hand.
- **Steps:** load data → train challenger (B1/B2/B3 code) → evaluate both models on the same held-out set → promote the winner.
- **Registry:** keep each model version with its metrics (a table in PostgreSQL, or files with a `registry.json`).
- **Announce:** publish the promoted model on `model-updates` (key = model name) so stream services hot-reload it. Proposed message in `../README.md`.
