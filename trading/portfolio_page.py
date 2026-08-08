"""
Ecran Recherche / Portefeuille (/research/portfolio) -- fonctions PURES de
rendu et de parsing (testables sans serveur, sans reseau, cf.
docs/UI_UX_WEBAPP_SPEC.md §4.7). Equivalent web de `python main.py portfolio` :
backtest multi-actifs equipondere + matrice de correlation (heatmap HTML/CSS,
sans lib) -- l'honnetete impose d'afficher la correlation en clair (~0.8
crypto = lisse mais ne protege pas d'un krach systemique, cf. CLAUDE.md).

Meme patron que trading/research_page.py (Lot 4) : formulaire -> job async
(trading/research_runners.run_portfolio) -> panneau de progression -> resultat
rendu par render_portfolio_done (appele depuis trading/report_page.py
render_result_done, generalisation Lot 5).
"""
import html

import numpy as np

import config
from . import metrics_format as fmt
from .research_page import (
    parse_risk_fields, parse_timeframe_days_source, strategy_options, timeframe_options,
)
from .strategies import STRATEGIES
from .webui import job_panel_html, page_shell, research_subnav_html

DEFAULT_SYMBOLS = "BTC/USD,ETH/USD,SOL/USD"

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.muted { color: #8b97a6; }
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.pf-form .row { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 14px; }
.pf-form .field { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.pf-form .field.wide { min-width: 280px; flex: 1; }
.pf-form label.flabel { font-size: 12px; color: #9fb0c3; }
.pf-form input, .pf-form select { padding: 8px 10px; background: #0e1116;
  color: #d7dee8; border: 1px solid #2a333f; border-radius: 6px;
  font-family: ui-monospace, Consolas, monospace; font-size: 13px; }
.radio-row { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; }
.radio-row label { display: flex; align-items: center; gap: 6px; cursor: pointer;
  font-size: 13px; color: #d7dee8; }
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
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px; margin-bottom: 14px; }
.kpi { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 12px 14px; }
.kpi .kpi-label { font-size: 10.5px; text-transform: uppercase; letter-spacing: .08em;
  color: #9fb0c3; }
.kpi .kpi-value { font-family: ui-monospace, Consolas, monospace; font-size: 20px;
  margin-top: 6px; }
table.asset-table { width: 100%; border-collapse: collapse; font-size: 13px;
  font-family: ui-monospace, Consolas, monospace; }
table.asset-table th, table.asset-table td { text-align: right; padding: 8px 10px;
  border-bottom: 1px solid #232b36; }
table.asset-table th:first-child, table.asset-table td.nm { text-align: left; }
table.asset-table th { color: #9fb0c3; font-weight: 500; font-size: 11px;
  text-transform: uppercase; letter-spacing: .05em; }
table.asset-table td.nm { color: #d6aa5a; }
.up { color: #46c46f; } .down { color: #e5534b; } .neu { color: #d7dee8; }
table.corr-table { border-collapse: collapse; font-size: 12px;
  font-family: ui-monospace, Consolas, monospace; margin-top: 8px; }
table.corr-table th, table.corr-table td { padding: 7px 10px; text-align: center; }
table.corr-table th { color: #9fb0c3; font-weight: 500; }
table.corr-table td.diag { color: #8b97a6; }
.corr-note { font-size: 12.5px; color: #9fb0c3; margin-top: 10px; line-height: 1.6; }
"""


def _esc(s):
    return html.escape("" if s is None else str(s))


def parse_symbols(raw) -> list:
    """Liste de symboles depuis une chaine "A,B,C" -- vide/absente -> defaut
    (spec §4.7 : BTC/USD,ETH/USD,SOL/USD). Jamais d'erreur bloquante ici."""
    symbols = [s.strip() for s in (raw or "").split(",") if s.strip()]
    return symbols or [s.strip() for s in DEFAULT_SYMBOLS.split(",")]


def parse_portfolio_params(fields: dict):
    """
    Valide les champs du formulaire POST /research/portfolio. Retourne
    (params, errors) -- fonction PURE. `symbols` remplace `symbol`
    (parse_market_and_risk_fields n'est PAS reutilisee ici pour le symbole --
    seulement pour timeframe/jours/source/risque).
    """
    strategy = (fields.get("strategy") or "").strip().lower()
    errors = []
    if strategy not in STRATEGIES:
        errors.append(f"Stratégie inconnue : {strategy or '(vide)'}.")

    tds, tds_errors = parse_timeframe_days_source(fields)
    errors += tds_errors
    if errors:
        return None, errors

    params = {"symbols": parse_symbols(fields.get("symbols"))}
    params.update(tds)
    params.update(parse_risk_fields(fields))
    params["strategy"] = strategy
    return params, []


def _form_html(csrf_token, values) -> str:
    v = dict(values or {})
    timeframe = v.get("timeframe") or config.DEFAULT_TIMEFRAME
    symbols = v.get("symbols") or DEFAULT_SYMBOLS
    kraken_checked = " checked" if v.get("source", "kraken") != "binance" else ""
    binance_checked = " checked" if v.get("source") == "binance" else ""
    vol_checked = " selected" if v.get("position_sizing") == "vol" else ""
    none_checked = " selected" if v.get("position_sizing", "none") != "vol" else ""
    token = _esc(csrf_token)

    return (
        "<form class='pf-form' method='post' action='/research/portfolio'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<div class='row'>"
        "<div class='field wide'><label class='flabel' for='symbols'>Symboles (séparés par des virgules)</label>"
        f"<input id='symbols' name='symbols' value='{_esc(symbols)}'></div>"
        "<div class='field'><label class='flabel' for='strategy'>Stratégie</label>"
        f"<select id='strategy' name='strategy'>{strategy_options(v.get('strategy'))}</select></div>"
        "</div>"

        "<div class='row'>"
        "<div class='field'><label class='flabel' for='timeframe'>Timeframe</label>"
        f"<select id='timeframe' name='timeframe'>{timeframe_options(timeframe)}</select></div>"
        "<div class='field'><label class='flabel' for='days'>Jours</label>"
        f"<input id='days' name='days' type='number' min='1' value='{_esc(v.get('days', 720))}'></div>"
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
        f"value='{_esc(v.get('stop_loss'))}' placeholder='(désactivé)'></div>"
        "<div class='field'><label class='flabel' for='take_profit'>Objectif (%)</label>"
        f"<input id='take_profit' name='take_profit' type='number' step='0.1' "
        f"value='{_esc(v.get('take_profit'))}' placeholder='(désactivé)'></div>"
        "<div class='field'><label class='flabel' for='trailing_stop'>Trailing (%)</label>"
        f"<input id='trailing_stop' name='trailing_stop' type='number' step='0.1' "
        f"value='{_esc(v.get('trailing_stop'))}' placeholder='(désactivé)'></div>"
        "<div class='field'><label class='flabel' for='position_sizing'>Sizing</label>"
        "<select id='position_sizing' name='position_sizing'>"
        f"<option value='none'{none_checked}>none (tout-ou-rien)</option>"
        f"<option value='vol'{vol_checked}>vol (cible de volatilité)</option>"
        "</select></div>"
        "<div class='field'><label class='flabel' for='target_vol'>Vol cible (%)</label>"
        f"<input id='target_vol' name='target_vol' type='number' step='1' "
        f"value='{_esc(v.get('target_vol'))}' placeholder='si sizing=vol'></div>"
        "</div>"

        "<button class='btn' type='submit'>Backtester le portefeuille</button>"
        "</form>"
    )


def render_portfolio_form(csrf_token, errors=None, values=None) -> str:
    """Page complete GET /research/portfolio (formulaire vide/prerempli-defaut)."""
    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Formulaire invalide :<ul>{items}</ul></div>"

    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("portfolio")
        + "<div class='head'><h1>Recherche &mdash; Portefeuille</h1>"
        "<a class='navlink' href='/'>&larr; Accueil</a></div>"
        + errors_html
        + "<div class='card'>"
        + _form_html(csrf_token, values)
        + "</div>"
        + "<p class='muted honesty'>Panier équipondéré. La corrélation entre actifs "
          "crypto est généralement élevée (~0.8) : la diversification lisse, "
          "elle ne protège pas d'un krach systémique.</p>"
    )
    return page_shell("Recherche - Portefeuille - InsertYourCoin", "research", body)


def render_portfolio_busy(active_label, active_id, csrf_token) -> str:
    label = active_label or "analyse en cours"
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("portfolio")
        + "<div class='head'><h1>Recherche &mdash; Portefeuille</h1>"
        "<a class='navlink' href='/research/portfolio'>&larr; Formulaire</a></div>"
        f"<div class='busy'>Une analyse est déjà en cours : <strong>{_esc(label)}</strong>. "
        "Attends sa fin (panneau ci-dessous) ou annule-la avant d'en lancer une "
        "nouvelle -- un seul job a la fois.</div>"
        "<div class='card'>"
        + job_panel_html(active_id, csrf_token, result_url=f"/report/{active_id}")
        + "</div>"
    )
    return page_shell("Analyse en cours - InsertYourCoin", "research", body)


def render_portfolio_launched(job_id, csrf_token) -> str:
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("portfolio")
        + "<div class='head'><h1>Recherche &mdash; Portefeuille en cours</h1>"
        "<a class='navlink' href='/research/portfolio'>&larr; Formulaire</a></div>"
        "<div class='card'>"
        + job_panel_html(job_id, csrf_token, result_url=f"/report/{job_id}")
        + "</div>"
    )
    return page_shell("Portefeuille en cours - InsertYourCoin", "research", body)


def _corr_cell_color(v):
    """Heatmap HTML/CSS pure (pas de lib) : rouge si tres correle (>0.7),
    neutre sinon -- meme seuil que main.format_portfolio (avg > 0.7)."""
    if v is None:
        return "#171c24"
    if v >= 0.99:
        return "#232b36"
    if v > 0.7:
        return "rgba(229,83,75,.35)"
    if v > 0.4:
        return "rgba(240,180,41,.25)"
    return "rgba(70,196,111,.20)"


def _correlation_heatmap(corr) -> str:
    """`corr` = pandas.DataFrame carre (symboles x symboles)."""
    symbols = list(corr.columns)
    head = "<th></th>" + "".join(f"<th>{_esc(s)}</th>" for s in symbols)
    rows = []
    for row_sym in symbols:
        cells = [f"<th>{_esc(row_sym)}</th>"]
        for col_sym in symbols:
            v = float(corr.loc[row_sym, col_sym])
            bg = _corr_cell_color(v)
            cls = " class='diag'" if row_sym == col_sym else ""
            cells.append(f"<td{cls} style='background:{bg}'>{v:.2f}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<table class='corr-table'><thead><tr>" + head + "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_portfolio_done(result) -> str:
    """
    Resultat pret (spec §4.7) : KPI agregees + matrice de correlation (heatmap
    HTML/CSS) + note honnete sur la correlation crypto + etat "actif ignore"
    si des symboles n'etaient pas chargeables. `result` = payload de
    research_runners.run_portfolio : {"kind": "portfolio", "result": {...},
    "ignored": [...], "context": {...}} ; `result["result"]` = dict EXACT de
    trading.portfolio.backtest_portfolio.
    """
    res = result["result"]
    ignored = result.get("ignored") or []
    context = result["context"]

    ignored_html = ""
    if ignored:
        items = "".join(
            f"<li>{_esc(i['symbol'])} : {_esc(i['error'])}</li>" for i in ignored
        )
        ignored_html = f"<div class='ignored'>Actif(s) ignoré(s) :<ul>{items}</ul></div>"

    p, b = res["portfolio"], res["portfolio_bh"]
    kpis = [
        ("Rendement portefeuille", fmt.pct(p["total_return"]), fmt.cls(p["total_return"])),
        ("vs Buy & Hold panier", fmt.pct(b["total_return"]), fmt.cls(b["total_return"])),
        ("Sharpe", fmt.num(p["sharpe"]), fmt.cls(p["sharpe"])),
        ("Volatilité", fmt.pct(p["volatility"], signed=False), "neu"),
        ("Drawdown max", fmt.pct(p["max_drawdown"], signed=False), "down"),
        ("Capital final", f"{res['final_equity']:,.2f} $", "neu"),
    ]
    kpi_html = "".join(
        f"<div class='kpi'><div class='kpi-label'>{_esc(lbl)}</div>"
        f"<div class='kpi-value {c}'>{val}</div></div>"
        for lbl, val, c in kpis
    )

    asset_rows = "".join(
        "<tr>"
        f"<td class='nm'>{_esc(sym)}</td>"
        f"<td class='{fmt.cls(m['total_return'])}'>{fmt.pct(m['total_return'])}</td>"
        f"<td class='{fmt.cls(m['sharpe'])}'>{fmt.num(m['sharpe'])}</td>"
        f"<td>{fmt.pct(m['volatility'], signed=False)}</td>"
        f"<td class='down'>{fmt.pct(m['max_drawdown'], signed=False)}</td>"
        "</tr>"
        for sym, m in res["per_asset"].items()
    )
    asset_table = (
        "<table class='asset-table'><thead><tr>"
        "<th>Actif</th><th>Rendement</th><th>Sharpe</th><th>Vol</th><th>DD max</th>"
        "</tr></thead><tbody>" + asset_rows + "</tbody></table>"
    )

    corr = res["correlation"]
    heatmap = _correlation_heatmap(corr)
    vals = corr.values
    n = len(vals)
    avg_corr = float(np.mean([vals[i, j] for i in range(n) for j in range(n) if i < j])) if n > 1 else 0.0
    corr_note = (
        "&rarr; Actifs très corrélés : diversification limitée (tout chute ensemble "
        "en cas de krach). Lisse les bords, ne protège pas du risque systémique crypto."
        if avg_corr > 0.7 else
        "&rarr; Corrélation modérée : la diversification apporte un vrai lissage ici."
    )

    symbols = context.get("symbols") or []
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("portfolio")
        + "<div class='head'><h1>Recherche &mdash; Portefeuille</h1>"
        "<a class='navlink' href='/research/portfolio'>&larr; Nouveau portefeuille</a></div>"
        + f"<p class='muted'>{_esc(', '.join(symbols))} &middot; {_esc(res['strategy'])} "
          f"&middot; {_esc(context.get('timeframe') or '1d')}</p>"
        + ignored_html
        + "<div class='kpi-grid'>" + kpi_html + "</div>"
        + "<div class='card'>" + asset_table + "</div>"
        + "<div class='card'>"
        + "<p class='muted' style='margin:0 0 4px'>Corrélation des rendements (1 = bougent ensemble)</p>"
        + heatmap
        + f"<p class='corr-note'>Corrélation moyenne : {avg_corr:.2f}. {corr_note}</p>"
        + "</div>"
    )
    title = f"Portefeuille - {', '.join(symbols)} - InsertYourCoin"
    return page_shell(title, "research", body)
