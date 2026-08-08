"""
Tests de trading/walkforward_page.py (Lot 6, /research/walkforward -- LE JUGE) :
parsing + rendu (fonctions PURES, aucun serveur). `render_walkforward_done` est
exerce sur un VRAI payload produit par research_runners.run_walkforward (donnees
synthetiques, AUCUN reseau -- meme convention que tests/test_research_runners.py)
pour verifier l'integration reelle avec optimizer.walk_forward_multi/holdout_check.

Le bandeau verdict (_verdict_banner) lit `result["summary"]` tel quel (SOURCE DE
VERITE UNIQUE, jamais recalculee cote rendu -- cf. optimizer.py commentaire
lignes 326-329) POUR LE CAS MULTI-ACTIFS SEULEMENT. Pour le cas MONO-ACTIF
(n_assets == 1, BUG-010), le bandeau lit directement avg_window_metric /
oos_total_return de result["results"][sym] via wf._mono_severity -- les tests
de verdict mono mutent donc CES champs (pas `summary`, qui est ignore dans ce
cas). Les tests "*_mono_parity_with_cli*" verifient que wf._mono_severity ne
diverge JAMAIS de optimizer._verdict sur les memes entrees (parite stricte).
"""
import numpy as np
import pytest

from trading import research_runners as rr
from trading import walkforward_page as wf
from trading.optimizer import _verdict as cli_verdict
from trading.strategies import STRATEGIES


def _oscillating(n, period=12.0, amp=20.0, base=100.0):
    t = np.arange(n)
    return base + amp * np.sin(t / period)


_SERIES_PARAMS = {
    "ETH/USD": {"base": 50.0, "period": 9.0},
    "BTC/USD": {"base": 100.0, "period": 12.0},
}


class _FakeProgress:
    """Double minimal de trading.jobs.JobProgress (aucun thread reel)."""

    def __init__(self):
        self.logs = []
        self.cancelled = False

    def log(self, message):
        self.logs.append(str(message))

    def set_percent(self, value):
        pass


def _real_result(make_df, monkeypatch, symbols=("ETH/USD",), **overrides):
    """Payload REEL de research_runners.run_walkforward (Lot 6), sans reseau
    (_load_basket_ohlcv monkeypatche). Mode parametres FIGES par defaut (jamais
    de risque de _best_on -> (None, None), cf. gotcha documente dans le WIP)."""
    data = {}
    for sym in symbols:
        p = _SERIES_PARAMS.get(sym, {"base": 30.0, "period": 11.0})
        data[sym] = make_df(_oscillating(600, base=p["base"], period=p["period"]))
    monkeypatch.setattr(rr, "_load_basket_ohlcv", lambda params, progress: (data, []))

    params = {
        "symbols": list(symbols), "strategy": "sma", "timeframe": "1d", "days": 600,
        "source": "kraken", "metric": "sharpe", "windows": 4, "train_frac": 0.5,
        "fixed": {"fast": 10, "slow": 50}, "holdout_pct": 0.0, "final": False,
        "stop_loss": None, "take_profit": None, "trailing_stop": None,
        "position_sizing": "none", "target_vol": None,
    }
    params.update(overrides)
    return rr.run_walkforward(params, _FakeProgress())


# --------------------------------------------------------------------------- #
#  parse_walkforward_params                                                   #
# --------------------------------------------------------------------------- #
def test_parse_walkforward_params_defaults_on_minimal_valid_input():
    params, errors = wf.parse_walkforward_params({"strategy": "sma"})
    assert errors == []
    assert params["strategy"] == "sma"
    assert params["metric"] == "sharpe"
    assert params["windows"] == wf.DEFAULT_WINDOWS
    assert params["train_frac"] == wf.DEFAULT_TRAIN_FRAC
    assert params["holdout_pct"] == wf.DEFAULT_HOLDOUT_PCT
    assert params["final"] is False
    assert params["fixed"] is None
    assert params["symbols"] == ["BTC/USD", "ETH/USD", "SOL/USD"]


def test_parse_walkforward_params_full_valid_input():
    fields = {
        "strategy": "tsmom", "symbols": "BTC/USD,ETH/USD", "timeframe": "1h",
        "days": "365", "source": "binance", "metric": "sortino", "windows": "6",
        "train_frac": "0.6", "fixed": "lookback=200", "holdout": "15", "final": "1",
    }
    params, errors = wf.parse_walkforward_params(fields)
    assert errors == []
    assert params["symbols"] == ["BTC/USD", "ETH/USD"]
    assert params["metric"] == "sortino"
    assert params["windows"] == 6
    assert params["train_frac"] == 0.6
    assert params["fixed"] == {"lookback": 200}
    assert params["holdout_pct"] == 15.0
    assert params["final"] is True


