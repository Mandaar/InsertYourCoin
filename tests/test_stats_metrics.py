"""
Tests du Sharpe deflate / probabiliste (trading/stats_metrics.py) -- Brique 3.

Aucun reseau, aucune cle, aucune dependance scipy : on verifie les proprietes
MONOTONES attendues du PSR/DSR (Bailey & Lopez de Prado) et la propagation propre
des cas degeneres (NaN/inf). On verifie aussi la CDF/PPF normale maison.
"""
import math

import numpy as np
import pytest

from trading.stats_metrics import (
    probabilistic_sharpe_ratio, deflated_sharpe_ratio, expected_max_sharpe,
    _norm_cdf, _norm_ppf,
)


# --------------------------------------------------------------------------- #
#  Helpers normaux (sans scipy)                                               #
# --------------------------------------------------------------------------- #
def test_norm_cdf_known_values():
    assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-12)
    assert _norm_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert _norm_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)


def test_norm_ppf_is_inverse_of_cdf():
    for p in (0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99):
        assert _norm_cdf(_norm_ppf(p)) == pytest.approx(p, abs=1e-6)


def test_norm_ppf_edges():
    assert _norm_ppf(0.0) == -math.inf
    assert _norm_ppf(1.0) == math.inf
    assert math.isnan(_norm_ppf(float("nan")))


# --------------------------------------------------------------------------- #
#  PSR : monotonie                                                            #
# --------------------------------------------------------------------------- #
def test_psr_increases_with_sharpe():
    lo = probabilistic_sharpe_ratio(0.05, n_obs=250)
    hi = probabilistic_sharpe_ratio(0.20, n_obs=250)
    assert hi > lo
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0


def test_psr_increases_with_n_obs():
    few = probabilistic_sharpe_ratio(0.10, n_obs=30)
    many = probabilistic_sharpe_ratio(0.10, n_obs=2000)
    assert many > few          # plus d'observations -> plus de confiance que SR > 0


def test_psr_decreases_with_higher_benchmark():
    base = probabilistic_sharpe_ratio(0.15, n_obs=300, sharpe_benchmark=0.0)
    high = probabilistic_sharpe_ratio(0.15, n_obs=300, sharpe_benchmark=0.10)
    assert high < base


def test_psr_positive_sharpe_above_half():
    # Un Sharpe positif observe -> PSR > 0.5 (plus de 50% de chance que le vrai SR > 0).
    assert probabilistic_sharpe_ratio(0.10, n_obs=500) > 0.5


# --------------------------------------------------------------------------- #
#  DSR : penalise le nombre d'essais                                          #
# --------------------------------------------------------------------------- #
def test_dsr_below_psr_when_multiple_trials():
    # variance des Sharpe PAR OBSERVATION entre essais (~1/n_obs, ordre realiste).
    sr, n, var = 0.15, 500, 0.002
    psr = probabilistic_sharpe_ratio(sr, n_obs=n)
    dsr = deflated_sharpe_ratio(sr, n_obs=n, n_trials=50, variance_trials_sharpe=var)
    assert dsr < psr           # tester 50 combos releve le seuil -> proba plus faible


def test_dsr_monotone_decreasing_in_trials():
    sr, n, var = 0.15, 500, 0.002
    d10 = deflated_sharpe_ratio(sr, n_obs=n, n_trials=10, variance_trials_sharpe=var)
    d100 = deflated_sharpe_ratio(sr, n_obs=n, n_trials=100, variance_trials_sharpe=var)
    d1000 = deflated_sharpe_ratio(sr, n_obs=n, n_trials=1000, variance_trials_sharpe=var)
    assert d10 > d100 > d1000  # plus d'essais -> seuil plus haut -> DSR plus faible


def test_dsr_equals_psr_when_single_trial():
    sr, n = 0.12, 400
    psr = probabilistic_sharpe_ratio(sr, n_obs=n)
    dsr = deflated_sharpe_ratio(sr, n_obs=n, n_trials=1)
    assert dsr == pytest.approx(psr)   # 1 essai -> SR0 = 0 -> DSR == PSR


def test_expected_max_sharpe_increases_with_trials():
    s10 = expected_max_sharpe(10, 1.0)
    s1000 = expected_max_sharpe(1000, 1.0)
    assert s1000 > s10 > 0.0
    assert expected_max_sharpe(1, 1.0) == 0.0      # 1 essai : aucun seuil
    assert expected_max_sharpe(100, 0.0) == 0.0    # variance nulle : aucun seuil


# --------------------------------------------------------------------------- #
#  Cas degeneres -> NaN propre (jamais d'exception, jamais d'inf silencieux)  #
# --------------------------------------------------------------------------- #
def test_psr_nan_sharpe_returns_nan():
    assert math.isnan(probabilistic_sharpe_ratio(float("nan"), n_obs=300))
    assert math.isnan(probabilistic_sharpe_ratio(float("inf"), n_obs=300))


def test_psr_too_few_obs_returns_nan():
    assert math.isnan(probabilistic_sharpe_ratio(0.1, n_obs=1))
    assert math.isnan(probabilistic_sharpe_ratio(0.1, n_obs=0))


def test_dsr_nan_sharpe_returns_nan():
    assert math.isnan(deflated_sharpe_ratio(float("nan"), n_obs=300, n_trials=20))


def test_psr_always_in_unit_interval_when_defined():
    for sr in (-0.5, -0.1, 0.0, 0.1, 0.5, 2.0):
        for n in (5, 50, 500):
            v = probabilistic_sharpe_ratio(sr, n_obs=n)
            assert 0.0 <= v <= 1.0 and np.isfinite(v)
