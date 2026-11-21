"""Base Online-BLS (Lei et al., Algorithm 1), independent of stream delivery."""

from dataclasses import dataclass
from math import hypot

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import solve_triangular

Vector = NDArray[np.float64]


@dataclass(frozen=True)
class ModelState:
    factor: Vector
    weights: Vector
    class_counts: tuple[int, int] = (0, 0)


class OnlineBLS:
    def __init__(self, input_width: int, ridge: float = 1.0) -> None:
        if not np.isfinite(ridge) or ridge <= 0:
            raise ValueError("ridge must be positive and finite")
        self.ridge = ridge
        rng = np.random.default_rng(1)
        self.feature_weights = rng.normal(0, input_width ** -0.5, (input_width, 16))
        self.feature_bias = rng.uniform(-1, 1, 16)
        self.enhancement_weights = rng.normal(0, 16 ** -0.5, (16, 16))
        self.enhancement_bias = rng.uniform(-1, 1, 16)
        self.width = 32

    def initial_state(self) -> ModelState:
        return ModelState(np.eye(self.width) * np.sqrt(self.ridge), np.zeros((self.width, 2)))

    def expand(self, features: Vector) -> Vector:
        mapped = features @ self.feature_weights + self.feature_bias
        enhanced = np.tanh(mapped @ self.enhancement_weights + self.enhancement_bias)
        return np.concatenate((mapped, enhanced))

    def learn(self, state: ModelState, features: Vector, label: int) -> ModelState:
        if label not in (0, 1):
            raise ValueError("label must be 0 or 1")
        factor = state.factor.copy()
        extra = features.copy()
        # Rotate the extra column of [features, L] to zero, preserving its Gram matrix.
        for column in range(self.width):
            diagonal = factor[column, column]
            pivot = hypot(diagonal, extra[column])
            cosine = diagonal / pivot
            sine = extra[column] / pivot
            tail = factor[column:, column].copy()
            factor[column:, column] = cosine * tail + sine * extra[column:]
            extra[column:] = cosine * extra[column:] - sine * tail

        target = np.zeros(2)
        target[label] = 1
        residual = np.outer(features, target - features @ state.weights)
        forward = solve_triangular(factor, residual, lower=True)
        adjustment = solve_triangular(factor.T, forward)
        counts = state.class_counts
        return ModelState(factor, state.weights + adjustment,
                          (counts[0] + (label == 0), counts[1] + (label == 1)))
