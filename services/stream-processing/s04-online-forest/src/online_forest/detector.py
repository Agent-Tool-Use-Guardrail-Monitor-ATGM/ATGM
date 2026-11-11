import numpy as np

from capymoa.anomaly import OnlineIsolationForest
from capymoa.instance import Instance
from capymoa.stream import Schema

from .config import (
    NUM_TREES,
    WINDOW_SIZE,
    MAX_LEAF_SAMPLES,
    RANDOM_SEED,
    ANOMALY_THRESHOLD,
)
from .features import FEATURE_NAMES, extract_features


class OnlineForestDetector:

    def __init__(self):
        self.schema = Schema.from_custom(
            feature_names=FEATURE_NAMES,
            dataset_name="ATGMToolCalls",
        )

        self.model = OnlineIsolationForest(
            schema=self.schema,
            num_trees=NUM_TREES,
            window_size=WINDOW_SIZE,
            max_leaf_samples=MAX_LEAF_SAMPLES,
            random_seed=RANDOM_SEED,
        )

        self.samples_seen = 0
        self.warmup_samples = WINDOW_SIZE // 4

    def process(self, event: dict) -> dict:
        values = extract_features(event)
        x = np.asarray(values, dtype=float)

        instance = Instance.from_array(self.schema, x)

        score = float(self.model.score_instance(instance))

        self.model.train(instance)

        self.samples_seen += 1

        is_anomaly = (
            self.samples_seen >= self.warmup_samples
            and score >= ANOMALY_THRESHOLD
        )

        return {
            "anomaly_score": score,
            "is_anomaly": is_anomaly,
            "samples_seen": self.samples_seen,
        }