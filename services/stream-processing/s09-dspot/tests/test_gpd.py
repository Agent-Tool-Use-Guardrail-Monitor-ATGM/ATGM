import numpy as np
import pytest
from scipy import stats

from dspot.domain.gpd import GPDFit, fit_gpd, log_likelihood, tail_quantile


def sample_gpd(gamma: float, sigma: float, n: int, seed: int) -> np.ndarray:
    """Exact GPD samples by inverting the survival function."""
    u = np.random.default_rng(seed).uniform(size=n)
    if gamma == 0:
        return -sigma * np.log(u)
    return sigma / gamma * (u ** (-gamma) - 1.0)


@pytest.mark.parametrize("gamma, sigma", [(0.3, 1.0), (0.1, 0.04), (0.0, 2.0), (-0.2, 0.5)])
def test_recovers_known_parameters(gamma, sigma):
    y = sample_gpd(gamma, sigma, n=20_000, seed=1)
    fit = fit_gpd(y)
    assert fit.gamma == pytest.approx(gamma, abs=0.04)
    assert fit.sigma == pytest.approx(sigma, rel=0.06)


@pytest.mark.parametrize("gamma, sigma, seed", [(0.3, 1.0, 2), (0.0, 1.0, 3), (-0.25, 1.0, 4), (0.15, 0.05, 5)])
def test_is_a_maximum_likelihood_estimate(gamma, sigma, seed):
    """The fit is at least as likely as the true parameters and matches SciPy's MLE."""
    y = sample_gpd(gamma, sigma, n=500, seed=seed)
    fit = fit_gpd(y)
    assert fit.log_likelihood >= log_likelihood(y, gamma, sigma) - 1e-9
    c, _, scale = stats.genpareto.fit(y, floc=0)
    assert fit.log_likelihood >= log_likelihood(y, c, scale) - 1e-6


def test_small_peak_sets_still_fit():
    """SPOT starts from few peaks (e.g. 2% of an initial batch)."""
    y = sample_gpd(0.2, 0.05, n=20, seed=6)
    fit = fit_gpd(y)
    assert fit.sigma > 0 and np.isfinite(fit.log_likelihood)


def test_tail_quantile_matches_gpd_quantile():
    """With every observation a peak at t = 0, z_q is the exact (1 - q) GPD quantile."""
    fit = GPDFit(gamma=0.2, sigma=1.5, log_likelihood=0.0)
    z = tail_quantile(t=0.0, fit=fit, q=1e-3, n=1000, n_peaks=1000)
    assert z == pytest.approx(stats.genpareto.isf(1e-3, 0.2, scale=1.5))
    exp_fit = GPDFit(gamma=0.0, sigma=1.5, log_likelihood=0.0)
    assert tail_quantile(0.0, exp_fit, 1e-3, 1000, 1000) == pytest.approx(stats.expon.isf(1e-3, scale=1.5))


def test_tail_quantile_extrapolates_beyond_t():
    """2% peaks above t = 0.45, risk 1e-4: the alarm level lies well above t."""
    fit = GPDFit(gamma=0.1, sigma=0.04, log_likelihood=0.0)
    z = tail_quantile(t=0.45, fit=fit, q=1e-4, n=1000, n_peaks=20)
    assert 0.6 < z < 0.8


@pytest.mark.parametrize("bad", [[], [1.0], [1.0, -0.5], [1.0, 0.0], [1.0, np.nan]])
def test_rejects_invalid_excesses(bad):
    with pytest.raises(ValueError):
        fit_gpd(np.array(bad))
