"""
Tests de trading/research_runners.py (Lots 4-5) : les runners des jobs POST
/research/{backtest,compare,optimize,portfolio}. AUCUN RESEAU -- les points
d'acces aux donnees (`_load_ohlcv` mono-actif, `_load_basket_ohlcv`
multi-actifs) sont TOUJOURS monkeypatches pour injecter des DataFrame OHLCV
synthetiques (cf. conftest.make_df).
"""
import numpy as np
import pytest

from trading import research_runners as rr
from trading.strategies import STRATEGIES


def _oscillating(n, period=12.0, amp=20.0, base=100.0):
    """Sinusoide : croisements SMA frequents -> assez de trades pour que
    l'optimizer trouve des combinaisons ELIGIBLES (n_trades >= MIN_TRADES),
    meme reproduction que tests/test_optimizer.py."""
    t = np.arange(n)
    return base + amp * np.sin(t / period)


class FakeProgress:
    """Double minimal de trading.jobs.JobProgress (aucun thread reel)."""

    def __init__(self, cancelled=False):
        self.logs = []
        self.cancelled = cancelled

    def log(self, message):
        self.logs.append(str(message))

    def set_percent(self, value):
        pass


def _params(**overrides):
    base = {
        "strategy": "sma", "symbol": "ETH/USD", "timeframe": "1d", "days": 150,
        "source": "kraken", "stop_loss": None, "take_profit": None,
        "trailing_stop": None, "position_sizing": "none", "target_vol": None,
    }
    base.update(overrides)
    return base


def test_run_backtest_returns_payload_without_network(make_df, monkeypatch):
    closes = [100 + i * 0.5 for i in range(150)]
    df = make_df(closes)
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)

    progress = FakeProgress()
    result = rr.run_backtest(_params(), progress)

    assert result is not None
    assert set(result) == {"kind", "detail", "comparison", "context"}
    assert result["kind"] == "backtest"
    assert result["context"] == {"symbol": "ETH/USD", "timeframe": "1d"}
    assert result["detail"].metrics["n_trades"] >= 0
    assert len(result["comparison"]) == len(STRATEGIES)
    assert {row["name"] for row in result["comparison"]}
    assert any("Chargement" in l or "Backtest" in l for l in progress.logs)


def test_run_backtest_applies_risk_params_as_fractions(make_df, monkeypatch):
    closes = [100 + i * 0.5 for i in range(150)]
    df = make_df(closes)
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)

    progress = FakeProgress()
    result = rr.run_backtest(_params(stop_loss=8, take_profit=20, target_vol=40,
                                     position_sizing="vol"), progress)

    risk = result["detail"].risk
    assert risk["stop_loss"] == pytest.approx(0.08)
    assert risk["take_profit"] == pytest.approx(0.20)
    assert risk["position_sizing"] == "vol"
    assert risk["target_vol"] == pytest.approx(0.40)


def test_run_backtest_unknown_strategy_raises_without_loading_data(monkeypatch):
    def _boom(params, progress):
        raise AssertionError("le loader ne doit jamais etre appele pour une strategie inconnue")

    monkeypatch.setattr(rr, "_load_ohlcv", _boom)
    with pytest.raises(rr.ResearchError, match="Strategie inconnue"):
        rr.run_backtest(_params(strategy="ne-existe-pas"), FakeProgress())


def test_run_backtest_loader_failure_becomes_research_error(monkeypatch):
    def _raise(params, progress):
        raise RuntimeError("Kraken indisponible")

    monkeypatch.setattr(rr, "_load_ohlcv", _raise)
    with pytest.raises(rr.ResearchError, match="Donnees indisponibles"):
        rr.run_backtest(_params(), FakeProgress())


def test_run_backtest_not_enough_candles_raises_research_error(make_df, monkeypatch):
    df = make_df([100.0])  # 1 seule bougie -- insuffisant
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)
    with pytest.raises(rr.ResearchError, match="Pas assez de bougies"):
        rr.run_backtest(_params(), FakeProgress())