def test_parse_walkforward_params_unknown_strategy_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "n-existe-pas"})
    assert params is None
    assert any("Stratégie inconnue" in e for e in errors)


def test_parse_walkforward_params_unknown_metric_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "metric": "bogus"})
    assert params is None
    assert any("Métrique non supportée" in e for e in errors)


def test_parse_walkforward_params_unknown_timeframe_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "timeframe": "3d"})
    assert params is None
    assert any("Timeframe non supporté" in e for e in errors)


def test_parse_walkforward_params_windows_non_positive_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "windows": "0"})
    assert params is None
    assert any("Fenêtres" in e for e in errors)


def test_parse_walkforward_params_windows_non_numeric_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "windows": "beaucoup"})
    assert params is None
    assert any("Fenêtres" in e for e in errors)


def test_parse_walkforward_params_train_frac_out_of_range_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "train_frac": "1.2"})
    assert params is None
    assert any("Train-frac" in e for e in errors)


def test_parse_walkforward_params_fixed_invalid_format_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "fixed": "fast"})
    assert params is None
    assert any("attendu k=v" in e for e in errors)


def test_parse_walkforward_params_fixed_non_numeric_value_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "fixed": "fast=abc"})
    assert params is None
    assert any("non numérique" in e for e in errors)


# Gardes reprises EXACTEMENT de main.py cmd_walkforward (lignes 181-184).
def test_parse_walkforward_params_holdout_out_of_range_is_error_exact_cli_message():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "holdout": "95"})
    assert params is None
    assert "Holdout : pourcentage attendu dans [0, 90[." in errors


def test_parse_walkforward_params_holdout_negative_is_error():
    params, errors = wf.parse_walkforward_params({"strategy": "sma", "holdout": "-1"})
    assert params is None
    assert "Holdout : pourcentage attendu dans [0, 90[." in errors


def test_parse_walkforward_params_final_without_holdout_is_error_exact_cli_message():
    params, errors = wf.parse_walkforward_params(
        {"strategy": "sma", "holdout": "0", "final": "1"}
    )
    assert params is None
    assert (
        "Validation finale : exige un holdout > 0 (sans holdout, pas de segment sacré)."
        in errors
    )


def test_parse_walkforward_params_final_with_holdout_is_valid():
    params, errors = wf.parse_walkforward_params(
        {"strategy": "sma", "holdout": "20", "final": "1"}
    )
    assert errors == []
    assert params["final"] is True
    assert params["holdout_pct"] == 20.0


# --------------------------------------------------------------------------- #
#  render_walkforward_form                                                    #
# --------------------------------------------------------------------------- #
def test_render_walkforward_form_lists_strategies_metrics_and_default_holdout():
    out = wf.render_walkforward_form("tok-secret")
    for key in STRATEGIES:
        assert f"value='{key}'" in out
    for m in wf.METRIC_CHOICES:
        assert f"value='{m}'" in out
    assert "name='csrf_token' value='tok-secret'" in out
    assert "action='/research/walkforward'" in out
    assert "research-subnav" in out
    assert "id='holdout'" in out
    assert "value='20.0'" in out  # DEFAULT_HOLDOUT_PCT pre-rempli (spec wireframe)


def test_render_walkforward_form_defaults_to_binance_source():
    # Gotcha documente dans le WIP : l'ecran walk-forward inverse le defaut des
    # autres ecrans de recherche (binance par defaut ici, kraken ailleurs).
    out = wf.render_walkforward_form("tok")
    assert "value='binance' checked>" in out
    assert "value='kraken'>" in out


def test_render_walkforward_form_final_checkbox_unchecked_by_default():
    out = wf.render_walkforward_form("tok")
    assert "<input type='checkbox' id='final' name='final' value='1'>" in out


def test_render_walkforward_form_embeds_confirm_modal_js():
    out = wf.render_walkforward_form("tok")
    assert "window.confirm(" in out
    assert "le holdout sera consommé" in out


