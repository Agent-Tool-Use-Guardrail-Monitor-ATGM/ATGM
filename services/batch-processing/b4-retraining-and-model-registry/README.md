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

To train the challenger on reviewed Agent B sessions from PostgreSQL, set `ANALYTICS_DB` and replace `--training-scenarios TRAINING.jsonl` with `--source db`. Keep the independent `--holdout-scenarios` file. The same overlap check and strict macro F1 gate apply, and the report records the training source.

## B4-03 publish a promoted version

Install the B1 Kafka extra, point `KAFKA_BOOTSTRAP` at the broker, and run:

```sh
python services/batch-processing/b4-retraining-and-model-registry/publish_b1.py VERSION --models-dir models
```

Use the version directory name from B4-02's `saved_to` output. The scorer needs access to the same registry files. Publication sends `model.trained` to `model-updates` and succeeds only after broker acknowledgement. If delivery fails, retry this job with the same version.

Verified in isolated Docker Compose with a fixture model. The scorer started with an empty registry, then loaded the exact published version without restarting. Wait for the scorer's Kafka subscription to become active before publishing to a newly started scorer. Broker acknowledgement confirms publication. The scorer log confirms reload.

## B4-04 report promoted versions

Export the champion and challenger macro F1 scores from the local registry:

```sh
python services/batch-processing/b4-retraining-and-model-registry/report_b1.py --models-dir models > b4-promotions.csv
```

Each row represents a saved B4 promotion and includes its holdout size. Rejected challengers and dry runs are absent because they have no saved promotion record. Compare the two scores within each row. Scores across rows may come from different holdouts.

For a paired score plot, install Matplotlib and add `--plot promotions.png` to the report command. Chart rounds follow the CSV row order. Each pair shares a holdout. The chart leaves rounds unconnected because their holdouts may differ.

## Scheduled B1 retraining

Build the image once and run the one-shot job from the ATGM checkout:

```sh
docker compose build b4-retrain
docker compose run --rm b4-retrain
```

The job loads the current random forest from the shared registry, trains with reviewed PostgreSQL data, and announces a winning challenger. An initial B1 model and independent `events/events_for_b4-holdout.jsonl` and `labels/labels_for_b4-holdout.jsonl` files under `dataset/agent_b` are required. Keep holdout sessions out of reviewed training data. Supply a fresh holdout after promotion. Scheduled runs skip holdouts containing any session already recorded by a B4 promotion. For models saved before holdout IDs were recorded, supply a holdout known to be independent.

For an hourly run on the Linux Compose host, add this to the deployment user's crontab with the actual checkout path. The lock prevents two scheduled runs from writing the registry concurrently. Run other registry writers outside this schedule.

```cron
0 * * * * cd /opt/atgm && flock -n /tmp/atgm-b4.lock docker compose run -T --rm b4-retrain
```

If Kafka fails after saving a winner, the next scheduled run retries publication before training. Broker acknowledgement is recorded beside the model. A retry can send the same version again, which the scorer can reload.

Each completed comparison with `--announce` also publishes a `model.evaluated` event to `stats`, including both macro-F1 scores, holdout size and promotion eligibility. The storage sink stores it in `other_events`. The B4 Grafana dashboard displays these comparisons, including rejected challengers.

## Remaining B4 work

Retrain B1–B3 regularly on the newest **reviewed** labels and only promote a new model if it is better than the current one (champion/challenger).

- **Steps:** load data → train challenger (B1/B2/B3 code) → evaluate both models on the same held-out set → promote the winner.
- **Registry:** keep each model version with its metrics (a table in PostgreSQL, or files with a `registry.json`).
- **Announce:** publish the promoted model on `model-updates` (key = model name) so stream services hot-reload it. Proposed message in `../README.md`.