def test_run_backtest_respects_cancellation_after_load(make_df, monkeypatch):
    closes = [100 + i * 0.5 for i in range(150)]
    df = make_df(closes)
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)

    progress = FakeProgress(cancelled=True)
    result = rr.run_backtest(_params(), progress)
    assert result is None


# --------------------------------------------------------------------------- #
#  Lot 5 -- run_compare (POST /research/compare)                              #
# --------------------------------------------------------------------------- #
def _compare_params(**overrides):
    base = {
        "symbol": "ETH/USD", "timeframe": "1d", "days": 150, "source": "kraken",
        "stop_loss": None, "take_profit": None, "trailing_stop": None,
        "position_sizing": "none", "target_vol": None,
    }
    base.update(overrides)
    return base


def test_run_compare_returns_all_strategies_and_buy_hold(make_df, monkeypatch):
    df = make_df(_oscillating(150))
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)

    progress = FakeProgress()
    result = rr.run_compare(_compare_params(), progress)

    assert result["kind"] == "compare"
    assert len(result["rows"]) == len(STRATEGIES)
    assert {row["name"] for row in result["rows"]}
    assert isinstance(result["buy_hold"], float)
    assert result["context"]["symbol"] == "ETH/USD"
    assert any("Comparaison" in l for l in progress.logs)


def test_run_compare_loader_failure_becomes_research_error(monkeypatch):
    def _raise(params, progress):
        raise RuntimeError("Kraken indisponible")

    monkeypatch.setattr(rr, "_load_ohlcv", _raise)
    with pytest.raises(rr.ResearchError, match="Donnees indisponibles"):
        rr.run_compare(_compare_params(), FakeProgress())


def test_run_compare_not_enough_candles_raises_research_error(make_df, monkeypatch):
    df = make_df([100.0])
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)
    with pytest.raises(rr.ResearchError, match="Pas assez de bougies"):
        rr.run_compare(_compare_params(), FakeProgress())


def test_run_compare_respects_cancellation_after_load(make_df, monkeypatch):
    df = make_df(_oscillating(150))
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)
    result = rr.run_compare(_compare_params(), FakeProgress(cancelled=True))
    assert result is None


# --------------------------------------------------------------------------- #
#  Lot 5 -- run_optimize (POST /research/optimize)                            #
# --------------------------------------------------------------------------- #
def _optimize_params(**overrides):
    base = {
        "strategy": "sma", "symbol": "ETH/USD", "timeframe": "1d", "days": 600,
        "source": "kraken", "metric": "sharpe", "train_frac": 0.6,
        "stop_loss": None, "take_profit": None, "trailing_stop": None,
        "position_sizing": "none", "target_vol": None,
    }
    base.update(overrides)
    return base


def test_run_optimize_returns_train_and_test(make_df, monkeypatch):
    df = make_df(_oscillating(600))
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)

    progress = FakeProgress()
    result = rr.run_optimize(_optimize_params(), progress)

    assert result["kind"] == "optimize"
    res = result["result"]
    assert res["strategy"] == "sma"
    assert res["metric"] == "sharpe"
    assert "best_params" in res
    assert set(res["train"]) >= {"sharpe", "total_return"}
    assert set(res["test"]) >= {"sharpe", "total_return"}
    assert result["context"]["symbol"] == "ETH/USD"
    assert any("Optimisation" in l for l in progress.logs)


def test_run_optimize_unknown_strategy_raises_without_loading_data(monkeypatch):
    def _boom(params, progress):
        raise AssertionError("le loader ne doit jamais etre appele")

    monkeypatch.setattr(rr, "_load_ohlcv", _boom)
    with pytest.raises(rr.ResearchError, match="Strategie inconnue"):
        rr.run_optimize(_optimize_params(strategy="ne-existe-pas"), FakeProgress())


def test_run_optimize_not_enough_data_raises_research_error(make_df, monkeypatch):
    # Trop peu de bougies pour qu'une combinaison de la grille SMA soit
    # eligible (garde optimizer._best_on -> "Aucune combinaison valide.").
    df = make_df([100.0 + i for i in range(10)])
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)
    with pytest.raises(rr.ResearchError):
        rr.run_optimize(_optimize_params(days=10), FakeProgress())


