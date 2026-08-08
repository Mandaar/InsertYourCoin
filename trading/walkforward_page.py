"""
Ecran Recherche / Walk-forward (/research/walkforward) -- fonctions PURES de
rendu et de parsing (testables sans serveur, sans reseau, cf.
docs/UI_UX_WEBAPP_SPEC.md §4.6). LE JUGE du projet : optimisation glissante
hors-echantillon, multi-actifs, holdout sacre, validation finale unique.
Equivalent web de `python main.py walkforward`.

Meme patron que trading/optimize_page.py / portfolio_page.py (Lot 5) :
formulaire -> job async (trading/research_runners.run_walkforward) -> panneau
de progression -> resultat rendu par render_walkforward_done (appele depuis
trading/report_page.py render_result_done, Lot 6).

Le runner (research_runners.run_walkforward) est TOUJOURS multi-actifs
(walk_forward_multi), meme pour un seul symbole : `result["results"]` est donc
toujours un dict {symbole: dict EXACT de optimizer.walk_forward}, jamais une
forme mono-actif distincte -- pas de dispatch a deviner ici.
"""
import html
import math

from .optimizer import MIN_TRADES
from . import metrics_format as fmt
from .portfolio_page import DEFAULT_SYMBOLS, parse_symbols
from .research_page import (
    parse_risk_fields, parse_timeframe_days_source, strategy_options, timeframe_options,
)
from .strategies import STRATEGIES
from .webui import job_panel_html, page_shell, research_subnav_html

