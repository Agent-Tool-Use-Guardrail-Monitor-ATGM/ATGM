import numpy as np
from online_bls.domain.model import OnlineBLS


def test_incremental_factor_and_weights_match_batch_ridge():
    rng = np.random.default_rng(7)
    model = OnlineBLS(input_width=5, ridge=0.3)
    state = model.initial_state()
    features, labels = [], []
    for index in range(30):
        # Repeated rows exercise rank-deficient input before regularization.
        broad = model.expand(np.ones(5) if index < 8 else rng.normal(size=5))
        label = index % 2
        features.append(broad)
        labels.append(np.eye(2)[label])
        state = model.learn(state, broad, label)
        matrix = np.stack(features)
        gram = matrix.T @ matrix + 0.3 * np.eye(model.width)
        expected = np.linalg.solve(gram, matrix.T @ labels)
        np.testing.assert_allclose(state.factor, np.linalg.cholesky(gram), atol=1e-11)
        np.testing.assert_allclose(state.weights, expected, atol=1e-11)