def test_run_optimize_loader_failure_becomes_research_error(monkeypatch):
    def _raise(params, progress):
        raise RuntimeError("Kraken indisponible")

    monkeypatch.setattr(rr, "_load_ohlcv", _raise)
    with pytest.raises(rr.ResearchError, match="Donnees indisponibles"):
        rr.run_optimize(_optimize_params(), FakeProgress())


def test_run_optimize_respects_cancellation_after_load(make_df, monkeypatch):
    df = make_df(_oscillating(600))
    monkeypatch.setattr(rr, "_load_ohlcv", lambda params, progress: df)
    result = rr.run_optimize(_optimize_params(), FakeProgress(cancelled=True))
    assert result is None


# --------------------------------------------------------------------------- #
#  Lot 5 -- run_portfolio (POST /research/portfolio)                          #
# --------------------------------------------------------------------------- #
def _portfolio_params(**overrides):
    base = {
        "symbols": ["BTC/USD", "ETH/USD"], "strategy": "sma", "timeframe": "1d",
        "days": 150, "source": "kraken", "stop_loss": None, "take_profit": None,
        "trailing_stop": None, "position_sizing": "none", "target_vol": None,
    }
    base.update(overrides)
    return base


def test_run_portfolio_returns_result_with_correlation(make_df, monkeypatch):
    data = {"BTC/USD": make_df(_oscillating(150, base=100.0)),
            "ETH/USD": make_df(_oscillating(150, base=50.0, period=9.0))}
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: (data, []))

    progress = FakeProgress()
    result = rr.run_portfolio(_portfolio_params(), progress)

    assert result["kind"] == "portfolio"
    res = result["result"]
    assert set(res["symbols"]) == {"BTC/USD", "ETH/USD"}
    assert "portfolio" in res and "portfolio_bh" in res
    assert list(res["correlation"].columns) == res["symbols"]
    assert result["ignored"] == []
    assert result["context"]["symbols"] == ["BTC/USD", "ETH/USD"]
    assert any("portefeuille" in l.lower() for l in progress.logs)


def test_run_portfolio_reports_ignored_symbols(make_df, monkeypatch):
    data = {"BTC/USD": make_df(_oscillating(150))}
    ignored = [{"symbol": "SOL/USD", "error": "indisponible"}]
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: (data, ignored))

    result = rr.run_portfolio(_portfolio_params(symbols=["BTC/USD", "SOL/USD"]), FakeProgress())
    assert result["ignored"] == ignored
    assert set(result["result"]["symbols"]) == {"BTC/USD"}


def test_run_portfolio_unknown_strategy_raises_without_loading_data(monkeypatch):
    def _boom(params, progress):
        raise AssertionError("le loader ne doit jamais etre appele")

    monkeypatch.setattr(rr, "_load_basket_ohlcv", _boom)
    with pytest.raises(rr.ResearchError, match="Strategie inconnue"):
        rr.run_portfolio(_portfolio_params(strategy="ne-existe-pas"), FakeProgress())


def test_run_portfolio_no_symbols_raises_research_error(monkeypatch):
    def _boom(params, progress):
        raise AssertionError("le loader ne doit jamais etre appele")

    monkeypatch.setattr(rr, "_load_basket_ohlcv", _boom)
    with pytest.raises(rr.ResearchError, match="Aucun symbole"):
        rr.run_portfolio(_portfolio_params(symbols=[]), FakeProgress())


def test_run_portfolio_all_symbols_ignored_raises_research_error(monkeypatch):
    ignored = [{"symbol": "BTC/USD", "error": "boom"}, {"symbol": "ETH/USD", "error": "boom2"}]
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: ({}, ignored))
    with pytest.raises(rr.ResearchError, match="Aucun actif chargeable"):
        rr.run_portfolio(_portfolio_params(), FakeProgress())


def test_run_portfolio_respects_cancellation_after_load(make_df, monkeypatch):
    data = {"BTC/USD": make_df(_oscillating(150)), "ETH/USD": make_df(_oscillating(150))}
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: (data, []))
    result = rr.run_portfolio(_portfolio_params(), FakeProgress(cancelled=True))
    assert result is None


