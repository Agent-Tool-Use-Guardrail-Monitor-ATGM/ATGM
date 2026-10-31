# DSPOT: alarm thresholds from extreme value theory

**Owner:** Áron · **Paper:** A. Siffer, P.-A. Fouque, A. Termier, C. Largouët, *Anomaly Detection in Streams with Extreme Value Theory*, KDD 2017.

Turns a stream of anomaly scores (e.g. Online Isolation Forest, Markov "surprise") into alarms with a chosen false-alarm probability `q`, without labels, and follows drift in the scores.

## Status

- [x] GPD fit with Grimshaw's method (`domain/gpd.py`)
- [x] Streaming SPOT threshold updates (`domain/spot.py`)
- [ ] Drift-following DSPOT variant
- [ ] Offline evaluation runner
- [ ] Kafka adapter

## How it works

Scores above a high level `t` ("peaks") are modelled by a Generalized Pareto Distribution with shape γ and scale σ. `fit_gpd` finds the maximum-likelihood γ, σ with Grimshaw's reduction: it finds the roots of a one-dimensional function, implemented with NumPy only. `tail_quantile` then extrapolates to the alarm threshold `z_q` that normal scores exceed with probability `q`.

`SPOT` calibrates `t`, the GPD and `z_q` on an initial batch, then classifies each new score as an alarm (not learned), a peak (learned, threshold refitted) or normal. Measured on synthetic streams, it raises about 2-3x the requested false-alarm rate. The reason: excluded alarms hide the scores that would correct an early underestimate of the tail (see the docstring in `spot.py`).

## Run the tests

```bash
cd services/stream-processing/dspot
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -e ".[test]"
pytest
```

SciPy is used in the tests only, as an independent reference for the maximum-likelihood fit.
