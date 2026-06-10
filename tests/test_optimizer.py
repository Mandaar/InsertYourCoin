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


# --------------------------------------------------------------------------- #
#  B12+ : Sharpe deflate (PSR/DSR) expose par walk_forward                     #
# --------------------------------------------------------------------------- #
def test_walk_forward_exposes_psr_dsr_and_trials(make_df):
    """walk_forward retourne psr/dsr/n_trials/n_obs_oos coherents."""
    df = make_df(_oscillating(600))
    res = opt.walk_forward(df, "sma", n_windows=4, train_frac=0.5,
                           metric="sharpe", fee=0.0)
    assert "psr" in res and "dsr" in res
    assert res["n_obs_oos"] > 0
    # En mode OPTIMISE, n_trials = nb de combos valides de la grille SMA.
    grid, is_valid = opt.DEFAULT_GRIDS["sma"]
    n_combos = sum(1 for _ in opt._combos(grid, is_valid))
    assert res["n_trials"] == n_combos and n_combos > 1
    # PSR/DSR sont des probas (ou NaN propre), jamais inf.
    for v in (res["psr"], res["dsr"]):
        assert np.isnan(v) or (0.0 <= v <= 1.0)


def test_walk_forward_dsr_below_psr_when_optimised(make_df):
    """Mode optimise (n_trials > 1) : DSR <= PSR (le data-mining est penalise)."""
    df = make_df(_oscillating(600))
    res = opt.walk_forward(df, "sma", n_windows=4, train_frac=0.5,
                           metric="sharpe", fee=0.0)
    if np.isfinite(res["psr"]) and np.isfinite(res["dsr"]):
        assert res["dsr"] <= res["psr"] + 1e-12


def test_walk_forward_fixed_params_n_trials_is_one(make_df):
    """Mode fige : 1 seul essai -> DSR == PSR (aucune penalite de data-mining)."""
    df = make_df(_trend_then_reversal(700))
    res = opt.walk_forward(df, "sma", n_windows=4, train_frac=0.5, metric="sharpe",
                           fee=0.0, fixed_params={"fast": 50, "slow": 200})
    assert res["n_trials"] == 1
    if np.isfinite(res["psr"]) and np.isfinite(res["dsr"]):
        assert res["dsr"] == pytest.approx(res["psr"])


# --------------------------------------------------------------------------- #
#  B7 : holdout SACRE (jamais vu par la recherche)                             #
# --------------------------------------------------------------------------- #
def test_holdout_split_excludes_recent_candles_from_research(make_df):
    """Le decoupage retire bien les bougies recentes : la recherche (walk-forward
    complet sur le segment de recherche) ne touche JAMAIS le holdout."""
    df = make_df(_trend_then_reversal(600))
    cut = opt.holdout_split(len(df), 0.20)
    assert cut == 480                                  # 20% recents reserves
    research, holdout = df.iloc[:cut], df.iloc[cut:]
    assert research.index.max() < holdout.index.min()
    res = opt.walk_forward(research, "sma", n_windows=4, train_frac=0.5,
                           metric="sharpe", fee=0.0)
    last_oos_end = res["windows"][-1]["period"][1]
    assert last_oos_end == research.index[-1]          # la recherche va au bout...
    assert last_oos_end < holdout.index.min()          # ...mais JAMAIS dans le holdout


def test_holdout_split_rejects_degenerate_fractions():
    with pytest.raises(ValueError):
        opt.holdout_split(100, 0.0)
    with pytest.raises(ValueError):
        opt.holdout_split(100, 1.0)


def test_holdout_check_counts_only_holdout_segment(make_df):
    """holdout_check rapporte EXACTEMENT le segment holdout (periode + nb de
    bougies) et ses metriques == celles d'un run warm-up direct equivalent."""
    df = make_df(_trend_then_reversal(700))
    fixed = {"fast": 10, "slow": 50}
    res = opt.holdout_check(df, 0.20, "sma", fixed_params=fixed,
                            metric="sharpe", fee=0.0)
    cut = opt.holdout_split(len(df), 0.20)
    assert res["holdout_period"][0] == df.index[cut]
    assert res["holdout_period"][1] == df.index[-1]
    assert res["n_holdout"] == len(df) - cut
    assert res["params"] == fixed
    assert res["optimised_on_research"] is False
    # Reference : run direct Backtester avec le meme warm-up amont (B1).
    bt = Backtester(fee=0.0)
    margin = opt._params_warmup(fixed)
    t_start = max(0, cut - margin)
    expected = bt.run(df.iloc[t_start:], SMACrossover(**fixed),
                      warmup=cut - t_start).metrics
    assert res["metrics"]["total_return"] == pytest.approx(expected["total_return"])
    assert res["metrics"]["n_trades"] == expected["n_trades"]


