"""
Tests du moteur de backtest : pas de lookahead, frais appliques, metriques
coherentes, et effet de chaque outil de risque (stop / trailing / take-profit /
sizing par volatilite).
"""
import numpy as np
import pandas as pd
import pytest

from trading.backtester import Backtester
from trading.strategies import build_strategy


class FixedSignal:
    """Strategie deterministe pour piloter les scenarios de test."""
    def __init__(self, signals):
        self._signals = [int(s) for s in signals]

    def generate_signals(self, df):
        return pd.Series(self._signals[:len(df)], index=df.index, dtype=int)

    def __str__(self):
        return "Fixed"


def _oscillating(n):
    t = np.arange(n)
    return 100 + 0.3 * t + 12 * np.sin(t / 7.0)


def _volatile(n, seed=0):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.05, n)))  # ~5%/jour -> vol annuelle elevee


# --------------------------------------------------------------------------- #
#  Pas de lookahead + frais                                                    #
# --------------------------------------------------------------------------- #
def test_no_lookahead_executes_at_next_open(make_df):
    df = make_df([100, 100, 100, 110, 120, 130],
                 opens=[100, 100, 100, 105, 115, 125])
    strat = FixedSignal([0, 0, 1, 1, 1, 1])  # le signal passe a 1 a la bougie 2
    res = Backtester(fee=0.0, initial_capital=10_000).run(df, strat)
    first = res.trades[0]
    # decision a la cloture de la bougie 2 -> execution a l'OUVERTURE de la bougie 3
    assert first["entry_time"] == df.index[3]
    assert first["entry_price"] == df["open"].iloc[3]


def test_round_trip_applies_fee_twice(make_df):
    df = make_df([100, 100, 100, 100, 100], opens=[100, 100, 100, 100, 100])
    strat = FixedSignal([0, 1, 1, 0, 0])  # entree puis sortie sur signal, prix constant
    fee = 0.0026
    res = Backtester(fee=fee, initial_capital=10_000).run(df, strat)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t["reason"] == "signal"
    assert t["pnl"] == pytest.approx((1 - fee) ** 2 - 1, rel=1e-9)


def test_fees_reduce_final_equity(make_df):
    df = make_df([100, 101, 102, 101, 103, 104, 102, 105])
    strat = FixedSignal([0, 1, 0, 1, 0, 1, 0, 1])  # plusieurs aller-retours
    no_fee = Backtester(fee=0.0, initial_capital=10_000).run(df, strat)
    with_fee = Backtester(fee=0.01, initial_capital=10_000).run(df, strat)
    assert with_fee.metrics["final_equity"] < no_fee.metrics["final_equity"]


# --------------------------------------------------------------------------- #
#  Coherence des metriques                                                     #
# --------------------------------------------------------------------------- #
def test_metrics_are_coherent(make_df):
    df = make_df(_oscillating(160))
    res = Backtester(initial_capital=10_000).run(df, build_strategy("sma"))
    m = res.metrics
    assert m["n_trades"] == len(res.trades)
    assert 0.0 <= m["exposure"] <= 1.0
    assert m["total_return"] == pytest.approx(m["final_equity"] / 10_000 - 1)
    assert m["max_drawdown"] <= 0.0
    assert np.isfinite(m["sharpe"]) and np.isfinite(m["volatility"])
    assert 0.0 <= m["win_rate"] <= 1.0


# --------------------------------------------------------------------------- #
#  Stop-loss / trailing stop / take-profit                                     #
# --------------------------------------------------------------------------- #
def test_stop_loss_cuts_losses(make_df):
    df = make_df(closes=[100, 100, 100, 88, 72, 60],
                 opens=[100, 100, 100, 95, 80, 65],
                 highs=[100, 100, 100, 96, 82, 67],
                 lows=[100, 100, 100, 85, 68, 58])
    strat = FixedSignal([0, 1, 1, 1, 1, 1])
    with_stop = Backtester(fee=0.0, initial_capital=10_000, stop_loss=0.10).run(df, strat)
    no_stop = Backtester(fee=0.0, initial_capital=10_000).run(df, strat)
    assert any(t["reason"] == "stop" for t in with_stop.trades)
    assert with_stop.metrics["final_equity"] > no_stop.metrics["final_equity"]


