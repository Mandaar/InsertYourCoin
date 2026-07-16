"""
Ecran Recherche / Backtest (/research/backtest) -- fonctions PURES de rendu et
de parsing (testables sans serveur, sans reseau, cf. docs/UI_UX_WEBAPP_SPEC.md
§4.3). Equivalent web de `python main.py backtest` + `dashboard` (le lancement
produit un job async -> redirection vers le Rapport, trading/report_page.py).

Aucune I/O ici : `parse_backtest_params` prend un dict de chaines DEJA extrait
du POST par trading/monitor.py (meme convention que `_one(name)` pour /options)
et rend soit des params valides, soit une liste d'erreurs -- jamais d'exception.
"""
import html

import config
from .strategies import STRATEGIES, build_strategy
from .webui import job_panel_html, page_shell, research_subnav_html

# Choix timeframe proposes (memes valeurs que l'aide CLI de main.py --timeframe).
TIMEFRAME_CHOICES = ("1m", "5m", "15m", "1h", "4h", "1d")

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
h2 { font-size: 14px; margin: 0 0 10px; color: #9fb0c3; text-transform: uppercase;
  letter-spacing: .5px; }
.muted { color: #6b7787; }
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.bt-form .row { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 14px; }
.bt-form .field { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.bt-form label.flabel { font-size: 12px; color: #9fb0c3; }
.bt-form input, .bt-form select { padding: 8px 10px; background: #0e1116;
  color: #d7dee8; border: 1px solid #2a333f; border-radius: 6px;
  font-family: ui-monospace, Consolas, monospace; font-size: 13px; }
.radio-row { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; }
.radio-row label { display: flex; align-items: center; gap: 6px; cursor: pointer;
  font-size: 13px; color: #d7dee8; }
.btn { background: #1f6feb; color: #fff; border: none; border-radius: 7px;
  padding: 9px 18px; font-size: 14px; cursor: pointer; }
.btn:hover { background: #2a7bff; }
.errors { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.errors ul { margin: 4px 0 0; padding-left: 18px; }
.busy { background: #3a2a12; border: 1px solid #f0b429; color: #ffd98a;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.honesty { font-size: 12px; color: #9fb0c3; line-height: 1.6; }
"""

DEFAULT_FORM_VALUES = {
    "strategy": "sma",
    "symbol": None,       # resolu depuis config.DEFAULT_SYMBOL au rendu
    "timeframe": None,    # resolu depuis config.DEFAULT_TIMEFRAME au rendu
    "days": "720",
    "source": "kraken",
    "stop_loss": "",
    "take_profit": "",
    "trailing_stop": "",
    "position_sizing": "none",
    "target_vol": "",
}


def _esc(s):
    return html.escape("" if s is None else str(s))


def _to_float_or_none(s):
    """Conversion souple : chaine vide/absente -> None ; non numerique -> None
    (champ optionnel, jamais de crash sur une saisie invalide)."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(s, default):
    s = (s or "").strip()
    if not s:
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def parse_timeframe_days_source(fields: dict):
    """
    Sous-ensemble COMMUN a tous les ecrans de recherche (Lot 5 : Comparer/
    Optimiser/Portefeuille reutilisent ce parsing, pas seulement Backtest) :
    timeframe/jours/source. Retourne (dict, errors) -- fonction PURE.
    """
    errors = []
    timeframe = (fields.get("timeframe") or "").strip() or config.DEFAULT_TIMEFRAME
    if timeframe not in TIMEFRAME_CHOICES:
        errors.append(
            f"Timeframe non supporte : {timeframe} "
            f"(attendu : {', '.join(TIMEFRAME_CHOICES)})."
        )

    days = _to_int(fields.get("days"), 720)
    if days <= 0:
        errors.append("Jours : doit etre un nombre positif.")

    source = (fields.get("source") or "kraken").strip().lower()
    if source not in ("kraken", "binance"):
        source = "kraken"

    return {"timeframe": timeframe, "days": days, "source": source}, errors


def parse_risk_fields(fields: dict):
    """
    Sous-ensemble COMMUN "risque" (stop/take-profit/trailing/sizing) --
    reutilise par les 4 ecrans de recherche (Lots 4-5). Parsing TOLERANT
    (jamais d'erreur bloquante ici, cf. _to_float_or_none) -- fonction PURE.
    """
    position_sizing = (fields.get("position_sizing") or "none").strip().lower()
    if position_sizing not in ("none", "vol"):
        position_sizing = "none"

    return {
        "stop_loss": _to_float_or_none(fields.get("stop_loss")),
        "take_profit": _to_float_or_none(fields.get("take_profit")),
        "trailing_stop": _to_float_or_none(fields.get("trailing_stop")),
        "position_sizing": position_sizing,
        "target_vol": _to_float_or_none(fields.get("target_vol")),
    }


def parse_market_and_risk_fields(fields: dict):
    """
    `symbol` + parse_timeframe_days_source + parse_risk_fields, SANS
    `strategy` (reutilise tel quel par trading/compare_page.py -- Comparer
    n'a pas de choix de strategie unique, cf. spec §4.4). Retourne
    (dict, errors) -- fonction PURE.
    """
    symbol = (fields.get("symbol") or "").strip() or config.DEFAULT_SYMBOL
    tds, errors = parse_timeframe_days_source(fields)
    if errors:
        return None, errors
    params = {"symbol": symbol}
    params.update(tds)
    params.update(parse_risk_fields(fields))
    return params, []


def parse_backtest_params(fields: dict):
    """
    Valide les champs du formulaire POST /research/backtest (`fields` = dict de
    chaines DEJA extraites, une valeur par nom). Retourne (params, errors) :
    - succes -> (dict pret pour research_runners.run_backtest, [])
    - echec  -> (None, [messages FR actionnables])
    Fonction PURE (aucune I/O, aucun reseau) -- testable directement.
    """
    strategy = (fields.get("strategy") or "").strip().lower()
    errors = []
    if strategy not in STRATEGIES:
        errors.append(f"Strategie inconnue : {strategy or '(vide)'}.")

    common, common_errors = parse_market_and_risk_fields(fields)
    errors += common_errors
    if errors:
        return None, errors

    params = dict(common)
    params["strategy"] = strategy
    return params, []


def strategy_options(selected):
    opts = []
    for key in STRATEGIES:
        label = f"{key} — {build_strategy(key).name}"
        checked = " selected" if key == selected else ""
        opts.append(f"<option value='{_esc(key)}'{checked}>{_esc(label)}</option>")
    return "".join(opts)


def timeframe_options(selected):
    opts = []
    for tf in TIMEFRAME_CHOICES:
        checked = " selected" if tf == selected else ""
        opts.append(f"<option value='{_esc(tf)}'{checked}>{_esc(tf)}</option>")
    return "".join(opts)


def _form_html(csrf_token, values) -> str:
    v = dict(DEFAULT_FORM_VALUES)
    v.update({k: val for k, val in (values or {}).items() if val is not None})
    symbol = v.get("symbol") or config.DEFAULT_SYMBOL
    timeframe = v.get("timeframe") or config.DEFAULT_TIMEFRAME
    kraken_checked = " checked" if v.get("source", "kraken") != "binance" else ""
    binance_checked = " checked" if v.get("source") == "binance" else ""
    vol_checked = " selected" if v.get("position_sizing") == "vol" else ""
    none_checked = " selected" if v.get("position_sizing", "none") != "vol" else ""
    token = _esc(csrf_token)

    return (
        "<form class='bt-form' method='post' action='/research/backtest'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<div class='row'>"
        "<div class='field'><label class='flabel' for='strategy'>Strategie</label>"
        f"<select id='strategy' name='strategy'>{strategy_options(v.get('strategy'))}</select></div>"
        "<div class='field'><label class='flabel' for='symbol'>Symbole</label>"
        f"<input id='symbol' name='symbol' value='{_esc(symbol)}'></div>"
        "<div class='field'><label class='flabel' for='timeframe'>Timeframe</label>"
        f"<select id='timeframe' name='timeframe'>{timeframe_options(timeframe)}</select></div>"
        "<div class='field'><label class='flabel' for='days'>Jours</label>"
        f"<input id='days' name='days' type='number' min='1' value='{_esc(v.get('days'))}'></div>"
        "</div>"

        "<div class='field'><label class='flabel'>Source</label>"
        "<div class='radio-row'>"
        f"<label><input type='radio' name='source' value='kraken'{kraken_checked}> "
        "Kraken (~720 bougies max)</label>"
        f"<label><input type='radio' name='source' value='binance'{binance_checked}> "
        "Binance (historique long, recherche)</label>"
        "</div></div>"

        "<div class='row'>"
        "<div class='field'><label class='flabel' for='stop_loss'>Stop (%)</label>"
        f"<input id='stop_loss' name='stop_loss' type='number' step='0.1' "
        f"value='{_esc(v.get('stop_loss'))}' placeholder='(desactive)'></div>"
        "<div class='field'><label class='flabel' for='take_profit'>Objectif (%)</label>"
        f"<input id='take_profit' name='take_profit' type='number' step='0.1' "
        f"value='{_esc(v.get('take_profit'))}' placeholder='(desactive)'></div>"
        "<div class='field'><label class='flabel' for='trailing_stop'>Trailing (%)</label>"
        f"<input id='trailing_stop' name='trailing_stop' type='number' step='0.1' "
        f"value='{_esc(v.get('trailing_stop'))}' placeholder='(desactive)'></div>"
        "<div class='field'><label class='flabel' for='position_sizing'>Sizing</label>"
        "<select id='position_sizing' name='position_sizing'>"
        f"<option value='none'{none_checked}>none (tout-ou-rien)</option>"
        f"<option value='vol'{vol_checked}>vol (cible de volatilite)</option>"
        "</select></div>"
        "<div class='field'><label class='flabel' for='target_vol'>Vol cible (%)</label>"
        f"<input id='target_vol' name='target_vol' type='number' step='1' "
        f"value='{_esc(v.get('target_vol'))}' placeholder='si sizing=vol'></div>"
        "</div>"

        "<button class='btn' type='submit'>Lancer le backtest</button>"
        "</form>"
    )


def render_backtest_form(csrf_token, errors=None, values=None) -> str:
    """
    Page complete GET /research/backtest (formulaire vide/prerempli-defaut).
    `errors` = liste de messages (re-affiche le formulaire avec les valeurs
    soumises apres un POST invalide) ; `values` = dict des valeurs a repeupler.
    """
    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Formulaire invalide :<ul>{items}</ul></div>"

    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("backtest")
        + "<div class='head'><h1>Recherche &mdash; Backtest</h1>"
        "<a class='navlink' href='/'>&larr; Accueil</a></div>"
        + errors_html
        + "<div class='card'>"
        + _form_html(csrf_token, values)
        + "</div>"
        + "<p class='muted honesty'>Le backtest teste une strategie IN-SAMPLE "
          "(sur les donnees vues) -- ce n'est pas une preuve d'edge futur. "
          "<a class='navlink' href='/research/walkforward'>Le walk-forward "
          "est le juge.</a></p>"
    )
    return page_shell("Recherche - Backtest - InsertYourCoin", "research", body)


def render_backtest_busy(active_label, active_id, csrf_token) -> str:
    """
    Rendu quand `JobManager.submit` a leve `JobBusy` (Lot 4 : un seul job a la
    fois, cf. spec §7.2) -- jamais de 2e job silencieux, jamais de crash.
    Propose d'attendre (panneau de progression du job en cours, avec son
    propre bouton Annuler) ou de revenir au formulaire une fois termine.
    """
    label = active_label or "analyse en cours"
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("backtest")
        + "<div class='head'><h1>Recherche &mdash; Backtest</h1>"
        "<a class='navlink' href='/research/backtest'>&larr; Formulaire</a></div>"
        f"<div class='busy'>Une analyse est deja en cours : <strong>{_esc(label)}</strong>. "
        "Attends sa fin (panneau ci-dessous) ou annule-la avant d'en lancer une "
        "nouvelle -- un seul job a la fois.</div>"
        "<div class='card'>"
        + job_panel_html(active_id, csrf_token, result_url=f"/report/{active_id}")
        + "</div>"
    )
    return page_shell("Analyse en cours - InsertYourCoin", "research", body)


def render_backtest_launched(job_id, csrf_token) -> str:
    """Rendu juste apres la creation reussie du job (Lot 4) : panneau de
    progression -> redirection JS automatique vers /report/<job_id> a la fin
    (cf. trading/webui.py job_panel_html)."""
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("backtest")
        + "<div class='head'><h1>Recherche &mdash; Backtest en cours</h1>"
        "<a class='navlink' href='/research/backtest'>&larr; Formulaire</a></div>"
        "<div class='card'>"
        + job_panel_html(job_id, csrf_token, result_url=f"/report/{job_id}")
        + "</div>"
    )
    return page_shell("Backtest en cours - InsertYourCoin", "research", body)
