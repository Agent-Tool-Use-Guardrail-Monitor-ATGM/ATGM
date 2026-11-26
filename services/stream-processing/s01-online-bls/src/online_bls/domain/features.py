from dataclasses import dataclass
from hashlib import blake2b
from math import log1p

import numpy as np

BUCKETS = 16
INPUT_WIDTH = 2 * BUCKETS + 4


def tool_bucket(name: str) -> int:
    return blake2b(name.encode("utf-8"), digest_size=1).digest()[0] % BUCKETS


@dataclass
class Prefix:
    length: int = 0
    failures: int = 0
    previous_tool: str = ""
    repetitions: int = 0

    def observe(self, tool: str, failed: bool, argument_count: int) -> np.ndarray:
        features = np.zeros(INPUT_WIDTH)
        features[tool_bucket(tool)] = 1
        if self.previous_tool:
            features[BUCKETS + tool_bucket(self.previous_tool)] = 1
        self.length += 1
        self.failures += failed
        self.repetitions = self.repetitions + 1 if self.previous_tool == tool else 1
        self.previous_tool = tool
        features[-4:] = (
            log1p(min(self.length, 100)) / log1p(100),
            self.failures / self.length,
            log1p(min(self.repetitions, 100)) / log1p(100),
            log1p(min(argument_count, 16)) / log1p(16),
        )
        return features