def test_trailing_stop_locks_in_gains(make_df):
    df = make_df(closes=[100, 103, 112, 128, 142, 150, 135, 115],
                 opens=[100, 100, 110, 120, 140, 150, 140, 120],
                 highs=[100, 105, 115, 130, 145, 152, 142, 122],
                 lows=[100, 98, 108, 118, 138, 148, 130, 110])
    strat = FixedSignal([0, 1, 1, 1, 1, 1, 1, 1])
    trail = Backtester(fee=0.0, initial_capital=10_000, trailing_stop=0.10).run(df, strat)
    none = Backtester(fee=0.0, initial_capital=10_000).run(df, strat)
    assert any(t["reason"] == "trailing" for t in trail.trades)
    assert trail.metrics["final_equity"] > none.metrics["final_equity"]


def test_take_profit_exits_at_target(make_df):
    df = make_df(closes=[100, 100, 100, 115, 128],
                 opens=[100, 100, 100, 110, 125],
                 highs=[100, 100, 100, 118, 130],
                 lows=[100, 99, 99, 108, 120])
    strat = FixedSignal([0, 1, 1, 1, 1])
    res = Backtester(fee=0.0, initial_capital=10_000, take_profit=0.20).run(df, strat)
    objectifs = [t for t in res.trades if t["reason"] == "objectif"]
    assert objectifs
    # sortie au prix cible : +20% sur l'entree (open de la bougie 2 = 100)
    assert objectifs[0]["exit_price"] == pytest.approx(120.0)


def test_tightest_stop_wins_when_both_active(make_df):
    # Stop fixe -5% (=> 95) plus serre que le trailing -20% des l'entree : il prime.
    df = make_df(closes=[100, 100, 100, 92, 80],
                 opens=[100, 100, 100, 96, 85],
                 highs=[100, 100, 101, 97, 86],
                 lows=[100, 99, 99, 93, 78])
    strat = FixedSignal([0, 1, 1, 1, 1])
    res = Backtester(fee=0.0, initial_capital=10_000,
                     stop_loss=0.05, trailing_stop=0.20).run(df, strat)
    assert res.trades[0]["reason"] == "stop"
    assert res.trades[0]["exit_price"] == pytest.approx(95.0)


# --------------------------------------------------------------------------- #
#  Dimensionnement par volatilite                                             #
# --------------------------------------------------------------------------- #
def test_size_series_full_when_disabled(make_df):
    df = make_df(_oscillating(80))
    bt = Backtester()  # POSITION_SIZING None par defaut
    arr = bt._size_series(df, bt._periods_per_year(df))
    assert np.allclose(arr, 1.0)


def test_size_series_vol_reduces_fraction_when_volatile(make_df):
    df = make_df(_volatile(80))
    bt = Backtester(position_sizing="vol", target_vol=0.20, vol_window=20, max_fraction=1.0)
    arr = bt._size_series(df, bt._periods_per_year(df))
    assert (arr <= 1.0 + 1e-9).all()        # plafonnee a max_fraction (pas de levier)
    assert (arr[20:] < 1.0).any()           # vol > cible => on investit moins de 100%


def test_vol_sizing_lowers_equity_volatility(make_df):
    df = make_df(_volatile(120))
    strat = FixedSignal([1] * 120)          # toujours investi des que possible
    full = Backtester(fee=0.0, initial_capital=10_000).run(df, strat)
    sized = Backtester(fee=0.0, initial_capital=10_000, position_sizing="vol",
                       target_vol=0.15, vol_window=20, max_fraction=1.0).run(df, strat)
    assert sized.metrics["volatility"] < full.metrics["volatility"]
    assert sized.metrics["exposure"] <= full.metrics["exposure"] + 1e-9