METRIC_CHOICES = ("sharpe", "sortino", "calmar", "total_return", "profit_factor")
# B5/optimizer.py : le defaut walk-forward (0.5) DIFFERE du defaut optimize (0.6)
# -- volontairement PAS partage avec optimize_page.DEFAULT_TRAIN_FRAC (gotcha
# documente : un formulaire commun ne doit pas unifier ces deux defauts).
DEFAULT_TRAIN_FRAC = 0.5
DEFAULT_WINDOWS = 4
# Wireframe spec §4.6 : holdout sacre pre-rempli a 20% (encourage la separation
# honnete par defaut plutot qu'un holdout desactive par omission).
DEFAULT_HOLDOUT_PCT = 20.0

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.muted { color: #8b97a6; }
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.wf-form .row { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 14px; }
.wf-form .field { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.wf-form .field.wide { min-width: 280px; flex: 1; }
.wf-form label.flabel { font-size: 12px; color: #9fb0c3; }
.wf-form input, .wf-form select { padding: 8px 10px; background: #0e1116;
  color: #d7dee8; border: 1px solid #2a333f; border-radius: 6px;
  font-family: ui-monospace, Consolas, monospace; font-size: 13px; }
.radio-row { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; }
.radio-row label { display: flex; align-items: center; gap: 6px; cursor: pointer;
  font-size: 13px; color: #d7dee8; }
.check-row { display: flex; align-items: center; gap: 8px; margin: 10px 0 4px; }
.check-row label { font-size: 13px; color: #f0b429; font-weight: 600; cursor: pointer; }
.btn { background: #1f6feb; color: #fff; border: none; border-radius: 7px;
  padding: 10px 18px; font-size: 14px; cursor: pointer; }
.btn:hover { background: #2a7bff; }
.errors { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.errors ul { margin: 4px 0 0; padding-left: 18px; }
.busy { background: #3a2a12; border: 1px solid #f0b429; color: #ffd98a;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.honesty { font-size: 12px; color: #9fb0c3; line-height: 1.6; }
.ignored { background: #3a2a12; border: 1px solid #f0b429; color: #ffd98a;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-size: 13px; }
.ignored ul, .errors ul { margin: 4px 0 0; padding-left: 18px; }

/* Bandeau verdict -- element le plus visible de toute l'app (spec §4.6). */
.verdict-banner { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
  border-radius: 10px; padding: 16px 20px; margin-bottom: 14px; border: 1px solid; }
.verdict-banner .v-icon { font-size: 24px; line-height: 1; }
.verdict-banner .v-label { font-size: 22px; font-weight: 800; letter-spacing: .02em; }
.verdict-banner .v-detail { font-size: 13px; opacity: .85; font-family: ui-monospace, Consolas, monospace; }
.verdict-banner.v-green { background: rgba(70,196,111,.12); border-color: #46c46f; color: #7ee6a0; }
.verdict-banner.v-orange { background: rgba(240,180,41,.12); border-color: #f0b429; color: #ffd98a; }
.verdict-banner.v-red { background: rgba(229,83,75,.12); border-color: #e5534b; color: #ffb4ad; }

.holdout-state { font-size: 13px; }
.holdout-state.holdout-consumed { border-color: #f0b429; background: #3a2a12; color: #ffd98a; }
.result-error { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad; }

/* Verdict holdout par actif (BUG-011) -- meme palette que .verdict-banner. */
.holdout-verdict { font-size: 13px; margin: 8px 0 0; padding: 6px 10px;
  border-radius: 6px; display: inline-block; }
.holdout-verdict.v-green { background: rgba(70,196,111,.12); color: #7ee6a0; }
.holdout-verdict.v-orange { background: rgba(240,180,41,.12); color: #ffd98a; }
.holdout-verdict.v-red { background: rgba(229,83,75,.12); color: #ffb4ad; }

.wf-card .wf-sym-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  margin-bottom: 8px; }
.wf-sym-head .wf-sym-name { font-weight: 700; color: #d6aa5a; font-size: 14px; }
table.wf-windows { width: 100%; border-collapse: collapse; font-size: 12.5px;
  font-family: ui-monospace, Consolas, monospace; }
table.wf-windows th, table.wf-windows td { text-align: right; padding: 7px 9px;
  border-bottom: 1px solid #232b36; }
table.wf-windows th:first-child, table.wf-windows td:first-child,
table.wf-windows th:nth-child(2), table.wf-windows td.params { text-align: left; }
table.wf-windows th { color: #9fb0c3; font-weight: 500; font-size: 10.5px;
  text-transform: uppercase; letter-spacing: .04em; }
.up { color: #46c46f; } .down { color: #e5534b; } .neu { color: #d7dee8; }
.wf-warn { color: #ffb4ad; font-size: 12.5px; margin: 6px 0 0; }
.wf-why { font-size: 12.5px; color: #9fb0c3; line-height: 1.6; margin-bottom: 14px; }
.wf-why summary { cursor: pointer; color: #6cb6ff; }
"""


def _esc(s):
    return html.escape("" if s is None else str(s))


def _parse_fixed_params(raw):
    """
    Parse "k=v,k=v" -> dict (int prioritaire puis float) ; "" ou None -> None.
    Fonction PURE, jamais d'exception -- retourne (dict|None, errors), meme
    convention que main._parse_fixed (main.py:54-79) mais sans sys.exit.
    """
    raw = (raw or "").strip()
    if not raw:
        return None, []
    result, errors = {}, []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            errors.append(f"Paramètres figés : '{part}' invalide (attendu k=v).")
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        try:
            result[k] = int(v)
        except ValueError:
            try:
                result[k] = float(v)
            except ValueError:
                errors.append(f"Paramètres figés : valeur non numérique pour '{k}' : '{v}'.")
    if errors:
        return None, errors
    return (result or None), []


def parse_walkforward_params(fields: dict):
    """
    Valide les champs du formulaire POST /research/walkforward. Retourne
    (params, errors) -- fonction PURE. Reprend les gardes EXACTES de la CLI
    (main.py:180-184) : holdout dans [0, 90[, --final exige holdout > 0.
    """
    strategy = (fields.get("strategy") or "").strip().lower()
    errors = []
    if strategy not in STRATEGIES:
        errors.append(f"Stratégie inconnue : {strategy or '(vide)'}.")

    metric = (fields.get("metric") or "sharpe").strip().lower()
    if metric not in METRIC_CHOICES:
        errors.append(
            f"Métrique non supportée : {metric} (attendu : {', '.join(METRIC_CHOICES)})."
        )

    raw_windows = (fields.get("windows") or "").strip()
    if not raw_windows:
        windows = DEFAULT_WINDOWS
    else:
        try:
            windows = int(float(raw_windows))
        except ValueError:
            errors.append(f"Fenêtres : valeur non numérique ({raw_windows!r}).")
            windows = None
        else:
            if windows <= 0:
                errors.append("Fenêtres : doit être un entier positif.")

    raw_train_frac = (fields.get("train_frac") or "").strip()
    if not raw_train_frac:
        train_frac = DEFAULT_TRAIN_FRAC
    else:
        try:
            train_frac = float(raw_train_frac)
        except ValueError:
            errors.append(f"Train-frac : valeur non numérique ({raw_train_frac!r}).")
            train_frac = None
        else:
            if not (0.0 < train_frac < 1.0):
                errors.append("Train-frac : attendu dans ]0, 1[.")

    fixed, fixed_errors = _parse_fixed_params(fields.get("fixed"))
    errors += fixed_errors

    raw_holdout = (fields.get("holdout") or "").strip()
    if not raw_holdout:
        holdout_pct = DEFAULT_HOLDOUT_PCT
    else:
        try:
            holdout_pct = float(raw_holdout)
        except ValueError:
            errors.append(f"Holdout : valeur non numérique ({raw_holdout!r}).")
            holdout_pct = None
        else:
            if not (0.0 <= holdout_pct < 90.0):
                errors.append("Holdout : pourcentage attendu dans [0, 90[.")

    final = (fields.get("final") or "").strip().lower() in ("1", "on", "true", "yes")
    if final and (holdout_pct is None or holdout_pct <= 0):
        errors.append(
            "Validation finale : exige un holdout > 0 (sans holdout, pas de segment sacré)."
        )

    tds, tds_errors = parse_timeframe_days_source(fields)
    errors += tds_errors
    if errors:
        return None, errors

    params = {"symbols": parse_symbols(fields.get("symbols"))}
    params.update(tds)
    params.update(parse_risk_fields(fields))
    params["strategy"] = strategy
    params["metric"] = metric
    params["windows"] = windows
    params["train_frac"] = train_frac
    params["fixed"] = fixed
    params["holdout_pct"] = holdout_pct
    params["final"] = final
    return params, []


_FINAL_CONFIRM_JS = """
<script>
(function(){
  var form = document.querySelector('.wf-form');
  var box = document.getElementById('final');
  if(!form || !box){ return; }
  form.addEventListener('submit', function(ev){
    if(box.checked){
      var ok = window.confirm(
        "À ne faire qu'une fois par stratégie : le holdout sera consommé. Continuer ?"
      );
      if(!ok){ ev.preventDefault(); }
    }
  });
})();
</script>
"""


def _form_html(csrf_token, values) -> str:
    v = dict(values or {})
    symbols = v.get("symbols") or DEFAULT_SYMBOLS
    timeframe = v.get("timeframe")
    # Spec §4.6 : Binance coche PAR DEFAUT ("historique long, recommande") --
    # INVERSE des autres ecrans de recherche (defaut kraken ailleurs).
    kraken_checked = " checked" if v.get("source") == "kraken" else ""
    binance_checked = "" if v.get("source") == "kraken" else " checked"
    final_checked = " checked" if v.get("final") in ("1", "on", True) else ""
    token = _esc(csrf_token)

    metric_opts = "".join(
        f"<option value='{m}'{' selected' if m == v.get('metric', 'sharpe') else ''}>{m}</option>"
        for m in METRIC_CHOICES
    )

    return (
        "<form class='wf-form' method='post' action='/research/walkforward'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<div class='row'>"
        "<div class='field'><label class='flabel' for='strategy'>Stratégie</label>"
        f"<select id='strategy' name='strategy'>{strategy_options(v.get('strategy'))}</select></div>"
        "<div class='field wide'><label class='flabel' for='symbols'>Symboles (séparés par des virgules)</label>"
        f"<input id='symbols' name='symbols' value='{_esc(symbols)}'></div>"
        "<div class='field'><label class='flabel' for='timeframe'>Timeframe</label>"
        f"<select id='timeframe' name='timeframe'>{timeframe_options(timeframe)}</select></div>"
        "<div class='field'><label class='flabel' for='days'>Jours</label>"
        f"<input id='days' name='days' type='number' min='1' value='{_esc(v.get('days', 720))}'></div>"
        "</div>"

        "<div class='field'><label class='flabel'>Source</label>"
        "<div class='radio-row'>"
        f"<label><input type='radio' name='source' value='binance'{binance_checked}> "
        "Binance (historique long, recommandé)</label>"
        f"<label><input type='radio' name='source' value='kraken'{kraken_checked}> "
        "Kraken (~720 bougies max)</label>"
        "</div></div>"

        "<div class='row'>"
        "<div class='field'><label class='flabel' for='windows'>Fenêtres</label>"
        f"<input id='windows' name='windows' type='number' min='1' step='1' "
        f"value='{_esc(v.get('windows', DEFAULT_WINDOWS))}'></div>"
        "<div class='field'><label class='flabel' for='train_frac'>Train-frac</label>"
        f"<input id='train_frac' name='train_frac' type='number' step='0.05' min='0.05' max='0.95' "
        f"value='{_esc(v.get('train_frac', DEFAULT_TRAIN_FRAC))}'></div>"
        "<div class='field'><label class='flabel' for='metric'>Métrique</label>"
        f"<select id='metric' name='metric'>{metric_opts}</select></div>"
        "</div>"

        "<div class='row'>"
        "<div class='field wide'><label class='flabel' for='fixed'>Paramètres FIGÉS (anti-data-mining, recommandé)</label>"
        f"<input id='fixed' name='fixed' value='{_esc(v.get('fixed'))}' "
        "placeholder='ex : fast=50,slow=200 (vide = mode optimisé, moins honnête)'></div>"
        "<div class='field'><label class='flabel' for='holdout'>Holdout sacré (%)</label>"
        f"<input id='holdout' name='holdout' type='number' step='1' min='0' max='89' "
        f"value='{_esc(v.get('holdout', DEFAULT_HOLDOUT_PCT))}'></div>"
        "</div>"

        "<div class='check-row'>"
        f"<input type='checkbox' id='final' name='final' value='1'{final_checked}>"
        "<label for='final'>VALIDATION FINALE (1 seule fois par stratégie !) -- consomme le holdout</label>"
        "</div>"

        "<div class='row'>"
        "<div class='field'><label class='flabel' for='stop_loss'>Stop (%)</label>"
        f"<input id='stop_loss' name='stop_loss' type='number' step='0.1' "
        f"value='{_esc(v.get('stop_loss'))}' placeholder='(désactivé)'></div>"
        "<div class='field'><label class='flabel' for='take_profit'>Objectif (%)</label>"
        f"<input id='take_profit' name='take_profit' type='number' step='0.1' "
        f"value='{_esc(v.get('take_profit'))}' placeholder='(désactivé)'></div>"
        "<div class='field'><label class='flabel' for='trailing_stop'>Trailing (%)</label>"
        f"<input id='trailing_stop' name='trailing_stop' type='number' step='0.1' "
        f"value='{_esc(v.get('trailing_stop'))}' placeholder='(désactivé)'></div>"
        "</div>"

        "<button class='btn' type='submit'>Lancer le verdict</button>"
        "</form>"
        + _FINAL_CONFIRM_JS
    )


def render_walkforward_form(csrf_token, errors=None, values=None) -> str:
    """Page complete GET /research/walkforward (formulaire vide/prerempli-defaut)."""
    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Formulaire invalide :<ul>{items}</ul></div>"

    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("walkforward")
        + "<div class='head'><h1>Recherche &mdash; Walk-forward (LE JUGE)</h1>"
        "<a class='navlink' href='/'>&larr; Accueil</a></div>"
        + errors_html
        + "<div class='card'>"
        + _form_html(csrf_token, values)
        + "</div>"
        + "<p class='muted honesty'>Le test honnête central : optimisation glissante "
          "hors-échantillon, multi-actifs, holdout sacré. C'est le walk-forward, "
          "pas le backtest, qui juge si une stratégie a un edge réel.</p>"
    )
    return page_shell("Recherche - Walk-forward - InsertYourCoin", "research", body)


def render_walkforward_busy(active_label, active_id, csrf_token) -> str:
    label = active_label or "analyse en cours"
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("walkforward")
        + "<div class='head'><h1>Recherche &mdash; Walk-forward</h1>"
        "<a class='navlink' href='/research/walkforward'>&larr; Formulaire</a></div>"
        f"<div class='busy'>Une analyse est déjà en cours : <strong>{_esc(label)}</strong>. "
        "Attends sa fin (panneau ci-dessous) ou annule-la avant d'en lancer une "
        "nouvelle -- un seul job a la fois.</div>"
        "<div class='card'>"
        + job_panel_html(active_id, csrf_token, result_url=f"/report/{active_id}")
        + "</div>"
    )
    return page_shell("Analyse en cours - InsertYourCoin", "research", body)


def render_walkforward_launched(job_id, csrf_token) -> str:
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("walkforward")
        + "<div class='head'><h1>Recherche &mdash; Walk-forward en cours</h1>"
        "<a class='navlink' href='/research/walkforward'>&larr; Formulaire</a></div>"
        "<p class='muted'>Le plus long des jobs de recherche : plusieurs fenêtres, "
        "plusieurs actifs, parfois une validation finale. Patience.</p>"
        "<div class='card'>"
        + job_panel_html(job_id, csrf_token, result_url=f"/report/{job_id}")
        + "</div>"
    )
    return page_shell("Walk-forward en cours - InsertYourCoin", "research", body)


# --------------------------------------------------------------------------- #
#  Resultat (render_walkforward_done)                                         #
# --------------------------------------------------------------------------- #
_TONE_ICON = {"green": "✓", "orange": "⚠", "red": "✗"}
_SEVERITY_RANK = {"green": 0, "orange": 1, "red": 2}


def _mono_severity(avg_window_metric, oos_total_return):
    """
    BUG-010 -- parite web/CLI pour le cas MONO-ACTIF (n_assets == 1).

    `summary["robust"]` (optimizer.walk_forward_multi) degenere pour un seul
    actif en `oos_total_return > 0` : les branches severes de la CLI
    (metrique non finie -> "indecidable" ; forte chute de metrique ->
    "sur-apprentissage probable") disparaissent completement. Cette fonction
    reproduit EXACTEMENT les 4 branches de optimizer._verdict(avg_window_metric,
    1.0, oos_total_return, wf=True) -- le meme appel que
    optimizer.format_walk_forward (optimizer.py:422), donc la meme sortie que
    `python main.py walkforward` sur un seul symbole (train_metric fige a 1.0
    pour le walk-forward -> seuil "sur-apprentissage" = 0.5).

    Aucun recalcul moteur : les 2 entrees sont DEJA dans
    result["results"][sym] (trading.optimizer.walk_forward) -- uniquement de
    la classification d'affichage. Duplication VOLONTAIRE des seuils
    (optimizer.py:528-538, evite d'importer un symbole prive pour un texte de
    terminal) ; couverte par un test de parite directe contre optimizer._verdict.
    """
    if avg_window_metric is None or not math.isfinite(avg_window_metric):
        return "orange", "INDÉCIDABLE"
    if oos_total_return is None or oos_total_return < 0 or avg_window_metric < 0:
        return "red", "NE PAS TRADER"
    if avg_window_metric < 0.5:  # 0.5 * max(train_metric=1.0, 1e-9)
        return "orange", "SUR-APPRENTISSAGE PROBABLE"
    return "green", "EDGE PLAUSIBLE"


def _holdout_severity(metric_value, total_return):
    """
    BUG-011 -- parite web/CLI pour la VALIDATION FINALE (holdout sacre).

    Reproduit optimizer._verdict(metric_value, 0.0, total_return) -- le meme
    appel que optimizer.format_holdout (optimizer.py:520). train_metric=0.0 ->
    le seuil "sur-apprentissage" (0.5 * max(0.0, 1e-9)) est quasi nul et n'est
    en pratique jamais atteint separement du cas negatif -- conserve pour la
    parite exacte. Entrees deja calculees par optimizer.holdout_check, aucun
    recalcul moteur ici.
    """
    if metric_value is None or not math.isfinite(metric_value):
        return "orange", "INDÉCIDABLE"
    if total_return is None or total_return < 0 or metric_value < 0:
        return "red", "NE PAS TRADER"
    if metric_value < 0.5 * max(0.0, 1e-9):
        return "orange", "SUR-APPRENTISSAGE PROBABLE"
    return "green", "VALIDATION CONFIRMÉE"


def _worst_holdout_verdict(holdout_results):
    """
    BUG-011 -- (tone, label) le PLUS SEVERE parmi les validations finales
    holdout rendues. Sert a qualifier/degrader le bandeau global -- jamais a
    l'ameliorer (cf. _verdict_banner : n'ecrase le tone recherche que s'il est
    STRICTEMENT plus severe, un holdout positif ne blanchit jamais un verdict
    recherche deja rouge/orange).
    """
    worst = None
    for res in (holdout_results or {}).values():
        m = res["metrics"]
        tone, label = _holdout_severity(m.get(res.get("metric")), m.get("total_return"))
        if worst is None or _SEVERITY_RANK[tone] > _SEVERITY_RANK[worst[0]]:
            worst = (tone, label)
    return worst


def _verdict_banner(result) -> str:
    """
    Bandeau verdict -- element le plus visible de toute l'app (spec §4.6).

    Multi-actifs (n_assets > 1) : source PRIMAIRE `summary["robust"]`
    (optimizer.walk_forward_multi -- SOURCE DE VERITE UNIQUE, jamais
    recalculee ici). L'orange ne scinde QUE le bucket "non robuste" (jamais le
    bucket "robuste") selon qu'au moins un actif est OOS positif -- ce n'est
    PAS un re-test du booleen, seulement un raffinement d'affichage.

    Mono-actif (n_assets == 1, BUG-010) : `summary["robust"]` degenere en
    `oos_total_return > 0` et masque les branches severes de la CLI --
    _mono_severity() restaure la parite en lisant avg_window_metric/
    oos_total_return DIRECTEMENT depuis result["results"][sym].

    BUG-011 : si une validation finale (holdout) a ete rendue et que son
    verdict le plus severe est PLUS severe que celui de la recherche, le
    bandeau est qualifie/degrade en consequence -- jamais un vert nu au-dessus
    d'un holdout negatif/indecidable.

    Icone + texte toujours (jamais la couleur seule, accessibilite spec §8).
    """
    summary = result["summary"]
    n_assets = summary["n_assets"]
    n_positive = summary["n_positive"]
    per_symbol = result["results"]

    if n_assets == 1 and per_symbol:
        sym, res = next(iter(per_symbol.items()))
        tone, label = _mono_severity(res.get("avg_window_metric"), res.get("oos_total_return"))
        n_win = len(res["windows"])
        n_prof = round(res["pct_profitable"] * n_win) if n_win else 0
        detail = f"({n_prof} / {n_win} fenêtres profitables sur {sym})"
    else:
        if summary["robust"]:
            tone, label = "green", "EDGE PLAUSIBLE"
        elif n_positive > 0:
            tone, label = "orange", "FRAGILE / MITIGÉ"
        else:
            tone, label = "red", "PAS D'EDGE FIABLE"
        detail = f"({n_positive} / {n_assets} actifs OOS positifs)"

    worst_holdout = _worst_holdout_verdict(result.get("holdout"))
    if worst_holdout and _SEVERITY_RANK[worst_holdout[0]] > _SEVERITY_RANK[tone]:
        tone, holdout_label = worst_holdout
        label = f"{label} -- VALIDATION FINALE : {holdout_label}"
        detail += f" ; holdout sacré : {holdout_label.lower()}"

    icon = _TONE_ICON[tone]
    return (
        f"<div class='verdict-banner v-{tone}'>"
        f"<span class='v-icon'>{icon}</span>"
        f"<span class='v-label'>VERDICT : {_esc(label)}</span>"
        f"<span class='v-detail'>{_esc(detail)}</span>"
        "</div>"
    )


def _ignored_block(ignored) -> str:
    if not ignored:
        return ""
    items = "".join(f"<li>{_esc(i['symbol'])} : {_esc(i['error'])}</li>" for i in ignored)
    return f"<div class='ignored'>Actif(s) non chargé(s) (données indisponibles) :<ul>{items}</ul></div>"


def _wf_errors_block(wf_errors) -> str:
    if not wf_errors:
        return ""
    items = "".join(f"<li>{_esc(sym)} : {_esc(msg)}</li>" for sym, msg in wf_errors.items())
    return f"<div class='errors'>Actif(s) en échec de walk-forward :<ul>{items}</ul></div>"


def _psr_dsr_line(res) -> str:
    psr, dsr = res.get("psr"), res.get("dsr")
    n_trials = res.get("n_trials", 1)
    return (
        f"PSR {fmt.pct(psr, signed=False)} / DSR {fmt.pct(dsr, signed=False)} "
        f"(essais testes : {n_trials})"
    )


def _windows_table(res) -> str:
    metric = res["metric"]
    rows = []
    for w in res["windows"]:
        period = f"{w['period'][0].date()} &rarr; {w['period'][1].date()}"
        bp = ", ".join(f"{k}={v}" for k, v in (w.get("params") or {}).items())
        m = w["metrics"]
        rows.append(
            "<tr>"
            f"<td>{_esc(period)}</td>"
            f"<td class='params'>{_esc(bp)}</td>"
            f"<td class='{fmt.cls(m.get(metric))}'>{fmt.num(m.get(metric))}</td>"
            f"<td class='{fmt.cls(m['total_return'])}'>{fmt.pct(m['total_return'])}</td>"
            f"<td class='down'>{fmt.pct(m['max_drawdown'], signed=False)}</td>"
            "</tr>"
        )
    return (
        "<table class='wf-windows'><thead><tr>"
        "<th>Fenêtre (hors-éch.)</th><th>Paramètres retenus</th>"
        f"<th>{_esc(metric.capitalize())}</th><th>Rendement</th><th>DD max</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _symbol_card(sym, res) -> str:
    header = (
        "<div class='wf-sym-head'>"
        f"<span class='wf-sym-name'>{_esc(sym)}</span>"
        f"<span class='{fmt.cls(res['oos_total_return'])}'>OOS cumulé : "
        f"{fmt.pct(res['oos_total_return'])}</span>"
        f"<span class='muted'>Fenêtres profitables : {fmt.pct(res['pct_profitable'], signed=False)}</span>"
        f"<span class='muted'>{_esc(_psr_dsr_line(res))}</span>"
        "</div>"
    )
    return "<div class='card wf-card'>" + header + _windows_table(res) + "</div>"


def _holdout_block(result) -> str:
    context = result["context"]
    if not context.get("final"):
        return (
            "<div class='card holdout-state'>Holdout sacré : <strong>NON consommé</strong> "
            "(aucune validation finale demandée -- coche 'Validation finale' pour "
            "l'évaluer, une seule fois par stratégie).</div>"
        )
    holdout = result.get("holdout") or {}
    holdout_errors = result.get("holdout_errors") or {}
    blocks = [
        "<div class='card holdout-state holdout-consumed'>"
        "<strong>VALIDATION FINALE</strong> -- le holdout sacré a été consommé "
        "pour le(s) actif(s) ci-dessous.</div>"
    ]
    for sym, res in holdout.items():
        m = res["metrics"]
        bp = ", ".join(f"{k}={v}" for k, v in res["params"].items())
        src = ("optimisés sur la recherche uniquement" if res["optimised_on_research"]
               else "FIGÉS, aucune optimisation")
        period = f"{res['holdout_period'][0].date()} &rarr; {res['holdout_period'][1].date()}"
        warn = ""
        if m["n_trades"] < MIN_TRADES:
            warn = (
                f"<p class='wf-warn'>Très peu de trades sur le holdout (&lt; {MIN_TRADES}) : "
                "résultat peu significatif statistiquement.</p>"
            )
        # BUG-011 : verdict CLI equivalent (optimizer._verdict via
        # _holdout_severity) toujours rendu -- pas seulement des chiffres bruts.
        v_tone, v_label = _holdout_severity(m.get(res.get("metric")), m.get("total_return"))
        verdict_html = (
            f"<p class='holdout-verdict v-{v_tone}'>{_TONE_ICON[v_tone]} "
            f"Verdict validation finale : <strong>{_esc(v_label)}</strong></p>"
        )
        blocks.append(
            "<div class='card wf-card'>"
            "<div class='wf-sym-head'>"
            f"<span class='wf-sym-name'>{_esc(sym)}</span>"
            f"<span class='{fmt.cls(m['total_return'])}'>{fmt.pct(m['total_return'])}</span>"
            "</div>"
            f"<p class='muted'>{_esc(period)} ({res['n_holdout']} bougies) &middot; "
            f"{_esc(bp)} ({_esc(src)})</p>"
            f"<p class='muted'>Sharpe : {fmt.num(m['sharpe'])} &middot; "
            f"DD max : {fmt.pct(m['max_drawdown'], signed=False)} &middot; "
            f"Trades : {m['n_trades']}</p>"
            + verdict_html
            + warn +
            "</div>"
        )
    for sym, msg in holdout_errors.items():
        blocks.append(
            f"<div class='card result-error'>Validation finale impossible pour "
            f"{_esc(sym)} : {_esc(msg)}</div>"
        )
    return "".join(blocks)


_WHY_WF_HTML = (
    "<details class='wf-why'><summary>Pourquoi le walk-forward est le juge</summary>"
    "<p>Le backtest simple choisit les meilleurs paramètres sur TOUTES les données "
    "vues -- il triche sans le savoir (in-sample). Le walk-forward ré-optimise "
    "périodiquement sur le passé, puis applique ces paramètres à la période SUIVANTE, "
    "jamais vue -- comme un bot qu'on re-règle de temps en temps. Le verdict porte "
    "sur la performance CUMULÉE hors-échantillon : c'est la mesure la plus honnête "
    "disponible ici, même si elle n'est jamais une garantie pour le futur.</p></details>"
)


def render_walkforward_done(result) -> str:
    """
    Resultat pret (spec §4.6) : bandeau VERDICT (grande typo, couleur semantique)
    + etat du holdout + une carte par actif (fenetres OOS, params retenus,
    metrique, rendement, DD) + encart pedagogique repliable. `result` = payload
    de research_runners.run_walkforward -- `result["results"]` porte les dicts
    EXACTS de trading.optimizer.walk_forward, aucune re-derivation de calcul.
    """
    context = result["context"]
    symbols = context.get("symbols") or []
    strategy = context.get("strategy") or "?"
    metric = context.get("metric") or "sharpe"

    fixed = context.get("fixed_params")
    mode = (
        "paramètres FIGÉS (" + ", ".join(f"{k}={v}" for k, v in fixed.items()) + ") "
        "-- aucune optimisation (anti-data-mining)"
        if fixed else
        "paramètres OPTIMISÉS sur chaque train (re-sélection de la grille)"
    )

    cards = "".join(_symbol_card(sym, res) for sym, res in result["results"].items())

    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("walkforward")
        + "<div class='head'><h1>Recherche &mdash; Walk-forward</h1>"
        "<a class='navlink' href='/research/walkforward'>&larr; Nouveau walk-forward</a></div>"
        + f"<p class='muted'>{_esc(strategy.upper())} &middot; {_esc(', '.join(symbols))} "
          f"&middot; {_esc(context.get('timeframe') or '1d')} &middot; critère : {_esc(metric)}"
          f"<br>{_esc(mode)}</p>"
        + _verdict_banner(result)
        + _ignored_block(result.get("ignored"))
        + _wf_errors_block(result.get("wf_errors"))
        + _holdout_block(result)
        + cards
        + _WHY_WF_HTML
    )
    title = f"Walk-forward - {strategy} - InsertYourCoin"
    return page_shell(title, "research", body)
