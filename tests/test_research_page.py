"""
Tests de trading/research_page.py (Lot 4) : parsing du formulaire POST
/research/backtest + rendu (fonctions PURES, aucun serveur, aucun reseau).
"""
from trading import research_page as rp
from trading.strategies import STRATEGIES


# --------------------------------------------------------------------------- #
#  parse_backtest_params                                                      #
# --------------------------------------------------------------------------- #
def test_parse_backtest_params_defaults_on_minimal_valid_input():
    params, errors = rp.parse_backtest_params({"strategy": "sma"})
    assert errors == []
    assert params["strategy"] == "sma"
    assert params["symbol"]          # resolu depuis config.DEFAULT_SYMBOL
    assert params["timeframe"] in rp.TIMEFRAME_CHOICES
    assert params["days"] == 720
    assert params["source"] == "kraken"
    assert params["stop_loss"] is None
    assert params["position_sizing"] == "none"


def test_parse_backtest_params_full_valid_input():
    fields = {
        "strategy": "tsmom", "symbol": "BTC/USD", "timeframe": "1h", "days": "365",
        "source": "binance", "stop_loss": "8", "take_profit": "20",
        "trailing_stop": "12", "position_sizing": "vol", "target_vol": "40",
    }
    params, errors = rp.parse_backtest_params(fields)
    assert errors == []
    assert params == {
        "strategy": "tsmom", "symbol": "BTC/USD", "timeframe": "1h", "days": 365,
        "source": "binance", "stop_loss": 8.0, "take_profit": 20.0,
        "trailing_stop": 12.0, "position_sizing": "vol", "target_vol": 40.0,
    }


def test_parse_backtest_params_unknown_strategy_is_error():
    params, errors = rp.parse_backtest_params({"strategy": "n-existe-pas"})
    assert params is None
    assert any("Stratégie inconnue" in e for e in errors)


def test_parse_backtest_params_unknown_timeframe_is_error():
    params, errors = rp.parse_backtest_params({"strategy": "sma", "timeframe": "3d"})
    assert params is None
    assert any("Timeframe non supporté" in e for e in errors)


def test_parse_backtest_params_negative_days_is_error():
    params, errors = rp.parse_backtest_params({"strategy": "sma", "days": "-5"})
    assert params is None
    assert any("Jours" in e for e in errors)


def test_parse_backtest_params_garbage_days_falls_back_to_default():
    # Une saisie non numérique n'est PAS bloquante -- retombe sur le defaut
    # (720), coherent avec la tolerance des autres champs optionnels.
    params, errors = rp.parse_backtest_params({"strategy": "sma", "days": "beaucoup"})
    assert errors == []
    assert params["days"] == 720


def test_parse_backtest_params_unknown_source_falls_back_to_kraken():
    params, errors = rp.parse_backtest_params({"strategy": "sma", "source": "coinbase"})
    assert errors == []
    assert params["source"] == "kraken"


def test_parse_backtest_params_blank_risk_fields_become_none():
    fields = {"strategy": "sma", "stop_loss": "", "take_profit": "  ", "target_vol": "abc"}
    params, errors = rp.parse_backtest_params(fields)
    assert errors == []
    assert params["stop_loss"] is None
    assert params["take_profit"] is None
    assert params["target_vol"] is None  # non numérique -> None, pas de crash


# --------------------------------------------------------------------------- #
#  render_backtest_form                                                       #
# --------------------------------------------------------------------------- #
def test_render_backtest_form_lists_all_strategies_and_csrf_token():
    out = rp.render_backtest_form("tok-secret")
    for key in STRATEGIES:
        assert f"value='{key}'" in out
    assert "name='csrf_token' value='tok-secret'" in out
    assert "action='/research/backtest'" in out
    assert "Lancer le backtest" in out
    assert "<nav class='nav'>" in out  # coquille commune (page_shell)


def test_render_backtest_form_shows_errors_and_repopulates_values():
    out = rp.render_backtest_form(
        "tok", errors=["Timeframe non supporté : 3d."],
        values={"symbol": "SOL/USD", "timeframe": "1d"},
    )
    assert "Timeframe non supporté : 3d." in out
    assert "value='SOL/USD'" in out


def test_render_backtest_form_no_errors_by_default():
    out = rp.render_backtest_form("tok")
    assert "Formulaire invalide" not in out
    assert "<div class='errors'>" not in out


# --------------------------------------------------------------------------- #
#  render_backtest_busy / render_backtest_launched                            #
# --------------------------------------------------------------------------- #
def test_render_backtest_busy_shows_label_and_job_panel():
    out = rp.render_backtest_busy("Backtest sma ETH/USD", "a" * 32, "tok")
    assert "Backtest sma ETH/USD" in out
    assert "déjà en cours" in out
    assert "class='job-panel'" in out
    assert f"/report/{'a' * 32}" in out


def test_render_backtest_busy_handles_missing_label():
    out = rp.render_backtest_busy(None, "b" * 32, "tok")
    assert "analyse en cours" in out


def test_render_backtest_launched_embeds_job_panel_and_result_url():
    out = rp.render_backtest_launched("c" * 32, "tok")
    assert "class='job-panel'" in out
    assert f"/report/{'c' * 32}" in out
