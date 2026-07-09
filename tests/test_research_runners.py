"""
Tests de trading/research_runners.py (Lot 4) : le runner du job POST
/research/backtest. AUCUN RESEAU -- `_load_ohlcv` (seul point d'acces aux
donnees) est TOUJOURS monkeypatche pour injecter un DataFrame OHLCV
synthetique (cf. conftest.make_df).
"""
import pytest

from trading import research_runners as rr
from trading.strategies import STRATEGIES


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
    assert set(result) == {"detail", "comparison", "context"}
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
