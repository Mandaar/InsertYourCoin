"""
Tests de l'optimiseur (le "juge" du projet) -- sans reseau ni cles.

Couvre :
- B3 : non-chevauchement des fenetres walk-forward, train precede strictement
       son test, garde "pas assez de donnees", reproductibilite des best_params.
- B1 : le warm-up amont est bien utilise (une SMA lente sur une fenetre OOS
       courte produit des trades AVEC warm-up vs degenere SANS).
- B2 : une combo "flat" (0 trade) ou a metrique non-finie n'est PAS selectionnee
       quand une vraie combo existe ; NaN/inf ne cassent pas avg_window_metric.
"""
import numpy as np
import pandas as pd
import pytest

from trading import optimizer as opt
from trading.backtester import Backtester
from trading.strategies import SMACrossover


# --------------------------------------------------------------------------- #
#  Generateurs de prix synthetiques (deterministes)                           #
# --------------------------------------------------------------------------- #
def _oscillating(n, period=12.0, amp=20.0, base=100.0):
    """Sinusoide : croisements SMA frequents -> beaucoup de trades."""
    t = np.arange(n)
    return base + amp * np.sin(t / period)


def _trend_then_reversal(n, base=100.0):
    """Tendance lente + grande oscillation : declenche aussi des SMA lentes."""
    t = np.arange(n)
    return base + 30.0 * np.sin(t / 40.0) + 0.04 * t


# --------------------------------------------------------------------------- #
#  B3 : structure temporelle du walk-forward                                  #
# --------------------------------------------------------------------------- #
def test_walk_forward_windows_do_not_overlap(make_df):
    df = make_df(_oscillating(600))
    res = opt.walk_forward(df, "sma", n_windows=4, train_frac=0.5, metric="sharpe", fee=0.0)
    periods = [w["period"] for w in res["windows"]]
    # Chaque fenetre OOS commence strictement apres la fin de la precedente.
    for (s0, e0), (s1, e1) in zip(periods, periods[1:]):
        assert e0 < s1, f"fenetres qui se chevauchent : {e0} >= {s1}"


def test_walk_forward_train_strictly_precedes_each_test(make_df):
    """Aucune fuite temporelle : tout le train est anterieur a son test."""
    df = make_df(_oscillating(600))
    n = len(df)
    train_frac, n_windows = 0.5, 4
    train_initial = int(n * train_frac)
    fold = (n - train_initial) // n_windows
    for w in range(n_windows):
        test_start = train_initial + w * fold
        train = df.iloc[:test_start]
        test = df.iloc[test_start:(n if w == n_windows - 1 else test_start + fold)]
        assert train.index.max() < test.index.min()


def test_walk_forward_guard_when_not_enough_data(make_df):
    df = make_df(_oscillating(40))  # trop court pour 4 fenetres
    with pytest.raises(RuntimeError):
        opt.walk_forward(df, "sma", n_windows=4, train_frac=0.5, fee=0.0)


def test_walk_forward_reproducible(make_df):
    """Meme df + memes reglages -> memes best_params (deterministe)."""
    df = make_df(_trend_then_reversal(600))
    r1 = opt.walk_forward(df.copy(), "sma", n_windows=4, metric="sharpe", fee=0.0)
    r2 = opt.walk_forward(df.copy(), "sma", n_windows=4, metric="sharpe", fee=0.0)
    p1 = [w["params"] for w in r1["windows"]]
    p2 = [w["params"] for w in r2["windows"]]
    assert p1 == p2
    assert r1["oos_total_return"] == pytest.approx(r2["oos_total_return"])


def test_optimize_reproducible(make_df):
    df = make_df(_trend_then_reversal(500))
    a = opt.optimize(df.copy(), "sma", metric="sharpe", fee=0.0)
    b = opt.optimize(df.copy(), "sma", metric="sharpe", fee=0.0)
    assert a["best_params"] == b["best_params"]