def test_render_walkforward_form_shows_errors_and_repopulates_values():
    out = wf.render_walkforward_form(
        "tok", errors=["Holdout : pourcentage attendu dans [0, 90[."],
        values={"symbols": "BTC/USD,ETH/USD"},
    )
    assert "Holdout : pourcentage attendu dans [0, 90[." in out
    assert "value='BTC/USD,ETH/USD'" in out


# --------------------------------------------------------------------------- #
#  render_walkforward_busy / render_walkforward_launched                      #
# --------------------------------------------------------------------------- #
def test_render_walkforward_busy_shows_label_and_job_panel():
    out = wf.render_walkforward_busy("Walk-forward sma ETH/USD (1d)", "a" * 32, "tok")
    assert "Walk-forward sma ETH/USD (1d)" in out
    assert "class='job-panel'" in out
    assert f"/report/{'a' * 32}" in out


def test_render_walkforward_launched_embeds_job_panel():
    out = wf.render_walkforward_launched("c" * 32, "tok")
    assert "class='job-panel'" in out
    assert f"/report/{'c' * 32}" in out


# --------------------------------------------------------------------------- #
#  render_walkforward_done -- bandeau VERDICT (element le plus visible)       #
# --------------------------------------------------------------------------- #
def _set_mono_result(result, avg_window_metric, oos_total_return):
    """Mono-actif (n_assets == 1, BUG-010) : le bandeau ignore desormais
    `summary["robust"]` et lit avg_window_metric/oos_total_return DIRECTEMENT
    depuis result["results"][sym] -- ce helper mute ces champs (pas summary,
    qui n'est plus la source pour ce cas)."""
    sym = next(iter(result["results"]))
    res = dict(result["results"][sym], avg_window_metric=avg_window_metric,
              oos_total_return=oos_total_return)
    result["results"] = {sym: res}
    result["summary"] = dict(result["summary"], n_assets=1,
                             n_positive=(1 if oos_total_return and oos_total_return > 0 else 0))
    return result


def test_render_walkforward_done_verdict_green_when_robust(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch)
    result = _set_mono_result(result, avg_window_metric=0.8, oos_total_return=0.05)
    out = wf.render_walkforward_done(result)
    assert "v-green" in out
    assert "EDGE PLAUSIBLE" in out


def test_render_walkforward_done_verdict_orange_when_fragile(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch, symbols=("BTC/USD", "ETH/USD"))
    result["summary"] = dict(result["summary"], robust=False, n_positive=1, n_assets=2)
    out = wf.render_walkforward_done(result)
    assert "v-orange" in out
    assert "FRAGILE" in out
    assert "MITIGÉ" in out


def test_render_walkforward_done_verdict_red_when_no_edge(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch)
    result = _set_mono_result(result, avg_window_metric=-0.4, oos_total_return=-0.10)
    out = wf.render_walkforward_done(result)
    assert "v-red" in out
    assert "NE PAS TRADER" in out


def test_render_walkforward_done_verdict_banner_pairs_icon_with_label(make_df, monkeypatch):
    # Daltonisme (spec §8) : jamais la couleur seule -- icone ET libelle textuel
    # doivent accompagner la classe de couleur du bandeau.
    result = _real_result(make_df, monkeypatch)
    result = _set_mono_result(result, avg_window_metric=-0.4, oos_total_return=-0.10)
    out = wf.render_walkforward_done(result)
    assert "v-icon" in out
    assert "v-label" in out
    assert "VERDICT :" in out


# --------------------------------------------------------------------------- #
#  BUG-010 -- parite mono-actif web/CLI (sur-apprentissage / indecidable)     #
# --------------------------------------------------------------------------- #
def test_render_walkforward_done_mono_orange_overfit_scenario_never_green(make_df, monkeypatch):
    # Scenario exact du ticket BUG-010 : 4 fenetres, sharpe moyen 0.2 (fini),
    # OOS cumule legerement positif (+0.4%) -> CLI dit "sur-apprentissage
    # probable" (optimizer._verdict: 0.2 < 0.5). Avant le fix : summary["robust"]
    # degenere en `oos_total_return > 0` -> bandeau VERT survendu.
    result = _real_result(make_df, monkeypatch)
    result = _set_mono_result(result, avg_window_metric=0.2, oos_total_return=0.004)
    out = wf.render_walkforward_done(result)
    assert "<div class='verdict-banner v-green'>" not in out
    assert "<div class='verdict-banner v-orange'>" in out
    assert "SUR-APPRENTISSAGE PROBABLE" in out