# --------------------------------------------------------------------------- #
#  Lot 6 -- run_walkforward (POST /research/walkforward) -- LE JUGE           #
# --------------------------------------------------------------------------- #
def _walkforward_params(**overrides):
    base = {
        "symbols": ["ETH/USD"], "strategy": "sma", "timeframe": "1d", "days": 600,
        "source": "kraken", "metric": "sharpe", "windows": 4, "train_frac": 0.5,
        "fixed": {"fast": 10, "slow": 50}, "holdout_pct": 0.0, "final": False,
        "stop_loss": None, "take_profit": None, "trailing_stop": None,
        "position_sizing": "none", "target_vol": None,
    }
    base.update(overrides)
    return base


def test_run_walkforward_returns_payload_without_network(make_df, monkeypatch):
    df = make_df(_oscillating(600))
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: ({"ETH/USD": df}, []))

    progress = FakeProgress()
    result = rr.run_walkforward(_walkforward_params(), progress)

    assert result is not None
    assert set(result) == {
        "kind", "results", "wf_errors", "summary", "holdout", "holdout_errors",
        "ignored", "context",
    }
    assert result["kind"] == "walkforward"
    assert set(result["results"]) == {"ETH/USD"}
    res = result["results"]["ETH/USD"]
    assert res["strategy"] == "sma"
    assert len(res["windows"]) == 4
    assert res["fixed_params"] == {"fast": 10, "slow": 50}
    assert result["wf_errors"] == {}
    assert result["summary"]["n_assets"] == 1
    assert result["holdout"] is None            # final=False -> holdout jamais consomme
    assert result["holdout_errors"] == {}
    assert result["ignored"] == []
    assert result["context"]["symbols"] == ["ETH/USD"]
    assert result["context"]["final"] is False
    assert any("Walk-forward" in l for l in progress.logs)


def test_run_walkforward_multi_symbol_aggregates(make_df, monkeypatch):
    data = {"BTC/USD": make_df(_oscillating(600, base=100.0)),
            "ETH/USD": make_df(_oscillating(600, base=50.0, period=9.0))}
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: (data, []))

    result = rr.run_walkforward(
        _walkforward_params(symbols=["BTC/USD", "ETH/USD"]), FakeProgress(),
    )
    assert set(result["results"]) == {"BTC/USD", "ETH/USD"}
    assert result["summary"]["n_assets"] == 2
    assert "robust" in result["summary"]


def test_run_walkforward_unknown_strategy_raises_without_loading_data(monkeypatch):
    def _boom(params, progress):
        raise AssertionError("le loader ne doit jamais etre appele")

    monkeypatch.setattr(rr, "_load_basket_ohlcv", _boom)
    with pytest.raises(rr.ResearchError, match="Strategie inconnue"):
        rr.run_walkforward(_walkforward_params(strategy="ne-existe-pas"), FakeProgress())


def test_run_walkforward_no_symbols_raises_research_error(monkeypatch):
    def _boom(params, progress):
        raise AssertionError("le loader ne doit jamais etre appele")

    monkeypatch.setattr(rr, "_load_basket_ohlcv", _boom)
    with pytest.raises(rr.ResearchError, match="Aucun symbole"):
        rr.run_walkforward(_walkforward_params(symbols=[]), FakeProgress())


def test_run_walkforward_all_symbols_ignored_raises_research_error(monkeypatch):
    ignored = [{"symbol": "ETH/USD", "error": "boom"}]
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: ({}, ignored))
    with pytest.raises(rr.ResearchError, match="Aucun actif chargeable"):
        rr.run_walkforward(_walkforward_params(), FakeProgress())


def test_run_walkforward_reports_ignored_symbols(make_df, monkeypatch):
    data = {"ETH/USD": make_df(_oscillating(600))}
    ignored = [{"symbol": "SOL/USD", "error": "indisponible"}]
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: (data, ignored))

    result = rr.run_walkforward(
        _walkforward_params(symbols=["ETH/USD", "SOL/USD"]), FakeProgress(),
    )
    assert result["ignored"] == ignored
    assert set(result["results"]) == {"ETH/USD"}


