"""
Tests de trading/portfolio_page.py (Lot 5, /research/portfolio) : parsing +
rendu (fonctions PURES, aucun serveur, aucun reseau).
"""
import numpy as np

from trading import portfolio_page as pp
from trading.portfolio import backtest_portfolio
from trading.strategies import STRATEGIES


def _oscillating(n, period=12.0, amp=20.0, base=100.0):
    t = np.arange(n)
    return base + amp * np.sin(t / period)


# --------------------------------------------------------------------------- #
#  parse_symbols                                                              #
# --------------------------------------------------------------------------- #
def test_parse_symbols_splits_and_strips():
    assert pp.parse_symbols("BTC/USD, ETH/USD ,SOL/USD") == ["BTC/USD", "ETH/USD", "SOL/USD"]


def test_parse_symbols_blank_falls_back_to_default():
    assert pp.parse_symbols("") == pp.DEFAULT_SYMBOLS.split(",")
    assert pp.parse_symbols(None) == pp.DEFAULT_SYMBOLS.split(",")


# --------------------------------------------------------------------------- #
#  parse_portfolio_params                                                     #
# --------------------------------------------------------------------------- #
def test_parse_portfolio_params_defaults_on_minimal_valid_input():
    params, errors = pp.parse_portfolio_params({"strategy": "sma"})
    assert errors == []
    assert params["symbols"] == pp.DEFAULT_SYMBOLS.split(",")
    assert params["strategy"] == "sma"
    assert params["days"] == 720


def test_parse_portfolio_params_custom_symbols():
    params, errors = pp.parse_portfolio_params(
        {"strategy": "sma", "symbols": "BTC/USD,ETH/USD"}
    )
    assert errors == []
    assert params["symbols"] == ["BTC/USD", "ETH/USD"]


def test_parse_portfolio_params_unknown_strategy_is_error():
    params, errors = pp.parse_portfolio_params({"strategy": "n-existe-pas"})
    assert params is None
    assert any("Stratégie inconnue" in e for e in errors)


def test_parse_portfolio_params_unknown_timeframe_is_error():
    params, errors = pp.parse_portfolio_params({"strategy": "sma", "timeframe": "3d"})
    assert params is None
    assert any("Timeframe non supporté" in e for e in errors)


# --------------------------------------------------------------------------- #
#  render_portfolio_form                                                      #
# --------------------------------------------------------------------------- #
def test_render_portfolio_form_lists_strategies_and_default_symbols():
    out = pp.render_portfolio_form("tok-secret")
    for key in STRATEGIES:
        assert f"value='{key}'" in out
    assert pp.DEFAULT_SYMBOLS in out
    assert "action='/research/portfolio'" in out
    assert "name='csrf_token' value='tok-secret'" in out
    assert "research-subnav" in out


def test_render_portfolio_form_shows_errors_and_repopulates_values():
    out = pp.render_portfolio_form("tok", errors=["Stratégie inconnue : x."],
                                   values={"symbols": "BTC/USD,ETH/USD"})
    assert "Stratégie inconnue : x." in out
    assert "value='BTC/USD,ETH/USD'" in out


# --------------------------------------------------------------------------- #
#  render_portfolio_busy / render_portfolio_launched                          #
# --------------------------------------------------------------------------- #
def test_render_portfolio_busy_shows_label_and_job_panel():
    out = pp.render_portfolio_busy("Portefeuille BTC/USD,ETH/USD (sma)", "a" * 32, "tok")
    assert "Portefeuille BTC/USD,ETH/USD (sma)" in out
    assert "class='job-panel'" in out


def test_render_portfolio_launched_embeds_job_panel():
    out = pp.render_portfolio_launched("c" * 32, "tok")
    assert "class='job-panel'" in out
    assert f"/report/{'c' * 32}" in out


# --------------------------------------------------------------------------- #
#  render_portfolio_done                                                      #
# --------------------------------------------------------------------------- #
def _real_portfolio_result(make_df, ignored=None):
    data = {"BTC/USD": make_df(_oscillating(150, base=100.0)),
            "ETH/USD": make_df(_oscillating(150, base=50.0, period=9.0))}
    res = backtest_portfolio(data, "sma")
    return {"kind": "portfolio", "result": res, "ignored": ignored or [],
            "context": {"symbols": ["BTC/USD", "ETH/USD"], "timeframe": "1d",
                       "source": "kraken"}}


def test_render_portfolio_done_shows_kpis_and_correlation_heatmap(make_df):
    result = _real_portfolio_result(make_df)
    out = pp.render_portfolio_done(result)
    assert "corr-table" in out
    assert "Corrélation moyenne" in out
    assert "BTC/USD" in out
    assert "ETH/USD" in out
    assert "<nav class='nav'>" in out


def test_render_portfolio_done_shows_ignored_symbols(make_df):
    ignored = [{"symbol": "SOL/USD", "error": "Données indisponibles"}]
    result = _real_portfolio_result(make_df, ignored=ignored)
    out = pp.render_portfolio_done(result)
    assert "SOL/USD" in out
    assert "Données indisponibles" in out
    assert "class='ignored'" in out


def test_render_portfolio_done_no_ignored_block_when_all_loaded(make_df):
    result = _real_portfolio_result(make_df)
    out = pp.render_portfolio_done(result)
    assert "class='ignored'" not in out


def test_render_portfolio_done_high_correlation_shows_systemic_warning(make_df):
    # Deux series IDENTIQUES -> correlation = 1 -> avertissement systemique.
    identical = make_df(_oscillating(150))
    data = {"BTC/USD": identical, "ETH/USD": identical}
    res = backtest_portfolio(data, "sma")
    result = {"kind": "portfolio", "result": res, "ignored": [],
             "context": {"symbols": ["BTC/USD", "ETH/USD"], "timeframe": "1d",
                        "source": "kraken"}}
    out = pp.render_portfolio_done(result)
    assert "risque systémique crypto" in out