def test_render_walkforward_done_mono_orange_when_metric_nan_is_indecidable(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch)
    result = _set_mono_result(result, avg_window_metric=float("nan"), oos_total_return=0.01)
    out = wf.render_walkforward_done(result)
    assert "<div class='verdict-banner v-green'>" not in out
    assert "<div class='verdict-banner v-orange'>" in out
    assert "INDÉCIDABLE" in out


def test_mono_severity_parity_with_cli_verdict_across_scenarios():
    # V16 : chaque scenario est verifie INDIVIDUELLEMENT contre optimizer._verdict
    # (le meme appel que la CLI, cf. optimizer.py:422) -- jamais un echantillon.
    scenarios = [
        (float("nan"), 0.01, "indecidable"),
        (float("inf"), 0.01, "indecidable"),
        (-0.4, -0.1, "negative"),
        (0.2, 0.004, "sur-apprentissage"),
        (0.9, 0.05, None),  # succes (pas de mot-cle d'alarme)
    ]
    for avg_metric, oos, keyword in scenarios:
        tone, label = wf._mono_severity(avg_metric, oos)
        cli_lines = cli_verdict(avg_metric, 1.0, oos, wf=True)
        cli_text = " ".join(cli_lines)
        if keyword in ("indecidable", "sur-apprentissage"):
            assert keyword in cli_text, (avg_metric, oos, cli_text)
            assert tone == "orange", (avg_metric, oos, tone, cli_text)
        elif keyword == "negative":
            assert "negative" in cli_text or "Ne pas trader" in cli_text
            assert tone == "red", (avg_metric, oos, tone, cli_text)
        else:
            assert cli_lines[0].startswith("✓"), (avg_metric, oos, cli_text)
            assert tone == "green", (avg_metric, oos, tone, cli_text)


# --------------------------------------------------------------------------- #
#  render_walkforward_done -- holdout sacre                                   #
# --------------------------------------------------------------------------- #
def test_render_walkforward_done_holdout_not_consumed_by_default(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch)
    out = wf.render_walkforward_done(result)
    assert "NON consommé" in out
    # La classe CSS `.holdout-consumed` existe dans le <style> (regle) mais ne
    # doit etre appliquee a AUCUN <div> tant que --final n'a pas ete demande.
    assert "class='card holdout-state holdout-consumed'" not in out


def test_render_walkforward_done_holdout_consumed_shows_final_results(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch, holdout_pct=20.0, final=True)
    out = wf.render_walkforward_done(result)
    assert "class='card holdout-state holdout-consumed'" in out
    assert "VALIDATION FINALE" in out
    assert result["context"]["final"] is True


def test_render_walkforward_done_shows_holdout_error_per_symbol(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch, holdout_pct=20.0, final=True)
    result["holdout"] = {}
    result["holdout_errors"] = {
        "ETH/USD": "Holdout trop court (< 5 bougies). Augmente --days ou --holdout."
    }
    out = wf.render_walkforward_done(result)
    assert "Validation finale impossible pour" in out
    assert "Holdout trop court" in out


def test_render_walkforward_done_shows_low_trades_warning_on_holdout(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch, holdout_pct=20.0, final=True)
    sym = next(iter(result["holdout"]))
    h = dict(result["holdout"][sym])
    h["metrics"] = dict(h["metrics"], n_trades=2)
    result["holdout"] = {sym: h}
    out = wf.render_walkforward_done(result)
    assert "Très peu de trades sur le holdout" in out


# --------------------------------------------------------------------------- #
#  BUG-011 -- un holdout qui echoue qualifie le bandeau + verdict rendu       #
# --------------------------------------------------------------------------- #
def test_render_walkforward_done_holdout_negative_downgrades_green_banner(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch, holdout_pct=20.0, final=True)
    result = _set_mono_result(result, avg_window_metric=0.8, oos_total_return=0.05)
    sym = next(iter(result["holdout"]))
    h = dict(result["holdout"][sym])
    h["metrics"] = dict(h["metrics"], total_return=-0.2, sharpe=-0.5)
    result["holdout"] = {sym: h}
    out = wf.render_walkforward_done(result)
    # BUG-011 : le holdout negatif est STRICTEMENT plus severe (rouge) que le
    # verdict recherche (vert) -- le bandeau ne doit JAMAIS rester vert nu.
    assert "<div class='verdict-banner v-red'>" in out
    assert "<div class='verdict-banner v-green'>" not in out
    assert "VALIDATION FINALE :" in out
    assert "NE PAS TRADER" in out