def test_run_walkforward_respects_cancellation_after_load(make_df, monkeypatch):
    df = make_df(_oscillating(600))
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: ({"ETH/USD": df}, []))
    result = rr.run_walkforward(_walkforward_params(), FakeProgress(cancelled=True))
    assert result is None


def test_run_walkforward_removes_holdout_before_research(make_df, monkeypatch):
    """B7 : le holdout sacre ne doit JAMAIS apparaitre dans les fenetres OOS --
    la derniere fenetre s'arrete avant le debut du holdout (meme frontiere que
    optimizer.holdout_split)."""
    from trading.optimizer import holdout_split

    df = make_df(_oscillating(600))
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: ({"ETH/USD": df}, []))

    result = rr.run_walkforward(_walkforward_params(holdout_pct=20.0), FakeProgress())
    cut = holdout_split(len(df), 0.20)
    last_window_end = result["results"]["ETH/USD"]["windows"][-1]["period"][1]
    assert last_window_end <= df.index[cut - 1]


def test_run_walkforward_logs_holdout_reservation(make_df, monkeypatch):
    df = make_df(_oscillating(600))
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: ({"ETH/USD": df}, []))
    progress = FakeProgress()
    rr.run_walkforward(_walkforward_params(holdout_pct=20.0), progress)
    assert any("Holdout reserve" in l for l in progress.logs)


def test_run_walkforward_final_true_populates_holdout(make_df, monkeypatch):
    df = make_df(_oscillating(600))
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: ({"ETH/USD": df}, []))

    result = rr.run_walkforward(
        _walkforward_params(holdout_pct=20.0, final=True), FakeProgress(),
    )
    assert result["holdout"] is not None
    assert set(result["holdout"]) == {"ETH/USD"}
    h = result["holdout"]["ETH/USD"]
    assert h["params"] == {"fast": 10, "slow": 50}
    assert h["optimised_on_research"] is False
    assert h["holdout_frac"] == pytest.approx(0.20)
    assert result["holdout_errors"] == {}
    assert result["context"]["final"] is True


def test_run_walkforward_final_false_holdout_stays_none(make_df, monkeypatch):
    df = make_df(_oscillating(600))
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: ({"ETH/USD": df}, []))
    result = rr.run_walkforward(
        _walkforward_params(holdout_pct=20.0, final=False), FakeProgress(),
    )
    assert result["holdout"] is None


def test_run_walkforward_per_symbol_holdout_error_does_not_abort_others(make_df, monkeypatch):
    """Un actif en echec de VALIDATION FINALE n'empeche pas les autres actifs
    de produire leur resultat (signale, jamais masque -- cf. rules/vigilance.md).
    `optimizer.holdout_check` est importe LOCALEMENT dans run_walkforward (a
    l'appel) -- monkeypatcher l'attribut module AVANT l'appel suffit donc a
    l'intercepter (cf. docstring recherche_runners : imports paresseux)."""
    from trading import optimizer as opt

    data = {"BTC/USD": make_df(_oscillating(600, base=100.0)),
            "ETH/USD": make_df(_oscillating(600, base=50.0, period=9.0))}
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: (data, []))

    original = opt.holdout_check

    def _flaky(df, holdout_frac, strategy_name, **kwargs):
        if df is data["BTC/USD"]:
            raise RuntimeError("Holdout trop court (< 5 bougies). Augmente --days ou --holdout.")
        return original(df, holdout_frac, strategy_name, **kwargs)

    monkeypatch.setattr(opt, "holdout_check", _flaky)

    result = rr.run_walkforward(
        _walkforward_params(symbols=["BTC/USD", "ETH/USD"], holdout_pct=20.0, final=True),
        FakeProgress(),
    )
    assert set(result["holdout"]) == {"ETH/USD"}
    assert set(result["holdout_errors"]) == {"BTC/USD"}
    assert "Holdout trop court" in result["holdout_errors"]["BTC/USD"]
