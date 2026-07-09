"""
Tests de trading/compare_page.py (Lot 5, /research/compare) : parsing +
rendu (fonctions PURES, aucun serveur, aucun reseau). Meme patron que
tests/test_research_page.py (Lot 4).
"""
from trading import compare_page as cp
from trading.backtester import Backtester
from trading.strategies import STRATEGIES, build_strategy


# --------------------------------------------------------------------------- #
#  parse_compare_params (delegue a research_page.parse_market_and_risk_fields)#
# --------------------------------------------------------------------------- #
def test_parse_compare_params_defaults_on_minimal_valid_input():
    params, errors = cp.parse_compare_params({})
    assert errors == []
    assert "strategy" not in params
    assert params["symbol"]
    assert params["timeframe"]
    assert params["days"] == 720
    assert params["source"] == "kraken"


def test_parse_compare_params_unknown_timeframe_is_error():
    params, errors = cp.parse_compare_params({"timeframe": "3d"})
    assert params is None
    assert any("Timeframe non supporte" in e for e in errors)


def test_parse_compare_params_negative_days_is_error():
    params, errors = cp.parse_compare_params({"days": "-5"})
    assert params is None
    assert any("Jours" in e for e in errors)


# --------------------------------------------------------------------------- #
#  render_compare_form                                                        #
# --------------------------------------------------------------------------- #
def test_render_compare_form_has_no_strategy_selector():
    out = cp.render_compare_form("tok-secret")
    assert "name='csrf_token' value='tok-secret'" in out
    assert "action='/research/compare'" in out
    assert "name='strategy'" not in out
    assert "<nav class='nav'>" in out
    assert "research-subnav" in out


def test_render_compare_form_shows_errors_and_repopulates_values():
    out = cp.render_compare_form("tok", errors=["Jours : doit etre un nombre positif."],
                                 values={"symbol": "SOL/USD"})
    assert "Jours : doit etre un nombre positif." in out
    assert "value='SOL/USD'" in out


def test_render_compare_form_no_errors_by_default():
    out = cp.render_compare_form("tok")
    assert "Formulaire invalide" not in out


# --------------------------------------------------------------------------- #
#  render_compare_busy / render_compare_launched                              #
# --------------------------------------------------------------------------- #
def test_render_compare_busy_shows_label_and_job_panel():
    out = cp.render_compare_busy("Comparer ETH/USD", "a" * 32, "tok")
    assert "Comparer ETH/USD" in out
    assert "deja en cours" in out
    assert "class='job-panel'" in out
    assert f"/report/{'a' * 32}" in out


def test_render_compare_launched_embeds_job_panel_and_result_url():
    out = cp.render_compare_launched("c" * 32, "tok")
    assert "class='job-panel'" in out
    assert f"/report/{'c' * 32}" in out


# --------------------------------------------------------------------------- #
#  render_compare_done                                                        #
# --------------------------------------------------------------------------- #
def _real_compare_result(make_df, closes=None):
    closes = closes or [100 + i * 0.5 for i in range(150)]
    df = make_df(closes)
    kw = dict(stop_loss=None, take_profit=None, trailing_stop=None,
             position_sizing=None, target_vol=None)
    rows = [{"name": build_strategy(k).name,
            "metrics": Backtester(**kw).run(df, build_strategy(k)).metrics}
           for k in STRATEGIES]
    buy_hold = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
    return {"kind": "compare", "rows": rows, "buy_hold": buy_hold,
            "context": {"symbol": "ETH/USD", "timeframe": "1d"}}


def test_render_compare_done_shows_buy_hold_row_and_all_strategies(make_df):
    result = _real_compare_result(make_df)
    out = cp.render_compare_done(result)
    assert "Buy &amp; Hold" in out
    for key in STRATEGIES:
        assert build_strategy(key).name in out
    assert "IN-SAMPLE" in out
    assert "ETH/USD" in out
    assert "<nav class='nav'>" in out


def test_render_compare_done_highlights_when_nothing_beats_buy_hold(make_df):
    # Marche monotone haussier : Buy & Hold gagne large sur toutes les
    # strategies actives (moins de temps investi = moins de rendement ici).
    closes = [100 + i * 2 for i in range(150)]
    result = _real_compare_result(make_df, closes=closes)
    # Force le constat honnete : aucune strategie ne bat un Buy & Hold ecrase.
    result["buy_hold"] = 10_000.0
    out = cp.render_compare_done(result)
    assert "0 strategie ne bat Buy" in out


def test_render_compare_done_no_warning_when_a_strategy_beats_buy_hold(make_df):
    result = _real_compare_result(make_df)
    result["buy_hold"] = -10_000.0  # garanti battu par toute strategie
    out = cp.render_compare_done(result)
    assert "0 strategie ne bat Buy" not in out