def test_render_walkforward_done_holdout_negative_shows_per_symbol_verdict(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch, holdout_pct=20.0, final=True)
    sym = next(iter(result["holdout"]))
    h = dict(result["holdout"][sym])
    h["metrics"] = dict(h["metrics"], total_return=-0.2, sharpe=-0.5)
    result["holdout"] = {sym: h}
    out = wf.render_walkforward_done(result)
    assert "holdout-verdict v-red" in out
    assert "Verdict validation finale" in out
    assert "NE PAS TRADER" in out


def test_render_walkforward_done_holdout_indecidable_downgrades_banner_to_orange(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch, holdout_pct=20.0, final=True)
    result = _set_mono_result(result, avg_window_metric=0.8, oos_total_return=0.05)
    sym = next(iter(result["holdout"]))
    h = dict(result["holdout"][sym])
    h["metrics"] = dict(h["metrics"], sharpe=float("nan"))
    result["holdout"] = {sym: h}
    out = wf.render_walkforward_done(result)
    assert "<div class='verdict-banner v-orange'>" in out
    assert "<div class='verdict-banner v-green'>" not in out
    assert "INDÉCIDABLE" in out


def test_render_walkforward_done_holdout_positive_never_upgrades_bad_research_banner(make_df, monkeypatch):
    # Un holdout POSITIF ne doit jamais "blanchir" un verdict recherche deja
    # rouge -- _worst_holdout_verdict ne fait QUE degrader, jamais ameliorer.
    result = _real_result(make_df, monkeypatch, holdout_pct=20.0, final=True)
    result = _set_mono_result(result, avg_window_metric=-0.4, oos_total_return=-0.10)
    sym = next(iter(result["holdout"]))
    h = dict(result["holdout"][sym])
    h["metrics"] = dict(h["metrics"], total_return=0.15, sharpe=0.9)
    result["holdout"] = {sym: h}
    out = wf.render_walkforward_done(result)
    assert "<div class='verdict-banner v-red'>" in out
    assert "<div class='verdict-banner v-green'>" not in out


def test_holdout_severity_parity_with_cli_verdict_across_scenarios():
    scenarios = [
        (float("nan"), 0.02, "indecidable"),
        (-0.5, -0.2, "negative"),
        (0.9, 0.15, None),  # succes
    ]
    for metric_value, total_return, keyword in scenarios:
        tone, label = wf._holdout_severity(metric_value, total_return)
        cli_lines = cli_verdict(metric_value, 0.0, total_return)
        cli_text = " ".join(cli_lines)
        if keyword == "indecidable":
            assert "indecidable" in cli_text, (metric_value, total_return, cli_text)
            assert tone == "orange", (metric_value, total_return, tone, cli_text)
        elif keyword == "negative":
            assert "negative" in cli_text or "Ne pas trader" in cli_text
            assert tone == "red", (metric_value, total_return, tone, cli_text)
        else:
            assert cli_lines[0].startswith("✓"), (metric_value, total_return, cli_text)
            assert tone == "green", (metric_value, total_return, tone, cli_text)


# --------------------------------------------------------------------------- #
#  render_walkforward_done -- fenetres OOS, PSR/DSR, encart pedagogique       #
# --------------------------------------------------------------------------- #
def test_render_walkforward_done_shows_windows_table_and_psr_dsr(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch)
    out = wf.render_walkforward_done(result)
    assert "wf-windows" in out
    assert "Paramètres retenus" in out
    assert "DD max" in out
    assert "PSR" in out and "DSR" in out
    assert "Pourquoi le walk-forward est le juge" in out
    assert "<nav class='nav'>" in out


def test_render_walkforward_done_shows_ignored_and_wf_errors_blocks(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch)
    result["ignored"] = [{"symbol": "SOL/USD", "error": "indisponible"}]
    result["wf_errors"] = {
        "XRP/USD": "Pas assez de donnees pour ce walk-forward. Augmente l'historique (--days) ou reduis --windows."
    }
    out = wf.render_walkforward_done(result)
    assert "SOL/USD" in out and "indisponible" in out
    assert "XRP/USD" in out and "Pas assez de donnees" in out


def test_render_walkforward_done_no_ignored_or_errors_blocks_when_all_ok(make_df, monkeypatch):
    result = _real_result(make_df, monkeypatch)
    out = wf.render_walkforward_done(result)
    assert "class='ignored'" not in out