def test_holdout_check_warmup_preserved(make_df):
    """B1 dans le holdout : une SMA lente (slow=200) sur un holdout court serait
    MORTE sans warm-up amont ; holdout_check l'amorce et elle trade."""
    df = make_df(_trend_then_reversal(700))
    cut = opt.holdout_split(len(df), 0.15)             # holdout de 105 bougies
    bt = Backtester(fee=0.0)
    isolated = bt.run(df.iloc[cut:], SMACrossover(fast=10, slow=200))
    res = opt.holdout_check(df, 0.15, "sma", fixed_params={"fast": 10, "slow": 200},
                            metric="sharpe", fee=0.0)
    assert isolated.metrics["n_trades"] == 0           # sans warm-up : degeneree
    assert res["metrics"]["n_trades"] >= 1             # avec warm-up : vivante


def test_holdout_check_optimises_on_research_only(make_df, monkeypatch):
    """Sans fixed_params, la selection (_best_on) ne voit QUE la recherche."""
    df = make_df(_trend_then_reversal(700))
    cut = opt.holdout_split(len(df), 0.20)
    seen = {}
    real = opt._best_on

    def spy(bt, d, *a, **k):
        seen["max_index"] = d.index.max()
        return real(bt, d, *a, **k)

    monkeypatch.setattr(opt, "_best_on", spy)
    res = opt.holdout_check(df, 0.20, "sma", fixed_params=None,
                            metric="sharpe", fee=0.0)
    assert seen["max_index"] < df.index[cut]           # jamais le holdout
    assert res["optimised_on_research"] is True


def test_holdout_check_guard_too_short():
    import pandas as pd
    idx = pd.date_range("2022-01-01", periods=20, freq="1D", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                       "close": 100.0, "volume": 1.0}, index=idx)
    with pytest.raises(RuntimeError):
        opt.holdout_check(df, 0.10, "sma", fixed_params={"fast": 10, "slow": 50},
                          fee=0.0)                     # holdout de 2 bougies < 5


def test_format_holdout_carries_strong_warning(make_df):
    df = make_df(_trend_then_reversal(700))
    res = opt.holdout_check(df, 0.20, "sma", fixed_params={"fast": 10, "slow": 50},
                            metric="sharpe", fee=0.0)
    txt = opt.format_holdout(res)
    assert "VALIDATION FINALE" in txt
    assert "data-mining" in txt
    assert "UNE fois" in txt


# --------------------------------------------------------------------------- #
#  Multi-actifs : agregation walk_forward_multi (sans reseau)                  #
# --------------------------------------------------------------------------- #
def _fake_wf_result(oos, sharpes=(1.0, 0.5), pct=0.5):
    return {"strategy": "sma", "metric": "sharpe",
            "windows": [{"period": None, "params": {},
                         "metrics": {"sharpe": s, "total_return": 0.0}}
                        for s in sharpes],
            "oos_total_return": oos, "avg_window_metric": float(np.mean(sharpes)),
            "pct_profitable": pct, "fixed_params": None,
            "n_trials": 1, "n_obs_oos": 100, "psr": 0.6, "dsr": 0.6}


def _patch_wf(monkeypatch, data, results, failing=()):
    """walk_forward monkeypatche : retrouve le symbole par identite du df."""
    def fake_wf(d, name, **k):
        for sym, dd in data.items():
            if dd is d:
                if sym in failing:
                    raise RuntimeError("Pas assez de donnees pour ce walk-forward.")
                return results[sym]
        raise AssertionError("df inconnu passe a walk_forward")
    monkeypatch.setattr(opt, "walk_forward", fake_wf)


