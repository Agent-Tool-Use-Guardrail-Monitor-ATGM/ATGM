"""Generalized Pareto Distribution (GPD) fitting for peaks over a threshold.

By the Pickands-Balkema-de Haan theorem, the excesses Y = X - t of a score stream X
over a high level t approximately follow a GPD with shape gamma and scale sigma:

    P(Y > y) = (1 + gamma * y / sigma) ** (-1 / gamma)      (gamma != 0)
    P(Y > y) = exp(-y / sigma)                               (gamma == 0)

The parameters are estimated by maximum likelihood using Grimshaw's reduction,
as in SPOT/DSPOT (Siffer et al., KDD 2017): with x = gamma / sigma, every
interior maximum of the likelihood is a root of the one-dimensional function

    w(x) = u(x) * v(x) - 1,
    u(x) = mean(1 / (1 + x * Y)),   v(x) = 1 + mean(log(1 + x * Y)),

and a root x* gives gamma = v(x*) - 1 and sigma = gamma / x*.
This module uses NumPy only; the root finding is implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_GRID_POINTS = 200      # grid used to locate sign changes of w(x) in each interval
_BISECTION_STEPS = 80   # enough for double precision on any bracket
_EPS = 1e-8


@dataclass(frozen=True)
class GPDFit:
    gamma: float           # shape: > 0 heavy tail, 0 exponential tail, < 0 bounded tail
    sigma: float           # scale, > 0
    log_likelihood: float


def log_likelihood(excesses: np.ndarray, gamma: float, sigma: float) -> float:
    """GPD log-likelihood of positive excesses; -inf outside the valid support."""
    y = np.asarray(excesses, dtype=float)
    if sigma <= 0:
        return -np.inf
    n = y.size
    if abs(gamma) < 1e-12:
        return float(-n * np.log(sigma) - y.sum() / sigma)
    z = 1.0 + gamma * y / sigma
    if np.any(z <= 0):
        return -np.inf
    return float(-n * np.log(sigma) - (1.0 + 1.0 / gamma) * np.log(z).sum())


def _w(x: float, y: np.ndarray) -> float:
    s = 1.0 + x * y
    u = np.mean(1.0 / s)
    v = 1.0 + np.mean(np.log(s))
    return float(u * v - 1.0)


def _roots(y: np.ndarray, lo: float, hi: float) -> list[float]:
    """All sign changes of w on a grid over [lo, hi], each refined by bisection.

    The interval lies on one side of 0 and can span many orders of magnitude,
    so the grid is logarithmic in |x|.
    """
    if not lo < hi:
        return []
    if lo > 0:
        xs = np.geomspace(lo, hi, _GRID_POINTS)
    else:
        xs = -np.geomspace(-lo, -hi, _GRID_POINTS)
    ws = np.array([_w(x, y) for x in xs])
    roots = []
    for a, b, wa, wb in zip(xs[:-1], xs[1:], ws[:-1], ws[1:]):
        if wa == 0.0:
            roots.append(float(a))
        elif wa * wb < 0:
            for _ in range(_BISECTION_STEPS):
                m = 0.5 * (a + b)
                wm = _w(m, y)
                if wa * wm <= 0:
                    b = m
                else:
                    a, wa = m, wm
            roots.append(0.5 * (a + b))
    return roots


def fit_gpd(excesses: np.ndarray) -> GPDFit:
    """Maximum-likelihood GPD fit of strictly positive excesses (Grimshaw's method)."""
    y = np.asarray(excesses, dtype=float).ravel()
    if y.size < 2:
        raise ValueError("need at least 2 excesses to fit a GPD")
    if np.any(~np.isfinite(y)) or np.any(y <= 0):
        raise ValueError("excesses must be finite and strictly positive")

    y_min, y_max, y_mean = y.min(), y.max(), y.mean()

    # Candidate 1: gamma = 0 (exponential tail), whose MLE is sigma = mean excess.
    candidates = [(0.0, float(y_mean))]

    # Candidates 2..: roots of w(x) on the two intervals given by Grimshaw:
    # x in (-1/y_max, 0) for gamma < 0, and x in (0, 2*(mean - min)/min^2) for gamma > 0.
    neg_lo, neg_hi = -1.0 / y_max + _EPS, -_EPS
    pos_lo, pos_hi = _EPS, 2.0 * (y_mean - y_min) / (y_min ** 2)
    for x in _roots(y, neg_lo, neg_hi) + _roots(y, pos_lo, pos_hi):
        gamma = float(np.mean(np.log1p(x * y)))       # gamma = v(x) - 1
        if gamma != 0:
            sigma = gamma / x
            if sigma > 0:
                candidates.append((gamma, sigma))

    best = max(candidates, key=lambda c: log_likelihood(y, *c))
    return GPDFit(gamma=best[0], sigma=best[1], log_likelihood=log_likelihood(y, *best))


def tail_quantile(t: float, fit: GPDFit, q: float, n: int, n_peaks: int) -> float:
    """Alarm threshold z_q with P(X > z_q) = q, given n observations, n_peaks of them above t.

        z_q = t + sigma/gamma * ((q * n / n_peaks) ** (-gamma) - 1)     (gamma != 0)
        z_q = t - sigma * log(q * n / n_peaks)                          (gamma == 0)
    """
    if not 0 < q < 1:
        raise ValueError("q must be in (0, 1)")
    if not 0 < n_peaks <= n:
        raise ValueError("need 0 < n_peaks <= n")
    r = q * n / n_peaks
    if abs(fit.gamma) < 1e-12:
        return float(t - fit.sigma * np.log(r))
    return float(t + fit.sigma / fit.gamma * (r ** (-fit.gamma) - 1.0))
