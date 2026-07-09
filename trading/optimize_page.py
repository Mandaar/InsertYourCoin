"""
Ecran Recherche / Optimiser (/research/optimize) -- fonctions PURES de rendu et
de parsing (testables sans serveur, sans reseau, cf. docs/UI_UX_WEBAPP_SPEC.md
§4.5). Equivalent web de `python main.py optimize` : meilleurs parametres sur
le TRAIN, verifies sur le TEST (hors-echantillon) -- deux panneaux cote a cote,
le TEST typographiquement dominant (honnetete : "ce qui compte").

Meme patron que trading/research_page.py (Lot 4) : formulaire -> job async
(trading/research_runners.run_optimize) -> panneau de progression -> resultat
rendu par render_optimize_done (appele depuis trading/report_page.py
render_result_done, generalisation Lot 5).
"""
import html

import numpy as np

import config
from . import metrics_format as fmt
from .research_page import (
    parse_market_and_risk_fields, strategy_options, timeframe_options,
)
from .strategies import STRATEGIES
from .webui import job_panel_html, page_shell, research_subnav_html

METRIC_CHOICES = ("sharpe", "sortino", "calmar", "total_return", "profit_factor")
DEFAULT_TRAIN_FRAC = 0.6

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.muted { color: #6b7787; }
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.opt-form .row { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 14px; }
.opt-form .field { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.opt-form label.flabel { font-size: 12px; color: #9fb0c3; }
.opt-form input, .opt-form select { padding: 8px 10px; background: #0e1116;
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
.params-line { font-family: ui-monospace, Consolas, monospace; font-size: 13px;
  color: #d6aa5a; margin-bottom: 14px; }
.tt-cols { display: grid; grid-template-columns: 1fr 1.3fr; gap: 14px; }
@media(max-width:760px) { .tt-cols { grid-template-columns: 1fr; } }
.tt-panel { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 16px 18px; }
.tt-panel.tt-test { border-color: #d6aa5a; background: #1b1710; }
.tt-panel h3 { margin: 0 0 4px; font-size: 13px; text-transform: uppercase;
  letter-spacing: .06em; color: #9fb0c3; }
.tt-panel.tt-test h3 { color: #d6aa5a; font-weight: 700; }
.tt-panel .tt-tag { font-size: 11px; color: #6b7787; margin-bottom: 12px; }
.tt-row { display: flex; justify-content: space-between; padding: 6px 0;
  border-bottom: 1px solid #232b36; font-family: ui-monospace, Consolas, monospace;
  font-size: 13px; }
.tt-row:last-child { border-bottom: none; }
.tt-panel.tt-test .tt-row { font-size: 15px; font-weight: 700; }
.up { color: #46c46f; } .down { color: #e5534b; } .neu { color: #d7dee8; }
.overfit-warn { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 10px 14px; margin-top: 14px; font-weight: 600; }
"""


def _esc(s):
    return html.escape("" if s is None else str(s))


def parse_optimize_params(fields: dict):
    """
    Valide les champs du formulaire POST /research/optimize. Retourne
    (params, errors) -- fonction PURE. Ajoute `strategy`/`metric`/`train_frac`
    a parse_market_and_risk_fields (reutilise depuis research_page, cf. Lot 5).
    """
    strategy = (fields.get("strategy") or "").strip().lower()
    errors = []
    if strategy not in STRATEGIES:
        errors.append(f"Strategie inconnue : {strategy or '(vide)'}.")

    metric = (fields.get("metric") or "sharpe").strip().lower()
    if metric not in METRIC_CHOICES:
        errors.append(
            f"Metrique non supportee : {metric} (attendu : {', '.join(METRIC_CHOICES)})."
        )

    raw_train_frac = (fields.get("train_frac") or "").strip()
    if not raw_train_frac:
        train_frac = DEFAULT_TRAIN_FRAC
    else:
        try:
            train_frac = float(raw_train_frac)
        except ValueError:
            errors.append(f"Train-frac : valeur non numerique ({raw_train_frac!r}).")
            train_frac = None
        else:
            if not (0.0 < train_frac < 1.0):
                errors.append("Train-frac : attendu dans ]0, 1[.")

    common, common_errors = parse_market_and_risk_fields(fields)
    errors += common_errors
    if errors:
        return None, errors

    params = dict(common)
    params["strategy"] = strategy
    params["metric"] = metric
    params["train_frac"] = train_frac
    return params, []


def _form_html(csrf_token, values) -> str:
    v = dict(values or {})
    symbol = v.get("symbol") or config.DEFAULT_SYMBOL
    timeframe = v.get("timeframe") or config.DEFAULT_TIMEFRAME
    kraken_checked = " checked" if v.get("source", "kraken") != "binance" else ""
    binance_checked = " checked" if v.get("source") == "binance" else ""
    vol_checked = " selected" if v.get("position_sizing") == "vol" else ""
    none_checked = " selected" if v.get("position_sizing", "none") != "vol" else ""
    token = _esc(csrf_token)

    metric_opts = "".join(
        f"<option value='{m}'{' selected' if m == v.get('metric', 'sharpe') else ''}>{m}</option>"
        for m in METRIC_CHOICES
    )

    return (
        "<form class='opt-form' method='post' action='/research/optimize'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<div class='row'>"
        "<div class='field'><label class='flabel' for='strategy'>Strategie</label>"
        f"<select id='strategy' name='strategy'>{strategy_options(v.get('strategy'))}</select></div>"
        "<div class='field'><label class='flabel' for='symbol'>Symbole</label>"
        f"<input id='symbol' name='symbol' value='{_esc(symbol)}'></div>"
        "<div class='field'><label class='flabel' for='timeframe'>Timeframe</label>"
        f"<select id='timeframe' name='timeframe'>{timeframe_options(timeframe)}</select></div>"
        "<div class='field'><label class='flabel' for='days'>Jours</label>"
        f"<input id='days' name='days' type='number' min='1' value='{_esc(v.get('days', 720))}'></div>"
        "</div>"

        "<div class='row'>"
        "<div class='field'><label class='flabel' for='metric'>Metrique</label>"
        f"<select id='metric' name='metric'>{metric_opts}</select></div>"
        "<div class='field'><label class='flabel' for='train_frac'>Train-frac</label>"
        f"<input id='train_frac' name='train_frac' type='number' step='0.05' min='0.05' max='0.95' "
        f"value='{_esc(v.get('train_frac', DEFAULT_TRAIN_FRAC))}'></div>"
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

        "<button class='btn' type='submit'>Optimiser</button>"
        "</form>"
    )


def render_optimize_form(csrf_token, errors=None, values=None) -> str:
    """Page complete GET /research/optimize (formulaire vide/prerempli-defaut)."""
    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Formulaire invalide :<ul>{items}</ul></div>"

    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("optimize")
        + "<div class='head'><h1>Recherche &mdash; Optimiser</h1>"
        "<a class='navlink' href='/'>&larr; Accueil</a></div>"
        + errors_html
        + "<div class='card'>"
        + _form_html(csrf_token, values)
        + "</div>"
        + "<p class='muted honesty'>Les parametres sont choisis sur le TRAIN "
          "(in-sample) puis verifies sur le TEST (hors-echantillon, jamais vu "
          "pendant la selection) -- c'est le TEST qui compte.</p>"
    )
    return page_shell("Recherche - Optimiser - InsertYourCoin", "research", body)


def render_optimize_busy(active_label, active_id, csrf_token) -> str:
    label = active_label or "analyse en cours"
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("optimize")
        + "<div class='head'><h1>Recherche &mdash; Optimiser</h1>"
        "<a class='navlink' href='/research/optimize'>&larr; Formulaire</a></div>"
        f"<div class='busy'>Une analyse est deja en cours : <strong>{_esc(label)}</strong>. "
        "Attends sa fin (panneau ci-dessous) ou annule-la avant d'en lancer une "
        "nouvelle -- un seul job a la fois.</div>"
        "<div class='card'>"
        + job_panel_html(active_id, csrf_token, result_url=f"/report/{active_id}")
        + "</div>"
    )
    return page_shell("Analyse en cours - InsertYourCoin", "research", body)


def render_optimize_launched(job_id, csrf_token) -> str:
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("optimize")
        + "<div class='head'><h1>Recherche &mdash; Optimisation en cours</h1>"
        "<a class='navlink' href='/research/optimize'>&larr; Formulaire</a></div>"
        "<div class='card'>"
        + job_panel_html(job_id, csrf_token, result_url=f"/report/{job_id}")
        + "</div>"
    )
    return page_shell("Optimisation en cours - InsertYourCoin", "research", body)


def _tt_panel(label, tag, m, mtr, dominant=False):
    rows = [
        (mtr.capitalize(), fmt.num(m.get(mtr)), fmt.cls(m.get(mtr))),
        ("Rendement total", fmt.pct(m["total_return"]), fmt.cls(m["total_return"])),
        ("Drawdown max", fmt.pct(m["max_drawdown"], signed=False), "down"),
        ("Profit factor", fmt.pf(m["profit_factor"]), "neu"),
        ("Trades", str(m["n_trades"]), "neu"),
    ]
    rows_html = "".join(
        f"<div class='tt-row'><span>{_esc(lbl)}</span><span class='{c}'>{val}</span></div>"
        for lbl, val, c in rows
    )
    cls = "tt-panel tt-test" if dominant else "tt-panel"
    return f"<div class='{cls}'><h3>{_esc(label)}</h3><div class='tt-tag'>{_esc(tag)}</div>{rows_html}</div>"


def render_optimize_done(result) -> str:
    """
    Resultat pret (spec §4.5) : deux panneaux cote a cote Train/Test (le TEST
    typographiquement dominant) + encart "surapprentissage probable" si le
    test s'effondre vs le train. `result` = payload de
    research_runners.run_optimize : {"kind": "optimize", "result": {...},
    "context": {...}} ; `result["result"]` = dict EXACT de
    trading.optimizer.optimize (best_params/train/test/train_period/test_period).
    """
    res = result["result"]
    context = result["context"]
    mtr = res["metric"]
    bp = ", ".join(f"{k}={v}" for k, v in res["best_params"].items())

    train_tag = f"{res['train_period'][0].date()} &rarr; {res['train_period'][1].date()}"
    test_tag = f"{res['test_period'][0].date()} &rarr; {res['test_period'][1].date()}"
    panels = (
        "<div class='tt-cols'>"
        + _tt_panel("Train (in-sample)", train_tag, res["train"], mtr)
        + _tt_panel("Test (hors-echantillon)", test_tag, res["test"], mtr, dominant=True)
        + "</div>"
    )

    t_val, te_val = res["train"].get(mtr), res["test"].get(mtr)
    overfit = ""
    if (t_val is not None and te_val is not None and np.isfinite(t_val)
            and np.isfinite(te_val) and te_val < 0.5 * max(t_val, 1e-9)):
        overfit = (
            "<div class='overfit-warn'>Surapprentissage probable : forte chute de "
            "performance entre train et test.</div>"
        )

    symbol = context.get("symbol") or "?"
    timeframe = context.get("timeframe") or "1d"
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("optimize")
        + "<div class='head'><h1>Recherche &mdash; Optimiser</h1>"
        "<a class='navlink' href='/research/optimize'>&larr; Nouvelle optimisation</a></div>"
        + f"<p class='muted'>{_esc(res['strategy'].upper())} &middot; {_esc(symbol)} "
          f"({_esc(timeframe)}) &middot; critere : {_esc(mtr)}</p>"
        + f"<div class='params-line'>Meilleurs parametres (sur le TRAIN) : {_esc(bp)}</div>"
        + panels
        + overfit
    )
    title = f"Optimiser - {symbol} - InsertYourCoin"
    return page_shell(title, "research", body)