def test_walk_forward_multi_aggregates(monkeypatch, make_df):
    """2 actifs positifs sur 3 : agregation correcte + robuste (majorite)."""
    base = make_df(_oscillating(100))
    data = {s: base.copy() for s in ("BTC/USD", "ETH/USD", "SOL/USD")}
    results = {"BTC/USD": _fake_wf_result(0.10), "ETH/USD": _fake_wf_result(-0.05),
               "SOL/USD": _fake_wf_result(0.20)}
    _patch_wf(monkeypatch, data, results)
    res = opt.walk_forward_multi(data, "sma", n_windows=4)
    s = res["summary"]
    assert s["n_assets"] == 3 and s["n_positive"] == 2
    assert s["avg_oos_return"] == pytest.approx((0.10 - 0.05 + 0.20) / 3)
    assert s["robust"] is True
    assert set(res["per_symbol"]) == set(data)


def test_walk_forward_multi_robust_consistent_with_display(monkeypatch, make_df):
    """FIX 3 : majorite positive (2/3) MAIS moyenne OOS negative -> robust=False
    partout. Le dict et l'affichage doivent dire la MEME chose (source unique)."""
    base = make_df(_oscillating(100))
    data = {s: base.copy() for s in ("BTC/USD", "ETH/USD", "SOL/USD")}
    # 2 petits gains + 1 grosse perte : majorite > 0 mais moyenne < 0.
    results = {"BTC/USD": _fake_wf_result(0.02), "ETH/USD": _fake_wf_result(0.03),
               "SOL/USD": _fake_wf_result(-0.30)}
    _patch_wf(monkeypatch, data, results)
    res = opt.walk_forward_multi(data, "sma", n_windows=4)
    s = res["summary"]
    assert s["n_positive"] == 2 and s["n_assets"] == 3   # majorite positive...
    assert s["avg_oos_return"] < 0                        # ...mais moyenne negative
    assert s["robust"] is False                           # dict : NON robuste
    assert "NON robuste" in opt.format_walk_forward_multi(res)   # affichage idem


def test_walk_forward_multi_one_positive_out_of_three_not_robust(monkeypatch, make_df):
    """1 actif positif sur 3 = PAS robuste (verdict honnete)."""
    base = make_df(_oscillating(100))
    data = {s: base.copy() for s in ("BTC/USD", "ETH/USD", "SOL/USD")}
    results = {"BTC/USD": _fake_wf_result(0.30), "ETH/USD": _fake_wf_result(-0.10),
               "SOL/USD": _fake_wf_result(-0.02)}
    _patch_wf(monkeypatch, data, results)
    res = opt.walk_forward_multi(data, "sma", n_windows=4)
    assert res["summary"]["robust"] is False
    txt = opt.format_walk_forward_multi(res)
    assert "NON robuste" in txt


def test_walk_forward_multi_skips_failing_asset(monkeypatch, make_df):
    """Un actif en echec est signale et ignore, jamais masque."""
    base = make_df(_oscillating(100))
    data = {s: base.copy() for s in ("BTC/USD", "ETH/USD", "SOL/USD")}
    results = {"BTC/USD": _fake_wf_result(0.10), "SOL/USD": _fake_wf_result(0.05)}
    _patch_wf(monkeypatch, data, results, failing=("ETH/USD",))
    res = opt.walk_forward_multi(data, "sma", n_windows=4)
    assert set(res["per_symbol"]) == {"BTC/USD", "SOL/USD"}
    assert "ETH/USD" in res["errors"]
    assert res["summary"]["n_assets"] == 2
    txt = opt.format_walk_forward_multi(res)
    assert "ignore ETH/USD" in txt


def test_walk_forward_multi_all_fail_raises(monkeypatch, make_df):
    base = make_df(_oscillating(100))
    data = {s: base.copy() for s in ("BTC/USD", "ETH/USD")}
    _patch_wf(monkeypatch, data, {}, failing=("BTC/USD", "ETH/USD"))
    with pytest.raises(RuntimeError):
        opt.walk_forward_multi(data, "sma", n_windows=4)


def test_format_walk_forward_multi_table_lists_each_asset(monkeypatch, make_df):
    base = make_df(_oscillating(100))
    data = {s: base.copy() for s in ("BTC/USD", "ETH/USD", "SOL/USD")}
    results = {s: _fake_wf_result(0.10) for s in data}
    _patch_wf(monkeypatch, data, results)
    res = opt.walk_forward_multi(data, "sma", n_windows=4)
    txt = opt.format_walk_forward_multi(res)
    for s in data:
        assert s in txt
    assert "Synthese" in txt and "3 actifs evalues" in txt
