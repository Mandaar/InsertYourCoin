"""
Ecran Recherche / Comparer (/research/compare) -- fonctions PURES de rendu et
de parsing (testables sans serveur, sans reseau, cf. docs/UI_UX_WEBAPP_SPEC.md
§4.4). Equivalent web de `python main.py compare` : toutes les strategies sur
le meme jeu, classees, avec la ligne Buy & Hold TOUJOURS visible (garde-fou
anti sur-vente, cf. main.cmd_compare).

Meme patron que trading/research_page.py (Lot 4) : formulaire -> job async
(trading/research_runners.run_compare) -> panneau de progression -> resultat
rendu par render_compare_done (appele depuis trading/report_page.py
render_result_done, generalisation Lot 5).
"""
import html

import config
from . import metrics_format as fmt
from .research_page import parse_market_and_risk_fields, timeframe_options
from .webui import job_panel_html, page_shell, research_subnav_html

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.muted { color: #8b97a6; }
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.cmp-form .row { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 14px; }
.cmp-form .field { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.cmp-form label.flabel { font-size: 12px; color: #9fb0c3; }
.cmp-form input, .cmp-form select { padding: 8px 10px; background: #0e1116;
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
.in-sample-badge { background: #3a2a12; border: 1px solid #f0b429; color: #ffd98a;
  border-radius: 8px; padding: 10px 16px; margin-bottom: 14px; font-size: 13px;
  font-weight: 600; }
table.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px;
  font-family: ui-monospace, Consolas, monospace; }
table.cmp-table th, table.cmp-table td { text-align: right; padding: 8px 10px;
  border-bottom: 1px solid #232b36; }
table.cmp-table th:first-child, table.cmp-table td.nm { text-align: left; }
table.cmp-table th { color: #9fb0c3; font-weight: 500; font-size: 11px;
  text-transform: uppercase; letter-spacing: .05em; }
table.cmp-table td.nm { color: #d6aa5a; }
table.cmp-table tr.bh-row td { color: #9fb0c3; font-style: italic; border-top: 2px solid #232b36; }
.up { color: #46c46f; } .down { color: #e5534b; } .neu { color: #d7dee8; }
.no-edge { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 10px 14px; margin-top: 14px; font-weight: 600; }
"""


def _esc(s):
    return html.escape("" if s is None else str(s))


def parse_compare_params(fields: dict):
    """
    Valide les champs du formulaire POST /research/compare. Retourne
    (params, errors) -- fonction PURE, meme convention que
    research_page.parse_backtest_params, mais SANS `strategy` (toutes les
    strategies sont comparees, cf. spec §4.4).
    """
    return parse_market_and_risk_fields(fields)


def _form_html(csrf_token, values) -> str:
    v = dict(values or {})
    symbol = v.get("symbol") or config.DEFAULT_SYMBOL
    timeframe = v.get("timeframe") or config.DEFAULT_TIMEFRAME
    kraken_checked = " checked" if v.get("source", "kraken") != "binance" else ""
    binance_checked = " checked" if v.get("source") == "binance" else ""
    vol_checked = " selected" if v.get("position_sizing") == "vol" else ""
    none_checked = " selected" if v.get("position_sizing", "none") != "vol" else ""
    token = _esc(csrf_token)

    return (
        "<form class='cmp-form' method='post' action='/research/compare'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<div class='row'>"
        "<div class='field'><label class='flabel' for='symbol'>Symbole</label>"
        f"<input id='symbol' name='symbol' value='{_esc(symbol)}'></div>"
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

        "<button class='btn' type='submit'>Comparer les stratégies</button>"
        "</form>"
    )


def render_compare_form(csrf_token, errors=None, values=None) -> str:
    """Page complete GET /research/compare (formulaire vide/prerempli-defaut)."""
    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Formulaire invalide :<ul>{items}</ul></div>"

    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("compare")
        + "<div class='head'><h1>Recherche &mdash; Comparer</h1>"
        "<a class='navlink' href='/'>&larr; Accueil</a></div>"
        + errors_html
        + "<div class='card'>"
        + _form_html(csrf_token, values)
        + "</div>"
        + "<p class='muted honesty'>Comparaison IN-SAMPLE (sur les données vues) -- "
          "ce n'est pas une preuve d'edge futur. La ligne Buy &amp; Hold est toujours "
          "affichée comme référence honnête.</p>"
    )
    return page_shell("Recherche - Comparer - InsertYourCoin", "research", body)


def render_compare_busy(active_label, active_id, csrf_token) -> str:
    """Meme convention que research_page.render_backtest_busy (Lot 4) : un
    seul job a la fois, jamais de 2e job silencieux."""
    label = active_label or "analyse en cours"
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("compare")
        + "<div class='head'><h1>Recherche &mdash; Comparer</h1>"
        "<a class='navlink' href='/research/compare'>&larr; Formulaire</a></div>"
        f"<div class='busy'>Une analyse est déjà en cours : <strong>{_esc(label)}</strong>. "
        "Attends sa fin (panneau ci-dessous) ou annule-la avant d'en lancer une "
        "nouvelle -- un seul job a la fois.</div>"
        "<div class='card'>"
        + job_panel_html(active_id, csrf_token, result_url=f"/report/{active_id}")
        + "</div>"
    )
    return page_shell("Analyse en cours - InsertYourCoin", "research", body)


def render_compare_launched(job_id, csrf_token) -> str:
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("compare")
        + "<div class='head'><h1>Recherche &mdash; Comparaison en cours</h1>"
        "<a class='navlink' href='/research/compare'>&larr; Formulaire</a></div>"
        "<div class='card'>"
        + job_panel_html(job_id, csrf_token, result_url=f"/report/{job_id}")
        + "</div>"
    )
    return page_shell("Comparaison en cours - InsertYourCoin", "research", body)


def render_compare_done(result) -> str:
    """
    Resultat pret (spec §4.4) : tableau trie toutes strategies + ligne
    Buy & Hold TOUJOURS visible + mise en evidence honnete si aucune
    strategie ne bat Buy & Hold. `result` = payload de
    research_runners.run_compare : {"kind": "compare", "rows": [...],
    "buy_hold": float, "context": {...}}.
    """
    rows = sorted(result["rows"], key=lambda r: r["metrics"]["total_return"], reverse=True)
    buy_hold = result["buy_hold"]
    context = result["context"]

    trs = []
    for r in rows:
        m = r["metrics"]
        trs.append(
            "<tr>"
            f"<td class='nm'>{_esc(r['name'])}</td>"
            f"<td class='{fmt.cls(m['total_return'])}'>{fmt.pct(m['total_return'])}</td>"
            f"<td class='{fmt.cls(m['sharpe'])}'>{fmt.num(m['sharpe'])}</td>"
            f"<td class='down'>{fmt.pct(m['max_drawdown'], signed=False)}</td>"
            f"<td>{fmt.pf(m['profit_factor'])}</td>"
            f"<td>{m['n_trades']}</td>"
            f"<td>{fmt.pct(m['win_rate'], signed=False)}</td>"
            "</tr>"
        )
    trs.append(
        "<tr class='bh-row'>"
        f"<td class='nm'>Buy &amp; Hold (référence)</td>"
        f"<td class='{fmt.cls(buy_hold)}'>{fmt.pct(buy_hold)}</td>"
        "<td>&mdash;</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td>"
        "</tr>"
    )
    table = (
        "<table class='cmp-table'><thead><tr>"
        "<th>Stratégie</th><th>Rendement</th><th>Sharpe</th><th>DD max</th>"
        "<th>PF</th><th>Trades</th><th>Réussite</th>"
        "</tr></thead><tbody>" + "".join(trs) + "</tbody></table>"
    )

    none_beats_bh = all(r["metrics"]["total_return"] <= buy_hold for r in rows)
    honesty = (
        "<div class='no-edge'>0 stratégie ne bat Buy &amp; Hold sur cette période -- "
        "l'edge n'est pas demontre ici.</div>"
        if none_beats_bh else ""
    )

    symbol = context.get("symbol") or "?"
    timeframe = context.get("timeframe") or "1d"
    body = (
        f"<style>{_CSS}</style>"
        + research_subnav_html("compare")
        + "<div class='head'><h1>Recherche &mdash; Comparer</h1>"
        "<a class='navlink' href='/research/compare'>&larr; Nouvelle comparaison</a></div>"
        + "<div class='in-sample-badge'>IN-SAMPLE &mdash; de bons chiffres passés "
          "ne garantissent jamais le futur.</div>"
        + f"<p class='muted'>{_esc(symbol)} ({_esc(timeframe)})</p>"
        + "<div class='card'>" + table + "</div>"
        + honesty
    )
    title = f"Comparer - {symbol} - InsertYourCoin"
    return page_shell(title, "research", body)
