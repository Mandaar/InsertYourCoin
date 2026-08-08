"""
Tests de trading/optimize_page.py (Lot 5, /research/optimize) : parsing +
rendu (fonctions PURES, aucun serveur, aucun reseau).
"""
import numpy as np

from trading import optimize_page as op
from trading.optimizer import optimize
from trading.strategies import STRATEGIES


def _oscillating(n, period=12.0, amp=20.0, base=100.0):
    t = np.arange(n)
    return base + amp * np.sin(t / period)


# --------------------------------------------------------------------------- #
#  parse_optimize_params                                                      #
# --------------------------------------------------------------------------- #
def test_parse_optimize_params_defaults_on_minimal_valid_input():
    params, errors = op.parse_optimize_params({"strategy": "sma"})
    assert errors == []
    assert params["strategy"] == "sma"
    assert params["metric"] == "sharpe"
    assert params["train_frac"] == op.DEFAULT_TRAIN_FRAC


def test_parse_optimize_params_full_valid_input():
    fields = {
        "strategy": "tsmom", "symbol": "BTC/USD", "timeframe": "1h", "days": "365",
        "source": "binance", "metric": "sortino", "train_frac": "0.7",
    }
    params, errors = op.parse_optimize_params(fields)
    assert errors == []
    assert params["strategy"] == "tsmom"
    assert params["metric"] == "sortino"
    assert params["train_frac"] == 0.7
    assert params["symbol"] == "BTC/USD"


def test_parse_optimize_params_unknown_strategy_is_error():
    params, errors = op.parse_optimize_params({"strategy": "n-existe-pas"})
    assert params is None
    assert any("Stratégie inconnue" in e for e in errors)


def test_parse_optimize_params_unknown_metric_is_error():
    params, errors = op.parse_optimize_params({"strategy": "sma", "metric": "bogus"})
    assert params is None
    assert any("Métrique non supportée" in e for e in errors)


def test_parse_optimize_params_train_frac_out_of_range_is_error():
    params, errors = op.parse_optimize_params({"strategy": "sma", "train_frac": "1.5"})
    assert params is None
    assert any("Train-frac" in e for e in errors)


def test_parse_optimize_params_train_frac_non_numeric_is_error():
    params, errors = op.parse_optimize_params({"strategy": "sma", "train_frac": "beaucoup"})
    assert params is None
    assert any("Train-frac" in e for e in errors)


# --------------------------------------------------------------------------- #
#  render_optimize_form                                                       #
# --------------------------------------------------------------------------- #
def test_render_optimize_form_lists_strategies_and_metrics():
    out = op.render_optimize_form("tok-secret")
    for key in STRATEGIES:
        assert f"value='{key}'" in out
    for m in op.METRIC_CHOICES:
        assert f"value='{m}'" in out
    assert "name='csrf_token' value='tok-secret'" in out
    assert "action='/research/optimize'" in out
    assert "research-subnav" in out


def test_render_optimize_form_shows_errors_and_repopulates_values():
    out = op.render_optimize_form("tok", errors=["Train-frac : attendu dans ]0, 1[."],
                                  values={"symbol": "SOL/USD"})
    assert "Train-frac : attendu dans ]0, 1[." in out
    assert "value='SOL/USD'" in out


# --------------------------------------------------------------------------- #
#  render_optimize_busy / render_optimize_launched                            #
# --------------------------------------------------------------------------- #
def test_render_optimize_busy_shows_label_and_job_panel():
    out = op.render_optimize_busy("Optimiser sma ETH/USD", "a" * 32, "tok")
    assert "Optimiser sma ETH/USD" in out
    assert "class='job-panel'" in out
    assert f"/report/{'a' * 32}" in out


def test_render_optimize_launched_embeds_job_panel():
    out = op.render_optimize_launched("c" * 32, "tok")
    assert "class='job-panel'" in out
    assert f"/report/{'c' * 32}" in out


# --------------------------------------------------------------------------- #
#  render_optimize_done                                                       #
# --------------------------------------------------------------------------- #
def _real_optimize_result(make_df):
    df = make_df(_oscillating(600))
    res = optimize(df, "sma", train_frac=0.6, metric="sharpe")
    return {"kind": "optimize", "result": res,
            "context": {"symbol": "ETH/USD", "timeframe": "1d"}}


def test_render_optimize_done_shows_train_and_test_panels(make_df):
    result = _real_optimize_result(make_df)
    out = op.render_optimize_done(result)
    assert "Train (in-sample)" in out
    assert "Test (hors-échantillon)" in out
    assert "tt-test" in out
    assert "ETH/USD" in out
    assert "<nav class='nav'>" in out


def test_render_optimize_done_shows_overfit_warning_when_test_collapses(make_df):
    result = _real_optimize_result(make_df)
    result["result"] = dict(result["result"])
    result["result"]["train"] = dict(result["result"]["train"], sharpe=2.0)
    result["result"]["test"] = dict(result["result"]["test"], sharpe=0.1)
    out = op.render_optimize_done(result)
    assert "Surapprentissage probable" in out


def test_render_optimize_done_no_overfit_warning_when_test_holds(make_df):
    result = _real_optimize_result(make_df)
    result["result"] = dict(result["result"])
    result["result"]["train"] = dict(result["result"]["train"], sharpe=1.0)
    result["result"]["test"] = dict(result["result"]["test"], sharpe=0.9)
    out = op.render_optimize_done(result)
    assert "Surapprentissage probable" not in out
