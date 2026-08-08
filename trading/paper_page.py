"""
Ecran Paper (/paper) -- fonctions PURES de rendu et de parsing (testables sans
serveur, sans reseau, cf. docs/UI_UX_WEBAPP_SPEC.md §4.9, Lot 7). Configure et
demarre/arrete le paper trading depuis l'UI (remplace les constantes PAPER_*
en tete de lancer.py).

Aucune I/O ici : `parse_paper_params` prend un dict de chaines DEJA extrait du
POST par trading/monitor.py (meme convention que /research/*) et rend soit des
params valides pour lancer.build_paper_command_params, soit une liste
d'erreurs -- jamais d'exception. `compute_paper_status` traduit (running,
start_ts) en un statut affichable -- aucune lecture de fichier ici non plus
(monitor.py fournit ces valeurs, deja lues via lancer.read_pid_file /
is_our_process, BUG-009 : jamais de PID recycle traite comme vivant).

Securite (spec §4.9) : AUCUNE cle requise (paper = donnees publiques) ; le
formulaire ne propose JAMAIS `source=binance` (paper = Kraken only, aucun
champ source ici) ; la commande construite passe par
lancer.build_paper_command_params -> assert_paper_only (garde-fou paper-only
EN DUR, jamais contournable depuis cet ecran).
"""
import datetime as dt
import html

