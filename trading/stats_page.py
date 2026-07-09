"""
Ecran Labo de stats (/stats) -- fonctions PURES de rendu (testables sans
serveur, sans reseau, sans lecture fichier). Equivalent web de la commande
`python main.py stats` (trading/stats.py : load_stats / summarize / format_summary,
reutilises TELS QUELS -- aucune logique de calcul reecrite ici, spec §4.11).

Lecture seule : aucun formulaire de mutation, pas de jeton CSRF necessaire.
Le SELECTEUR de fichier ne transporte jamais un chemin : uniquement un NOM DE
FICHIER present dans une liste blanche calculee cote serveur (trading/monitor.py
resolve_stats_path) -- cette page se contente d'afficher les noms proposes par
l'appelant, elle ne resout ni ne lit rien elle-meme.
"""
import html

from .stats import HONESTY_NOTE, WEEKDAY_NAMES
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
.empty { text-align: center; padding: 40px 16px; }
.filepick { display: flex; gap: 8px; align-items: center; margin-bottom: 14px;
  font-size: 13px; color: #9fb0c3; flex-wrap: wrap; }
.filepick select { background: #0e1116; color: #d7dee8; border: 1px solid #2a333f;
  border-radius: 6px; padding: 6px 8px; font-family: ui-monospace, Consolas, monospace; }
.filepick button { background: #1f6feb; color: #fff; border: none; border-radius: 6px;
  padding: 6px 12px; cursor: pointer; font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px; margin-bottom: 14px; }
.card.stat { margin-bottom: 0; }
.card .label { font-size: 11px; color: #7f8c9c; text-transform: uppercase;
  letter-spacing: .5px; margin-bottom: 6px; }
.card .value { font-size: 20px; font-weight: 600; }
.card.pos .value { color: #46c46f; }
.card.neg .value { color: #e5534b; }
.card.fees { border-color: #f0b429; }
.card.fees .value { color: #f0b429; }
.card.fees .label { color: #ffd98a; }
.bars { display: flex; flex-direction: column; gap: 6px; }
.barrow { display: grid; grid-template-columns: 70px 1fr 90px; align-items: center;
  gap: 8px; font-size: 12px; }
.barlabel { color: #9fb0c3; }
.bartrack { background: #0e1116; border: 1px solid #232b36; border-radius: 5px;
  height: 12px; overflow: hidden; }
.barfill { display: block; height: 100%; background: #d6aa5a; }
.barval { color: #6b7787; text-align: right; font-family: ui-monospace, Consolas, monospace; }
.honesty { font-size: 12px; color: #9fb0c3; line-height: 1.6; white-space: pre-wrap; }
"""


def _esc(s):
    return html.escape("" if s is None else str(s))


def _fmt_pct(value, decimals=2, signed=False):
    sign = "+" if signed else ""
    return f"{value*100:{sign}.{decimals}f}%"


def _stat_card(label, value, cls=""):
    css = f"card stat {cls}".strip()
    return (
        f"<div class='{css}'><div class='label'>{_esc(label)}</div>"
        f"<div class='value'>{value}</div></div>"
    )


def _hour_label(key):
    try:
        return f"{int(key):02d}h"
    except (TypeError, ValueError):
        return str(key)


def _weekday_label(key):
    try:
        wd = int(key)
    except (TypeError, ValueError):
        return str(key)
    return WEEKDAY_NAMES[wd] if 0 <= wd < 7 else str(key)


def _bars_card(title, counts: dict, label_fn) -> str:
    """Mini-barres HTML/CSS (pas de lib JS) : largeur proportionnelle au nombre
    de cycles, valeur "cycles / trades" affichee a droite."""
    if not counts:
        return ""
    max_cycles = max((c.get("cycles", 0) for c in counts.values()), default=0) or 1
    rows = []
    for key in sorted(counts, key=lambda x: int(x)):
        c = counts[key]
        cycles = c.get("cycles", 0)
        trades = c.get("trades", 0)
        pct = round(100 * cycles / max_cycles)
        rows.append(
            "<div class='barrow'>"
            f"<span class='barlabel'>{_esc(label_fn(key))}</span>"
            "<span class='bartrack'>"
            f"<span class='barfill' style='width:{pct}%'></span></span>"
            f"<span class='barval'>{cycles} / {trades}</span>"
            "</div>"
        )
    return (
        f"<div class='card'><h2>{_esc(title)}</h2>"
        "<div class='bars'>" + "".join(rows) + "</div></div>"
    )


def _honesty_card() -> str:
    # Repris MOT POUR MOT de trading.stats.HONESTY_NOTE (source unique partagee
    # avec le rendu CLI format_summary -- aucune copie divergente possible).
    return (
        "<div class='card'><h2>Honnetete</h2>"
        f"<p class='honesty'>{_esc(HONESTY_NOTE)}</p></div>"
    )


def _file_picker_html(current_file, available_files) -> str:
    """Formulaire GET de selection du CSV -- ne transporte que des NOMS DE
    FICHIER deja whitelistes cote serveur (trading/monitor.py). Si un seul
    fichier est disponible (cas courant), pas de selecteur : juste le nom."""
    if not available_files:
        return ""
    if len(available_files) == 1 and available_files[0] == current_file:
        return f"<div class='filepick'>Source : <code>{_esc(current_file)}</code></div>"
    options = "".join(
        f"<option value='{_esc(f)}'{' selected' if f == current_file else ''}>{_esc(f)}</option>"
        for f in available_files
    )
    return (
        "<form class='filepick' method='get' action='/stats'>"
        f"Source : <select name='file'>{options}</select>"
        "<button type='submit'>Charger</button>"
        "</form>"
    )


def render_stats_page(current_file, available_files, summary, empty_message=None) -> str:
    """
    Page complete /stats (fonction PURE, aucune I/O). `current_file` = nom du CSV
    effectivement charge (deja resolu/whitelist cote serveur) ; `available_files`
    = liste de noms proposes au selecteur (whitelist calculee cote serveur) ;
    `summary` = dict de trading.stats.summarize(...) ou None (etat vide) ;
    `empty_message` = message EXACT leve par trading.stats.load_stats (etat vide
    pedagogique, jamais une erreur brute).
    """
    picker = _file_picker_html(current_file, available_files)

    if summary is None:
        msg = empty_message or (
            "Aucune donnee de stats. Lance d'abord du paper trading pour "
            "accumuler des cycles."
        )
        body = (
            f"<style>{_CSS}</style>"
            "<div class='head'><h1>Labo de stats</h1>"
            "<a class='navlink' href='/monitoring'>&larr; Monitoring</a></div>"
            + picker
            + "<div class='card empty'><h2>Aucune donnee</h2>"
            f"<p class='muted'>{_esc(msg)}</p></div>"
            + _honesty_card()
        )
        return page_shell("Labo de stats - InsertYourCoin", "stats", body)

    ret_cls = "pos" if summary["total_return"] >= 0 else "neg"
    pnl_cls = "pos" if summary["pnl_total"] >= 0 else "neg"

    cards = (
        "<div class='cards'>"
        + _stat_card("Cycles", _esc(summary["n_cycles"]))
        + _stat_card("Rendement", _fmt_pct(summary["total_return"], signed=True), ret_cls)
        + _stat_card("Drawdown max", _fmt_pct(summary["max_drawdown"]))
        + _stat_card("Trades", f"{summary['n_trades']} "
                                f"({summary['n_buy']} achats / {summary['n_sell']} ventes)")
        + _stat_card("Reussite", _fmt_pct(summary["win_rate"], decimals=0))
        + _stat_card("PnL total", f"{summary['pnl_total']:+.2f}", pnl_cls)
        # Part des frais MISE EN EVIDENCE (spec §4.11 -- sur timeframe court,
        # les frais Kraken pesent lourd, deja rappele dans l'encart d'honnetete).
        + _stat_card(
            "Frais (part du |pnl|+frais)",
            f"{summary['fees_total']:.2f}  (~{_fmt_pct(summary['fees_share'], decimals=0)})",
            "fees",
        )
        + _stat_card("Exposition moy.", _fmt_pct(summary["avg_exposure"], decimals=0))
        + "</div>"
    )

    periode = (
        "<p class='muted'>Periode : "
        f"{_esc(summary['time_min'])} &rarr; {_esc(summary['time_max'])}</p>"
    )

    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Labo de stats</h1>"
        "<a class='navlink' href='/monitoring'>&larr; Monitoring</a></div>"
        + picker
        + periode
        + cards
        + _bars_card("Par heure (cycles / trades)", summary["by_hour"], _hour_label)
        + _bars_card("Par jour (cycles / trades)", summary["by_weekday"], _weekday_label)
        + _honesty_card()
    )
    return page_shell("Labo de stats - InsertYourCoin", "stats", body)