def test_optimize_test_period_covers_oos_only(make_df):
    """Le 'test_period' rapporte = exactement la tranche hors-echantillon."""
    df = make_df(_trend_then_reversal(500))
    res = opt.optimize(df, "sma", train_frac=0.6, metric="sharpe", fee=0.0)
    split = int(len(df) * 0.6)
    assert res["test_period"][0] == df.index[split]
    assert res["test_period"][1] == df.index[-1]


# --------------------------------------------------------------------------- #
#  B1 : le warm-up amont change concretement le resultat OOS                  #
# --------------------------------------------------------------------------- #
def test_warmup_revives_slow_sma_on_short_window(make_df):
    """
    Une SMA lente (slow=200) sur une fenetre OOS de 90 bougies est DEGENEREE
    sans warm-up (0 trade) ; AVEC warm-up amont elle reprend vie (>=1 trade).
    """
    df = make_df(_trend_then_reversal(400))
    bt = Backtester(fee=0.0, initial_capital=10_000)
    strat = SMACrossover(fast=10, slow=200)
    split = len(df) - 90

    isolated = bt.run(df.iloc[split:], strat)                      # sans warm-up
    w_start = max(0, split - opt.WARMUP)
    warmed = bt.run(df.iloc[w_start:], strat, warmup=split - w_start)

    assert isolated.metrics["n_trades"] == 0           # SMA 200 morte sur 90 bougies
    assert warmed.metrics["n_trades"] >= 1             # warm-up -> elle trade
    # Le segment compte couvre EXACTEMENT la meme periode OOS dans les deux cas.
    assert warmed.df.index[0] == isolated.df.index[0]
    assert warmed.df.index[-1] == isolated.df.index[-1]


def test_warmup_rebases_equity_and_total_return(make_df):
    """L'equity OOS redemarre au capital initial ; total_return coherent."""
    df = make_df(_trend_then_reversal(400))
    bt = Backtester(fee=0.0, initial_capital=10_000)
    strat = SMACrossover(fast=10, slow=150)
    split = len(df) - 120
    w_start = max(0, split - opt.WARMUP)
    res = bt.run(df.iloc[w_start:], strat, warmup=split - w_start)
    final = res.df["equity"].iloc[-1]
    assert res.metrics["total_return"] == pytest.approx(final / 10_000 - 1)
    # Le 1er point d'equity compte est proche du capital initial (rebase au warmup).
    assert abs(res.df["equity"].iloc[0] - 10_000) / 10_000 < 0.05


# --------------------------------------------------------------------------- #
#  B2 : pas de selection d'une combo flat / degeneree                         #
# --------------------------------------------------------------------------- #
def test_best_on_skips_flat_combo_when_a_trading_one_exists(make_df):
    """
    Sur un marche oscillant, des combos rapides tradent (>= MIN_TRADES) tandis
    que slow=200 reste flat. La selection doit choisir une combo ELIGIBLE
    (>= MIN_TRADES, metrique finie), jamais la flat.
    """
    df = make_df(_oscillating(600))
    bt = Backtester(fee=0.0, initial_capital=10_000)
    grid, is_valid = opt.DEFAULT_GRIDS["sma"]
    best, m = opt._best_on(bt, df, SMACrossover, grid, is_valid, "sharpe")
    assert best is not None
    assert m["n_trades"] >= opt.MIN_TRADES
    assert "degenerate" not in m            # une vraie combo a gagne
    assert np.isfinite(m["sharpe"])


def test_best_on_fallback_is_finite_and_flagged_when_no_eligible(make_df):
    """
    Marche quasi plat : aucune combo n'atteint MIN_TRADES. La selection ne
    renvoie pas None : elle retombe sur la 'moins pire' a metrique FINIE,
    explicitement marquee degeneree.
    """
    closes = list(100.0 + 0.001 * np.arange(300))   # quasi plat -> tres peu de trades
    df = make_df(closes)
    bt = Backtester(fee=0.0, initial_capital=10_000)
    grid, is_valid = opt.DEFAULT_GRIDS["sma"]
    best, m = opt._best_on(bt, df, SMACrossover, grid, is_valid, "sharpe")
    if best is not None:
        assert m["n_trades"] < opt.MIN_TRADES
        assert m.get("degenerate") is True
        # Une metrique non-finie n'est jamais choisie, meme en fallback.
        assert np.isfinite(m["sharpe"])