import config
from .strategies import STRATEGIES, build_strategy
from .research_page import TIMEFRAME_CHOICES, parse_risk_fields
from .webui import page_shell

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
.statut-line { font-size: 15px; }
.ok { color: #46c46f; }
.no { color: #e5534b; }
.pp-form .row { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 14px; }
.pp-form .field { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.pp-form label.flabel { font-size: 12px; color: #9fb0c3; }
.pp-form input, .pp-form select { padding: 8px 10px; background: #0e1116;
  color: #d7dee8; border: 1px solid #2a333f; border-radius: 6px;
  font-family: ui-monospace, Consolas, monospace; font-size: 13px; }
.btn { background: #1f6feb; color: #fff; border: none; border-radius: 7px;
  padding: 9px 18px; font-size: 14px; cursor: pointer; }
.btn:hover { background: #2a7bff; }
.btn-stop { background: #3a1d12; color: #ffb4ad; border: 1px solid #e5534b;
  border-radius: 7px; padding: 9px 18px; font-size: 14px; cursor: pointer; }
.btn-stop:hover { background: #4a2417; }
.errors { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.errors ul { margin: 4px 0 0; padding-left: 18px; }
.saved { background: #12331d; border: 1px solid #46c46f; color: #9ff0b8;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-weight: 600; }
.alert { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-weight: 600; }
.honesty { font-size: 12px; color: #9fb0c3; line-height: 1.6; }
"""

# Defauts actuels de lancer.py (constantes PAPER_* remplacees par cet ecran,
# cf. spec §4.9 : "Les parametres remplacent les constantes en tete de
# lancer.py"). Symbole : None -> resolu depuis config.DEFAULT_SYMBOL au rendu
# (meme convention que trading/research_page.py DEFAULT_FORM_VALUES).
DEFAULT_FORM_VALUES = {
    "strategy": "sma",
    "symbol": None,
    "timeframe": "5m",
    "stop_loss": "5",
    "take_profit": "10",
    "trailing_stop": "8",
    "position_sizing": "none",
    "target_vol": "",
}


def _esc(s):
    return html.escape("" if s is None else str(s))


def parse_paper_params(fields: dict):
    """
    Valide les champs du formulaire POST /paper (action=start). `fields` = dict
    de chaines DEJA extraites (meme convention que parse_backtest_params).
    Retourne (params, errors) :
    - succes -> (dict pret pour lancer.build_paper_command_params, [])
    - echec  -> (None, [messages FR actionnables])
    Fonction PURE (aucune I/O, aucun reseau) -- testable directement. AUCUN
    champ `source` : le paper est TOUJOURS Kraken (spec §4.9).
    """
    strategy = (fields.get("strategy") or "").strip().lower()
    errors = []
    if strategy not in STRATEGIES:
        errors.append(f"Strategie inconnue : {strategy or '(vide)'}.")

    symbol = (fields.get("symbol") or "").strip() or config.DEFAULT_SYMBOL

    timeframe = (fields.get("timeframe") or "").strip() or "5m"
    if timeframe not in TIMEFRAME_CHOICES:
        errors.append(
            f"Timeframe non supporte : {timeframe} "
            f"(attendu : {', '.join(TIMEFRAME_CHOICES)})."
        )

    risk = parse_risk_fields(fields)  # reutilise trading/research_page.py

    if errors:
        return None, errors

    params = {"strategy": strategy, "symbol": symbol, "timeframe": timeframe}
    params.update(risk)
    return params, []


def compute_paper_status(running: bool, start_ts, now_ts=None) -> dict:
    """
    Fonction PURE : traduit (running, start_ts epoch) en statut affichable.
    `start_ts` (float, epoch) vient de lancer.read_pid_start -- l'horodatage de
    demarrage REEL du process (create_time() si psutil dispo), pas une estimation.
    `now_ts` reste accepte pour rester dans la meme convention que
    trading/monitor.py compute_view (parametre injectable, testable) meme s'il
    n'est pas utilise dans le calcul actuel.
    """
    since = None
    if running and start_ts:
        try:
            since = dt.datetime.fromtimestamp(float(start_ts)).strftime("%Y-%m-%d %H:%M")
        except (OSError, OverflowError, ValueError):
            since = None
    return {"running": bool(running), "since": since}


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
    timeframe = v.get("timeframe") or "5m"
    vol_checked = " selected" if v.get("position_sizing") == "vol" else ""
    none_checked = " selected" if v.get("position_sizing", "none") != "vol" else ""
    token = _esc(csrf_token)

    return (
        "<form class='pp-form' method='post' action='/paper'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<input type='hidden' name='action' value='start'>"
        "<div class='row'>"
        "<div class='field'><label class='flabel' for='strategy'>Strategie</label>"
        f"<select id='strategy' name='strategy'>{strategy_options(v.get('strategy'))}</select></div>"
        "<div class='field'><label class='flabel' for='symbol'>Symbole</label>"
        f"<input id='symbol' name='symbol' value='{_esc(symbol)}'></div>"
        "<div class='field'><label class='flabel' for='timeframe'>Timeframe</label>"
        f"<select id='timeframe' name='timeframe'>{timeframe_options(timeframe)}</select></div>"
        "</div>"

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

        "<button class='btn' type='submit'>Demarrer le paper trading</button>"
        "</form>"
    )


def _stop_form_html(csrf_token) -> str:
    token = _esc(csrf_token)
    return (
        "<form method='post' action='/paper' style='display:inline-block;margin-right:10px'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<input type='hidden' name='action' value='stop'>"
        "<button class='btn-stop' type='submit'>Arreter</button>"
        "</form>"
    )


def render_paper_page(status, csrf_token, errors=None, values=None,
                      message=None, inactif=False, age_seconds=None) -> str:
    """
    Page complete GET/POST /paper (fonction PURE, testable sans serveur).
    `status` = compute_paper_status(...). `errors`/`values` re-affichent le
    formulaire apres un POST invalide (meme convention que research_page).
    `message` = bandeau de confirmation (demarre/arrete). `inactif`/`age_seconds`
    = alerte reprise de trading/monitor.py compute_view (>360s sans cycle).
    """
    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Action refusee :<ul>{items}</ul></div>"

    message_html = f"<div class='saved'>{_esc(message)}</div>" if message else ""

    if status.get("running"):
        since = _esc(status.get("since") or "?")
        inactif_html = ""
        if inactif:
            age_txt = f"{int(age_seconds)}" if age_seconds is not None else "?"
            inactif_html = (
                "<div class='alert'>ATTENTION : aucun cycle depuis "
                f"{age_txt}s (paper inactif ?)</div>"
            )
        status_card = (
            "<div class='card'><h2>Statut</h2>"
            f"<p class='statut-line'>Statut : <strong class='ok'>EN COURS</strong> "
            f"depuis {since}</p>"
            + inactif_html
            + _stop_form_html(csrf_token)
            + "<a class='navlink' href='/monitoring'>Voir le monitoring &rarr;</a>"
            "</div>"
            "<p class='muted honesty'>Demarrer/arreter ne touche pas a "
            "l'historique accumule : paper_stats.csv et paper_trades.log "
            "continuent d'exister, et reprennent au prochain demarrage.</p>"
        )
    else:
        status_card = (
            "<div class='card'><h2>Statut</h2>"
            "<p class='statut-line'>Statut : <strong class='no'>ARRETE</strong></p>"
            "</div>"
            "<div class='card'>" + _form_html(csrf_token, values) + "</div>"
            "<p class='muted honesty'>Aucune cle Kraken requise (le paper "
            "n'utilise que des donnees publiques et de l'argent fictif). "
            "L'historique existant (paper_stats.csv) est conserve et "
            "continuera de grandir au demarrage.</p>"
        )

    body = (
        f"<style>{_CSS}</style>"
        + "<div class='head'><h1>Paper trading</h1>"
        "<a class='navlink' href='/monitoring'>Monitoring &rarr;</a></div>"
        + message_html
        + errors_html
        + status_card
    )
    return page_shell("Paper - InsertYourCoin", "paper", body, csrf=csrf_token)