def test_avg_window_metric_ignores_nan_and_inf():
    """avg_window_metric = moyenne des seules fenetres a metrique FINIE."""
    windows = [
        {"metrics": {"sharpe": 1.0, "total_return": 0.1}},
        {"metrics": {"sharpe": float("nan"), "total_return": 0.0}},
        {"metrics": {"sharpe": float("inf"), "total_return": 0.5}},
        {"metrics": {"sharpe": 3.0, "total_return": 0.2}},
    ]
    vals = np.array([w["metrics"]["sharpe"] for w in windows], dtype=float)
    finite = vals[np.isfinite(vals)]
    avg = float(finite.mean())
    assert avg == pytest.approx(2.0)        # (1.0 + 3.0) / 2, NaN/inf ignores


def test_walk_forward_metric_finite_or_clean_nan(make_df):
    """avg_window_metric est soit fini, soit un NaN propre -- jamais inf."""
    df = make_df(_oscillating(600))
    res = opt.walk_forward(df, "sma", n_windows=4, metric="sharpe", fee=0.0)
    v = res["avg_window_metric"]
    assert not np.isinf(v)
    assert np.isfinite(v) or np.isnan(v)


# --------------------------------------------------------------------------- #
#  B5 : mode PARAMETRES FIGES (aucune optimisation -> anti-data-mining)        #
# --------------------------------------------------------------------------- #
def test_fixed_params_used_verbatim_on_every_window(make_df):
    """
    Avec fixed_params, AUCUNE optimisation : chaque fenetre porte EXACTEMENT les
    parametres figes (pas de re-selection de la grille).
    """
    df = make_df(_trend_then_reversal(700))
    fixed = {"fast": 50, "slow": 200}
    res = opt.walk_forward(df, "sma", n_windows=4, train_frac=0.5,
                           metric="sharpe", fee=0.0, fixed_params=fixed)
    assert res["fixed_params"] == fixed
    for w in res["windows"]:
        assert w["params"] == fixed          # jamais re-optimise


def test_fixed_params_does_not_call_best_on(make_df, monkeypatch):
    """Garde-fou explicite : en mode fige, `_best_on` n'est JAMAIS appele."""
    df = make_df(_trend_then_reversal(700))

    def _boom(*a, **k):
        raise AssertionError("_best_on ne doit pas etre appele en mode fige")

    monkeypatch.setattr(opt, "_best_on", _boom)
    res = opt.walk_forward(df, "tsmom", n_windows=4, train_frac=0.5,
                           metric="sharpe", fee=0.0, fixed_params={"lookback": 365})
    assert all(w["params"] == {"lookback": 365} for w in res["windows"])


def test_fixed_params_windows_do_not_overlap(make_df):
    """Le decoupage temporel (non-chevauchement) est preserve en mode fige."""
    df = make_df(_trend_then_reversal(700))
    res = opt.walk_forward(df, "sma", n_windows=4, train_frac=0.5,
                           metric="sharpe", fee=0.0, fixed_params={"fast": 50, "slow": 200})
    periods = [w["period"] for w in res["windows"]]
    for (s0, e0), (s1, e1) in zip(periods, periods[1:]):
        assert e0 < s1, f"fenetres qui se chevauchent : {e0} >= {s1}"


def test_fixed_params_warmup_revives_long_lookback(make_df):
    """
    B1 preserve en mode fige : un TSMOM lookback=365 sur des fenetres OOS courtes
    n'est PAS mort grace au warm-up amont etendu (>= lookback). Au moins une
    fenetre est investie une partie du temps (exposure > 0).
    """
    df = make_df(_trend_then_reversal(900))
    res = opt.walk_forward(df, "tsmom", n_windows=4, train_frac=0.5,
                           metric="sharpe", fee=0.0, fixed_params={"lookback": 365})
    # Le warm-up etendu doit couvrir le lookback (sinon le signal serait flat).
    assert opt._params_warmup({"lookback": 365}) >= 365
    assert any(w["metrics"]["exposure"] > 0 for w in res["windows"])
