"""
Serveur de monitoring web LEGER pour visualiser le paper trading EN DIRECT.

STDLIB UNIQUEMENT (http.server) : zero nouvelle dependance (install propre,
anti-virus proof). Le serveur LIT seulement des fichiers (paper_stats.csv,
paper_trades.log, paper_state.json) -- il ne touche JAMAIS au trading.

Conception :
- des fonctions PURES (lecture fichiers, assemblage de la vue, rendu HTML)
  testables sans serveur ni reseau ;
- un petit serveur ThreadingHTTPServer qui relit les fichiers a CHAQUE requete
  (donnees fraiches) et sert (Lot 1, bascule de route decidee §11.1) :
    GET /            -> Accueil (hub d'etat, trading/home_page.py)
    GET /check       -> Diagnostic (trading/check_page.py), ?run=1 = execute
                         le VRAI test de connexion Kraken (sinon aucun reseau)
    GET /monitoring  -> page complete monitoring (coquille + fragment initial
                         + script JS) -- ANCIEN "/"
    GET /fragment    -> fragment HTML seul (refresh partiel JS, sans rechargement)
    GET /stats       -> Labo de stats (trading/stats_page.py), lecture seule ;
                         ?file=<nom> restreint a une liste blanche *_stats.csv
                         (trading/monitor.py resolve_stats_path, jamais un
                         chemin arbitraire fourni par le client)
    GET/POST /research/backtest, /research/compare, /research/optimize,
                     /research/portfolio, /research/walkforward -> ecrans de
                         recherche (Lots 4-6, formulaire pur -> job async ->
                         /report/<job_id> ; walkforward = LE JUGE, Lot 6)
    GET /report/<job_id> -> resultat d'un job de recherche, generalise par
                         `kind` (Lot 5, etendu Lot 6, cf. trading/report_page.py
                         render_result_done)
    GET/POST /paper  -> ecran Paper (Lot 7, trading/paper_page.py) : configure
                         + demarre/arrete le paper trading DEPUIS l'UI (process
                         detache, PID suivi dans run/paper.pid, meme garde-fou
                         paper-only que lancer.py -- assert_paper_only).
  Le script JS cote client fait un fetch('/fragment') toutes les 7s et injecte
  le resultat dans <div id="content"> -- jamais de rechargement de page entiere.
"""
import csv
import datetime as dt
import html
import http.server
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import config
import lancer
from .options import (
    read_options, write_options, update_env_file, keys_configured, LOG_LEVELS,
)
from .webui import page_shell, serve_static
from .home_page import render_home_page
from .check_page import render_check_page
from .help_page import render_help_page
from .stats import load_stats, summarize
from .stats_page import render_stats_page
from .diagnostics_web import run_web_check, static_diagnostic_lines, truststore_active
from .jobs import JobBusy, JobManager
from . import compare_page
from . import live_control
from . import live_page
from . import optimize_page
from . import paper_page
from . import portfolio_page
from . import research_page
from . import report_page
from . import walkforward_page
from .research_runners import (
    run_backtest, run_compare, run_optimize, run_portfolio, run_walkforward,
)


def project_root() -> Path:
    """Racine du projet = dossier PARENT de trading/. Resolu en absolu pour etre
    robuste au repertoire de lancement (les chemins par defaut en dependent)."""
    return Path(__file__).resolve().parent.parent


def read_state(path) -> dict | None:
    """Parse paper_state.json. None si absent/illisible (jamais d'exception)."""
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def read_last_stats(path) -> dict | None:
    """
    Lit le CSV de stats. Retourne {"row": <derniere ligne, dict colonne->valeur>,
    "n": <nb lignes de donnees>, "first_time": ..., "last_time": ...} ou None si
    absent/vide. Gere le cas du fichier en cours d'ecriture : si la derniere ligne
    est partielle (champs manquants), on prend l'avant-derniere ligne complete.
    """
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return None
        with p.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return None

        # Une ligne est "complete" si aucun champ n'est manquant (None = colonnes
        # en trop par rapport a l'entete -> ligne tronquee en cours d'ecriture).
        def _complete(r):
            return None not in r.values()

        last = None
        for r in reversed(rows):
            if _complete(r):
                last = r
                break
        if last is None:
            last = rows[-1]  # rien de complet : on prend quand meme la derniere

        first_time = rows[0].get("time")
        last_time = last.get("time")
        return {"row": last, "n": len(rows),
                "first_time": first_time, "last_time": last_time}
    except Exception:
        return None


def tail_log(path, n=40) -> list:
    """n dernieres lignes du log (sans \\n), [] si absent/illisible."""
    try:
        p = Path(path)
        if not p.exists():
            return []
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        return lines[-n:] if n else lines
    except Exception:
        return []


def list_stats_csvs(directory) -> list:
    """
    Liste blanche des CSV de stats SELECTIONNABLES depuis l'ecran /stats :
    fichiers `*_stats.csv` presents DIRECTEMENT dans `directory` (pas de
    sous-dossier). Ne leve jamais (dossier absent/illisible -> liste vide).
    """
    try:
        d = Path(directory)
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.glob("*_stats.csv") if p.is_file())
    except OSError:
        return []


def resolve_stats_path(directory, requested, default_path) -> Path:
    """
    Resout le CSV de stats demande par le client de facon SURE : `requested`
    (parametre `?file=` fourni par le NAVIGATEUR, donc non fiable) n'est accepte
    que s'il est un NOM DE FICHIER NU (aucun separateur de chemin, aucun '..')
    ET present dans la liste blanche `list_stats_csvs(directory)`. Dans tout
    autre cas (absent, chemin, traversal, fichier hors liste) -> `default_path`.
    Cette fonction ne lit JAMAIS le fichier : elle ne fait que choisir un chemin.
    """
    if not requested:
        return default_path
    name = requested.strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return default_path
    if name not in list_stats_csvs(directory):
        return default_path
    return Path(directory) / name


def _to_float(value):
    """Conversion souple en float, None si impossible (champ vide/texte)."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(s):
    """Parse un horodatage 'YYYY-MM-DD HH:MM:SS', None si non parseable."""
    if not s:
        return None
    try:
        return dt.datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def compute_view(state, stats, log_lines, initial_capital, now_str) -> dict:
    """
    Assemble les metriques d'affichage a partir des donnees lues. Fonction PURE.
    `state` / `stats` peuvent etre None (paper pas encore demarre). `now_str` est
    l'heure courante (chaine), injectee pour rester testable.
    """
    row = (stats or {}).get("row") or {}

    price = _to_float(row.get("price"))
    equity = _to_float(row.get("equity"))
    exposure = _to_float(row.get("exposure"))
    drawdown = _to_float(row.get("drawdown"))

    invested = bool(state.get("invested")) if isinstance(state, dict) else None
    # Statut prioritaire depuis l'etat ; sinon deduit de la ligne de stats.
    if invested is None and row:
        invested = (exposure is not None and exposure > 0)
    statut = "INVESTI" if invested else "CASH"

    pnl_total = (equity - initial_capital) if equity is not None else None
    pnl_pct = (pnl_total / initial_capital) if (pnl_total is not None and initial_capital) else None

    n_cycles = (stats or {}).get("n", 0)
    last_time = (stats or {}).get("last_time")

    # Age depuis le dernier cycle : ecart now -> last_time si parseables.
    age_seconds = None
    t_last = _parse_time(last_time)
    t_now = _parse_time(now_str)
    if t_last is not None and t_now is not None:
        age_seconds = (t_now - t_last).total_seconds()

    inactif = (age_seconds is not None and age_seconds > 360)

    trades = []
    if isinstance(state, dict) and isinstance(state.get("trades"), list):
        trades = state["trades"][-8:]  # max 8, les plus recents

    return {
        "now": now_str,
        "statut": statut,
        "invested": bool(invested),
        "price": price,
        "equity": equity,
        "initial_capital": initial_capital,
        "pnl_total": pnl_total,
        "pnl_pct": pnl_pct,
        "drawdown": drawdown,
        "exposure": exposure,
        "n_cycles": n_cycles,
        "last_time": last_time,
        "age_seconds": age_seconds,
        "inactif": inactif,
        "trades": trades,
        "log_lines": list(log_lines or []),
        "has_data": bool(row) or bool(state) or bool(log_lines),
    }


# --------------------------------------------------------------------------- #
#  Rendu HTML (autonome, theme sombre, auto-refresh)                          #
# --------------------------------------------------------------------------- #
_ERROR_MARKERS = ("erreur", "echec", "error")


def _fmt_num(value, suffix="", decimals=2):
    """Formate un nombre, '-' si None."""
    if value is None:
        return "-"
    return f"{value:,.{decimals}f}{suffix}"


def _fmt_pct(value, decimals=2, signed=False):
    """Formate une fraction en pourcentage, '-' si None."""
    if value is None:
        return "-"
    sign = "+" if signed else ""
    return f"{value*100:{sign}.{decimals}f}%"


def _esc(s):
    return html.escape("" if s is None else str(s))


def _error_page(title, message) -> str:
    """
    Page d'erreur HTTP habillee (theme commun `page_shell`) -- remplace les
    `<h1>...</h1>` bruts servis sans doctype/charset/nav/theme (P3-4, audit
    §5) par une rupture visuelle coherente avec le reste de l'app. `title`
    reste bref ("404", "403 - Host non autorise"...), `message` explique
    l'erreur en une phrase (jamais de donnee sensible : appelants ne passent
    que du texte deja assaini, ex. `str(exc)` sans trace)."""
    body = (
        "<div class='head'><h1>" + _esc(title) + "</h1></div>"
        "<div class='card'><p>" + _esc(message) + "</p>"
        "<p><a class='navlink' href='/' style='color:#6cb6ff'>&larr; Accueil</a></p></div>"
    )
    return page_shell(title + " - InsertYourCoin", "", body)


def _trades_html(trades):
    if not trades:
        return "<p class='muted'>Aucun ordre pour l'instant.</p>"
    rows = []
    for t in trades:
        side = str(t.get("side", "")).upper()
        cls = "buy" if side == "BUY" else "sell"
        price = _to_float(t.get("price"))
        reason = t.get("reason")
        rows.append(
            "<tr>"
            f"<td>{_esc(t.get('time'))}</td>"
            f"<td class='{cls}'>{_esc(side)}</td>"
            f"<td class='right'>{_fmt_num(price)}</td>"
            f"<td>{_esc(reason) if reason else ''}</td>"
            "</tr>"
        )
    return (
        "<table class='trades'><thead><tr>"
        "<th>Heure</th><th>Sens</th><th class='right'>Prix</th><th>Motif</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _log_html(log_lines):
    if not log_lines:
        return "<p class='muted'>Aucune ligne de log.</p>"
    out = []
    for line in log_lines:
        low = line.lower()
        cls = " class='logerr'" if any(m in low for m in _ERROR_MARKERS) else ""
        out.append(f"<div{cls}>{_esc(line)}</div>")
    return "<div class='log'>" + "".join(out) + "</div>"


def render_fragment(view) -> str:
    """
    Fragment HTML du CONTENU (ce qui change a chaque cycle). Retourne uniquement
    le corps de la page (sans <html>/<head>/<body>), injecte dans <div id='content'>
    par le script JS. Inclut l'horodatage de derniere mise a jour.
    """
    now = _esc(view.get("now"))
    horodatage = (
        f"<span class='maj'>Dernière maj : {now} (auto-refresh 7s)</span>"
    )

    if not view.get("has_data"):
        return (
            horodatage
            + "<div class='card empty'>"
            "<h2>En attente de données du paper...</h2>"
            "<p class='muted'>Lance le paper trading pour voir apparaître "
            "les cycles, les ordres et le portefeuille ici.</p>"
            "</div>"
        )

    pnl = view.get("pnl_total")
    pnl_cls = "pos" if (pnl is not None and pnl >= 0) else "neg"
    statut_cls = "invested" if view.get("invested") else "cash"

    inactif_html = ""
    if view.get("inactif"):
        age = view.get("age_seconds")
        age_txt = f"{int(age)}" if age is not None else "?"
        inactif_html = (
            "<div class='alert'>ATTENTION : aucun cycle depuis "
            f"{age_txt}s (paper inactif ?)</div>"
        )

    bandeau = (
        "<div class='cards'>"
        f"<div class='card stat {statut_cls}'><div class='label'>Statut</div>"
        f"<div class='value'>{_esc(view['statut'])}</div></div>"
        f"<div class='card stat'><div class='label'>Prix</div>"
        f"<div class='value'>{_fmt_num(view.get('price'))}</div></div>"
        f"<div class='card stat'><div class='label'>Equity</div>"
        f"<div class='value'>{_fmt_num(view.get('equity'))}</div></div>"
        f"<div class='card stat {pnl_cls}'><div class='label'>P&amp;L</div>"
        f"<div class='value'>{_fmt_num(view.get('pnl_total'), decimals=2)} "
        f"({_fmt_pct(view.get('pnl_pct'), signed=True)})</div></div>"
        f"<div class='card stat'><div class='label'>Drawdown</div>"
        f"<div class='value'>{_fmt_pct(view.get('drawdown'))}</div></div>"
        f"<div class='card stat'><div class='label'>Exposition</div>"
        f"<div class='value'>{_fmt_pct(view.get('exposure'), decimals=0)}</div></div>"
        f"<div class='card stat'><div class='label'>Cycles</div>"
        f"<div class='value'>{_esc(view.get('n_cycles'))}</div></div>"
        "</div>"
    )

    return (
        horodatage
        + inactif_html
        + bandeau
        + "<div class='card'><h2>Derniers ordres</h2>"
        + _trades_html(view.get("trades"))
        + "</div>"
        + "<div class='card'><h2>Journal</h2>"
        + _log_html(view.get("log_lines"))
        + "</div>"
    )


def build_html(view) -> str:
    """
    Page HTML COMPLETE et autonome (CSS inline, theme sombre).
    La page est chargee UNE SEULE FOIS ; le contenu est ensuite mis a jour via
    fetch('/fragment') toutes les 7s (script JS injecte). Pas de meta refresh.
    """
    return _page(render_fragment(view))


_CSS = """
.iyc-page { padding: 16px; }
h1 { font-size: 18px; margin: 0 0 4px; }
h2 { font-size: 14px; margin: 0 0 10px; color: #9fb0c3; text-transform: uppercase;
  letter-spacing: .5px; }
.muted { color: #8b97a6; }
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
.head .maj { color: #8b97a6; font-size: 12px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px; margin-bottom: 14px; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.card.stat { margin-bottom: 0; }
.card .label { font-size: 11px; color: #7f8c9c; text-transform: uppercase;
  letter-spacing: .5px; margin-bottom: 6px; }
.card .value { font-size: 20px; font-weight: 600; }
.card.pos .value { color: #46c46f; }
.card.neg .value { color: #e5534b; }
.card.invested .value { color: #f0b429; }
.card.cash .value { color: #6cb6ff; }
.alert { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-weight: 600; }
.empty { text-align: center; padding: 40px 16px; }
table.trades { width: 100%; border-collapse: collapse; font-size: 13px; }
table.trades th, table.trades td { text-align: left; padding: 6px 10px;
  border-bottom: 1px solid #232b36; }
table.trades th { color: #7f8c9c; font-weight: 500; }
table.trades td.right, table.trades th.right { text-align: right; }
.buy { color: #46c46f; font-weight: 600; }
.sell { color: #e5534b; font-weight: 600; }
.log { font-family: ui-monospace, Consolas, Menlo, monospace; font-size: 12px;
  line-height: 1.5; max-height: 320px; overflow-y: auto; white-space: pre-wrap;
  word-break: break-word; }
.log .logerr { color: #ff7b72; }
"""


_JS_REFRESH = """
<script>
async function refresh(){
  try{
    var r=await fetch('/fragment',{cache:'no-store'});
    if(r.ok){document.getElementById('content').innerHTML=await r.text();}
  }catch(e){}
}
setInterval(refresh,7000);
</script>
"""


def _page(fragment):
    """
    Contenu de la page de monitoring, injecte dans la coquille commune
    `page_shell` (nav + theme partages, cf. trading/webui.py). `fragment` est
    le contenu initial produit par render_fragment(view), place dans
    <div id='content'>. Le script JS met a jour ce div toutes les 7s via
    fetch('/fragment'). AUCUN meta http-equiv='refresh' -- la page ne se
    recharge jamais.
    """
    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Paper trading - monitoring</h1>"
        "<a class='navlink' href='/options'>Options</a></div>"
        f"<div id='content'>{fragment}</div>"
        + _JS_REFRESH
    )
    return page_shell("Paper trading - monitoring", "monitoring", body)


# --------------------------------------------------------------------------- #
#  Page Options (niveau de logs, liaison Kraken, lien wallet)                 #
#                                                                             #
#  SECURITE : aucune VALEUR de cle n'apparait jamais dans le HTML, ni dans un #
#  log, ni dans une reponse. Un token anti-CSRF est exige au POST. L'en-tete  #
#  Host est verifie cote serveur (anti DNS-rebinding).                        #
# --------------------------------------------------------------------------- #
_WITHDRAW_URL = "https://www.kraken.com/u/funding/withdraw"

_OPTIONS_CSS = _CSS + """
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
form.opt { margin: 0; }
.radio-row { display: flex; gap: 18px; flex-wrap: wrap; margin: 6px 0 4px; }
.radio-row label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.field { margin: 12px 0; }
.field label.flabel { display: block; font-size: 12px; color: #9fb0c3;
  margin-bottom: 4px; }
.field input[type=password] { width: 100%; max-width: 460px; padding: 8px 10px;
  background: #0e1116; color: #d7dee8; border: 1px solid #2a333f; border-radius: 6px;
  font-family: ui-monospace, Consolas, monospace; }
.check-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; }
.btn { background: #1f6feb; color: #fff; border: none; border-radius: 7px;
  padding: 10px 18px; font-size: 14px; cursor: pointer; }
.btn:hover { background: #2a7bff; }
.btn-stop { background: #3a1d12; color: #ffb4ad; border: 1px solid #e5534b;
  border-radius: 7px; padding: 9px 18px; font-size: 14px; cursor: pointer; }
.btn-stop:hover { background: #4a2417; }
.server-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.help { font-size: 12px; color: #7f8c9c; margin: 6px 0; line-height: 1.5; }
.ok { color: #46c46f; font-weight: 600; }
.no { color: #e5534b; font-weight: 600; }
.saved { background: #12331d; border: 1px solid #46c46f; color: #9ff0b8;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-weight: 600; }
.warn { color: #f0b429; }
a.wallet { color: #6cb6ff; }
"""


def render_options_page(log_level, keys_ok, csrf_token, saved=False) -> str:
    """
    Page HTML COMPLETE de la page Options (fonction PURE, testable sans serveur).
    NE CONTIENT JAMAIS la valeur d'une cle, meme si configuree : seul l'etat
    booleen `keys_ok` est affiche. `csrf_token` est injecte en champ cache du form.
    """
    if log_level not in LOG_LEVELS:
        log_level = "moyen"

    saved_html = (
        "<div class='saved'>Modifications enregistrées.</div>" if saved else ""
    )

    # Boutons radio niveau de logs (l'actif est coche).
    radios = []
    labels = {"leger": "Léger (évènements seuls)",
              "moyen": "Moyen (défaut : + statut par cycle)",
              "complet": "Complet (+ détail par cycle)"}
    for lvl in LOG_LEVELS:
        checked = " checked" if lvl == log_level else ""
        radios.append(
            f"<label><input type='radio' name='log_level' value='{lvl}'{checked}> "
            f"{_esc(labels.get(lvl, lvl))}</label>"
        )
    radio_html = "<div class='radio-row'>" + "".join(radios) + "</div>"

    etat_cles = (
        "<span class='ok'>OUI</span>" if keys_ok else "<span class='no'>NON</span>"
    )

    token = _esc(csrf_token)

    body = (
        "<div class='head'><h1>Options</h1>"
        "<a class='navlink' href='/monitoring'>&larr; Retour au monitoring</a></div>"
        + saved_html
        + "<form class='opt' method='post' action='/options'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"

        # (a) Niveau de logs
        "<div class='card'><h2>Niveau de logs du paper</h2>"
        + radio_html
        + "<p class='help'>Appliqué à chaud (le paper relit ce réglage à chaque "
          "cycle). Les ACHAT/VENTE et les erreurs sont toujours journalisées.</p>"
        "</div>"

        # (b) Liaison Kraken
        "<div class='card'><h2>Liaison Kraken</h2>"
        f"<p>Clés configurées : {etat_cles}</p>"
        "<div class='field'><label class='flabel' for='api_key'>Clé API "
        "(publique)</label>"
        "<input type='password' id='api_key' name='api_key' autocomplete='off' "
        "placeholder='(laisser vide pour ne pas changer)'></div>"
        "<div class='field'><label class='flabel' for='api_secret'>Clé privée "
        "(secret)</label>"
        "<input type='password' id='api_secret' name='api_secret' "
        "autocomplete='off' placeholder='(laisser vide pour ne pas changer)'></div>"
        "<div class='check-row'><input type='checkbox' id='persist' "
        "name='persist' value='1'>"
        "<label for='persist'>Enregistrer dans .env (sinon : session seulement, "
        "rien n'est écrit sur disque)</label></div>"
        "<p class='help'>Crée ta clé sur Kraken avec UNIQUEMENT "
        "<strong>Query Funds</strong> + <strong>Create &amp; Modify Orders</strong>. "
        "<span class='warn'>JAMAIS</span> <strong>Withdraw Funds</strong> : cette "
        "application n'a aucun besoin de retirer des fonds.</p>"
        "<button class='btn' type='submit'>Enregistrer</button>"
        "</div>"
        "</form>"

        # (c) Wallet
        "<div class='card'><h2>Wallet</h2>"
        f"<p><a class='wallet' href='{_WITHDRAW_URL}' target='_blank' "
        "rel='noopener'>Transférer vers mon wallet (page officielle Kraken)</a></p>"
        "<p class='help'>Le retrait se fait sur Kraken avec ton 2FA. Conseil : "
        "active la <strong>whitelist d'adresses</strong> de retrait. "
        "CETTE APP NE FAIT JAMAIS DE RETRAIT ET N'ENREGISTRE RIEN CÔTÉ WALLET.</p>"
        "</div>"

        # (d) Serveur web (arret / redemarrage) -- controle UNIQUEMENT ce
        # serveur, jamais le paper trading (process separe).
        "<div class='card'><h2>Serveur web</h2>"
        "<p class='help'>Contrôle uniquement CE serveur (le tableau de bord). "
        "Le <strong>paper trading n'est pas affecté</strong> : il continue de "
        "tourner et d'écrire ses données, avec ou sans ce serveur.</p>"
        "<div class='server-actions'>"
        "<form method='post' action='/server/restart'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<button class='btn' type='submit'>Redémarrer le serveur</button>"
        "</form>"
        "<form method='post' action='/server/stop' "
        "onsubmit='return confirm(\"Arrêter le serveur web ? Le paper trading "
        "continue de tourner en arrière-plan. Relance ensuite via le "
        "raccourci bureau.\");'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<button class='btn-stop' type='submit'>Arrêter le serveur</button>"
        "</form>"
        "</div>"
        "</div>"
    )

    return page_shell("Options - monitoring", "options",
                      f"<style>{_OPTIONS_CSS}</style>" + body, csrf=csrf_token)


# --------------------------------------------------------------------------- #
#  Arret / redemarrage du SERVEUR WEB (Options) -- controle UNIQUEMENT ce      #
#  serveur (le tableau de bord). Le paper trading est un process SEPARE,      #
#  lance et suivi par lancer.py (run/paper.pid) : il n'est JAMAIS touche ici. #
# --------------------------------------------------------------------------- #
def _pid_file_path(root: Path) -> Path:
    return root / "run" / "monitor.pid"


def _write_monitor_pid_file(path: Path, pid: int) -> None:
    """Meme format que lancer.py.write_pid_file ("pid:ts") -- duplique en 3
    lignes plutot que d'importer lancer.py depuis trading/ (pas de dependance
    inverse module racine -> package). Best-effort, ne leve jamais."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{int(pid)}:{time.time():.3f}", encoding="ascii")
    except OSError:
        pass


def _remove_own_pid_file(root: Path) -> None:
    """Supprime run/monitor.pid SI ET SEULEMENT SI il pointe CE process --
    n'ecrase jamais le pid d'une instance plus recente (course rare mais
    gratuite a eviter, meme esprit que lancer.py is_our_process). Best-effort,
    ne leve jamais."""
    path = _pid_file_path(root)
    try:
        if not path.exists():
            return
        raw = path.read_text(encoding="ascii").strip()
        pid = int(raw.split(":", 1)[0])
        if pid == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass


def _spawn_detached_monitor(cmd, log_path: Path, cwd: Path) -> int:
    """Relance un `main.py monitor` detache -- meme recette que
    lancer.py.spawn_detached (DETACHED_PROCESS|CREATE_NO_WINDOW sous Windows :
    zero fenetre console). Duplique en local plutot qu'importe (voir
    _write_monitor_pid_file)."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    else:
        kwargs["start_new_session"] = True
    # Repli DEVNULL si le log est verrouille par un autre process (BUG-014) :
    # le respawn PRIME sur son log -- perdre la console vaut mieux que ne
    # jamais redemarrer le serveur.
    try:
        log = open(log_path, "ab")
    except OSError:
        log = None
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            stdout=(log if log is not None else subprocess.DEVNULL),
            stderr=(log if log is not None else subprocess.DEVNULL),
            cwd=str(cwd), **kwargs)
    finally:
        if log is not None:
            log.close()
    return proc.pid


# --------------------------------------------------------------------------- #
#  Paper trading pilotable (Lot 7, /paper) -- demarrage/arret DEPUIS l'UI,     #
#  en reutilisant les gardes de lancer.py (BUG-009 identite PID, BUG-014 log  #
#  verrouille). Le process paper est INDEPENDANT du serveur web : l'arreter   #
#  ou le demarrer depuis /paper ne touche jamais ce serveur (monitor.pid),    #
#  ni l'historique accumule (paper_stats.csv / paper_trades.log / etat).      #
# --------------------------------------------------------------------------- #
def _paper_pid_path(root: Path) -> Path:
    return root / "run" / "paper.pid"


def _paper_identity(root: Path):
    """
    Lit run/paper.pid et confirme l'IDENTITE du process (BUG-009 : Windows
    RECYCLE les PID, un PID vivant-mais-recycle n'est PAS "en cours"). Retourne
    (pid, running, start_ts). Un pid file orphelin/recycle est NETTOYE ici
    (meme comportement que lancer.py do_status/_start_service) -- jamais
    traite comme "en cours" par la suite.
    """
    pid_path = _paper_pid_path(root)
    pid = lancer.read_pid_file(pid_path)
    if pid is None:
        return None, False, None
    start_ts = lancer.read_pid_start(pid_path)
    if lancer.is_our_process(pid, "paper", start_ts):
        return pid, True, start_ts
    lancer.remove_pid_file(pid_path)  # orphelin/recycle : nettoye, traite ARRETE
    return None, False, None


def _spawn_paper_detached(cmd, log_path: Path, cwd: Path) -> int:
    """Lance `main.py paper` detache (Lot 7) -- MEME recette robuste que
    _spawn_detached_monitor (BUG-014 : repli DEVNULL si le log dedie
    (logs/paper_ui.log) est verrouille par un autre process). Duplique en
    local plutot qu'importe (meme raison que _spawn_detached_monitor : pas de
    dependance croisee root <-> package pour cette mecanique bas niveau)."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    else:
        kwargs["start_new_session"] = True
    try:
        log = open(log_path, "ab")
    except OSError:
        log = None
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            stdout=(log if log is not None else subprocess.DEVNULL),
            stderr=(log if log is not None else subprocess.DEVNULL),
            cwd=str(cwd), **kwargs)
    finally:
        if log is not None:
            log.close()
    return proc.pid


def _start_paper_from_params(root: Path, params: dict):
    """
    Demarre `main.py paper` avec les PARAMETRES du formulaire /paper (Lot 7).
    Construit la commande via lancer.build_paper_command_params (garde-fou
    paper-only EN DUR, assert_paper_only -- jamais "live"), -u pour un flush
    immediat (autopsie possible si le process meurt tot, meme lecon que le
    respawn du monitor), log DEDIE logs/paper_ui.log (jamais le
    logs/paper_console.log du lanceur -- BUG-014, verrou exclusif du '>>' shell
    d'un paper deja lance par lancer.py). Retourne (pid, start_ts) ; leve
    OSError si le spawn echoue (JAMAIS avale silencieusement, M9).
    """
    base_cmd = lancer.build_paper_command_params(root, params)
    cmd = [base_cmd[0], "-u"] + base_cmd[1:]
    run_dir, logs_dir = lancer.ensure_dirs(root)
    log_path = logs_dir / "paper_ui.log"
    new_pid = _spawn_paper_detached(cmd, log_path, root)
    start_ts = lancer._process_start_ts(new_pid)
    lancer.write_pid_file(_paper_pid_path(root), new_pid, start_ts)
    return new_pid, start_ts


def _stop_server_thread(server_ref, root: Path) -> None:
    """Arrete le serveur HTTP. DOIT tourner dans un thread SEPARE de celui qui
    execute serve_forever() (shutdown() bloquerait sinon -- cf. doc stdlib
    socketserver). Nettoie ensuite le pid file. Le paper trading n'est PAS
    touche : aucune reference a run/paper.pid ici."""
    srv = server_ref[0]
    if srv is not None:
        srv.shutdown()   # bloque jusqu'a l'arret effectif de serve_forever()
    _remove_own_pid_file(root)


def _service_thread(target, args) -> threading.Thread:
    """Thread de service stop/restart -- NON-daemon PAR CONSTRUCTION (BUG-014).

    Apres shutdown(), le thread principal sort de serve_forever() et le process
    se termine : un thread daemon serait TUE avant d'avoir fini son travail
    (le Popen du respawn ne naissait jamais -- mesure E2E : port mort apres
    /server/restart). Non-daemon : l'interpreteur attend la fin du thread."""
    return threading.Thread(target=target, args=args, daemon=False)


def _restart_server_thread(server_ref, root: Path, port: int, host: str) -> None:
    """Arrete l'ancien serveur PUIS demarre un nouveau process detache sur le
    meme port -- ordre choisi pour eviter toute course de bind (le port doit
    etre LIBRE avant que le nouveau tente de s'y lier ; pas de retry-bind).
    COMPROMIS ASSUME (M20) : court trou de disponibilite (l'ancien se ferme
    avant que le nouveau ne soit pret) plutot qu'une logique de retry-bind
    plus complexe et plus fragile pour un gain marginal -- la page de reponse
    /server/restart previent l'utilisateur et se recharge seule. Le paper
    trading n'est PAS touche."""
    srv = server_ref[0]
    if srv is not None:
        srv.shutdown()
        try:
            srv.server_close()   # libere vraiment le socket d'ecoute
        except OSError:
            pass
    # -u : flush immediat -> si le respawn meurt, sa derniere trace est dans le
    # log (sans -u le buffer est perdu et l'autopsie est aveugle -- meme lecon
    # que le lancement du paper).
    cmd = [sys.executable, "-u", str(root / "main.py"), "monitor", "--port", str(port)]
    # BUG-014 (cause racine MESUREE) : monitor_console.log est tenu en verrou
    # EXCLUSIF par la redirection shell '>>' du monitor courant -> open('ab')
    # levait PermissionError, avale par un except silencieux : le respawn ne
    # naissait JAMAIS. Log DEDIE au respawn (aucun autre detenteur possible).
    log_path = root / "logs" / "monitor_respawn.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        new_pid = _spawn_detached_monitor(cmd, log_path, root)
        _write_monitor_pid_file(_pid_file_path(root), new_pid)
    except OSError as exc:
        # JAMAIS silencieux (M9 signaler-pas-masquer) : l'echec du respawn est
        # la mort de l'app cote user -- on le trace ou on peut.
        try:
            (root / "logs" / "monitor_respawn_error.log").write_text(
                f"respawn ECHEC : {type(exc).__name__}: {exc}\ncmd={cmd}\n",
                encoding="utf-8")
        except OSError:
            pass


def render_server_stopped_page() -> str:
    body = (
        "<div class='head'><h1>Serveur arrêté</h1></div>"
        "<div class='card'>"
        "<p>Le serveur web de monitoring est arrêté.</p>"
        "<p class='muted'>Le <strong>paper trading continue de tourner</strong> "
        "en arrière-plan : il n'est pas touché par ce bouton, et continue "
        "d'écrire dans paper_stats.csv / paper_trades.log.</p>"
        "<p>Pour rouvrir le tableau de bord : double-clique l'icône du "
        "bureau, ou lance <code>python lancer.py</code>.</p>"
        "</div>"
    )
    return page_shell("Serveur arrêté - InsertYourCoin", "options", body)


def render_server_restarting_page() -> str:
    body = (
        "<div class='head'><h1>Redémarrage en cours...</h1></div>"
        "<div class='card'>"
        "<p>Le serveur web redémarre (le paper trading n'est pas touché).</p>"
        "<p class='muted'>Court trou de disponibilité pendant la bascule : "
        "l'ancien processus s'arrête puis un nouveau démarre sur le même "
        "port. Cette page se recharge automatiquement.</p>"
        "</div>"
        "<script>setTimeout(function(){ window.location.href = '/options'; }, 4000);</script>"
    )
    return page_shell("Redémarrage - InsertYourCoin", "options", body)


def csrf_valid(submitted_token, expected_token) -> bool:
    """Comparaison anti-CSRF en temps constant. Faux si l'un est vide/absent."""
    if not submitted_token or not expected_token:
        return False
    return secrets.compare_digest(str(submitted_token), str(expected_token))


def host_allowed(host_header, port) -> bool:
    """
    L'en-tete Host doit cibler 127.0.0.1/localhost sur le bon port (anti
    DNS-rebinding). Le port peut etre omis par certains clients -> tolere.
    """
    if not host_header:
        return False
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"}
    return host_header.strip().lower() in allowed


# --------------------------------------------------------------------------- #
#  Jobs asynchrones (Lot 3) -- routes GET /job/<id>/status, POST /job/<id>/cancel
#                                                                             #
#  Le job_id est un uuid4().hex (32 caracteres hex minuscules, cf. jobs.py) --#
#  le motif ci-dessous valide STRICTEMENT ce format avant tout traitement :  #
#  un id malforme ne matche jamais et tombe sur le 404 generique (pas        #
#  d'injection possible dans un chemin/HTML, en plus de l'echappement HTML   #
#  applique par job_panel_html cote webui.py).                               #
# --------------------------------------------------------------------------- #
_JOB_STATUS_RE = re.compile(r"^/job/([0-9a-f]{32})/status/?$")
_JOB_CANCEL_RE = re.compile(r"^/job/([0-9a-f]{32})/cancel/?$")

# Vue Rapport (Lot 4, spec §4.8) : meme format d'id (uuid4 hex 32) que les
# routes /job/<id>/*. Un id malforme tombe sur le 404 generique (defense en
# profondeur, avant meme d'atteindre JobManager.status).
_REPORT_RE = re.compile(r"^/report/([0-9a-f]{32})/?$")


# --------------------------------------------------------------------------- #
#  Serveur (relit les fichiers a CHAQUE requete)                              #
# --------------------------------------------------------------------------- #
def build_monitor_server(port=8765, host="127.0.0.1",
                         stats_path=None, log_path=None, state_path=None,
                         job_manager=None):
    """
    Construit le serveur de monitoring et le RETOURNE (sans le demarrer).
    Separe de run_monitor pour etre testable en integration (port=0 = port
    ephemere choisi par l'OS). Les chemins None sont resolus par defaut depuis
    project_root() (robuste au repertoire de lancement).

    `job_manager` (Lot 3) : instance `jobs.JobManager` partagee, attachee au
    serveur retourne (`server.job_manager`) pour que les tests -- et les
    futures routes /research/<type> des Lots 4-6 -- puissent y soumettre des
    jobs. None -> une instance neuve est creee (mono-job, en memoire).
    """
    root = project_root()
    jobs = job_manager if job_manager is not None else JobManager()
    # Port reellement lie (mis a jour apres bind ; port=0 -> ephemere). Le
    # Handler lit bound_port[0] pour la verification Host (anti DNS-rebinding).
    bound_port = [port]
    # Reference vers l'objet serveur, remplie juste apres sa construction (le
    # Handler doit exister AVANT que le serveur soit cree, cf. fin de fonction)
    # -- consommee par les routes /server/stop et /server/restart.
    server_ref = [None]
    stats_path = Path(stats_path) if stats_path else root / "paper_stats.csv"
    log_path = Path(log_path) if log_path else root / "paper_trades.log"
    state_path = Path(state_path) if state_path else root / "paper_state.json"

    # Token anti-CSRF genere au demarrage du serveur : un site malveillant ouvert
    # dans le navigateur peut POSTer vers 127.0.0.1, mais ne connait pas ce token.
    csrf_token = secrets.token_hex(32)
    # Cles "session seulement" (case decochee) : gardees EN MEMOIRE du process
    # monitor, JAMAIS ecrites sur disque. Utilisables pour un futur test de liaison.
    _session_keys = {}
    # Dernier resultat de /check?run=1, EN MEMOIRE seulement (jamais persiste) --
    # permet a l'Accueil d'afficher "verifie a HH:MM:SS" sans jamais appeler
    # Kraken lui-meme au chargement (cf. diagnostics_web.run_web_check).
    _last_check = {"value": None}
    # Lot 8 (live verrouille) : nonces d'armement du reel, EN MEMOIRE serveur
    # uniquement (jamais persistes -- un redemarrage invalide tout armement
    # en cours, friction assumee). Cf. trading/live_control.ArmTokenStore.
    _arm_tokens = live_control.ArmTokenStore()
    # BUG-015 (P0, gate independante Lot 8) : ThreadingHTTPServer => chaque
    # POST /live/start tourne dans son propre thread. Verifier
    # live_control.live_identity() (aucun live en cours) PUIS spawn PUIS
    # ecrire le pid file n'est PAS atomique sans verrou -- deux threads
    # porteurs chacun d'un nonce distinct et valide peuvent tous deux lire
    # "aucun live" avant que l'un des deux ait ecrit son pid (reproduit
    # 10/10 par la gate, docs/audit/GATE_LOT8_LIVE.md FAIL-1). Ce Lock
    # serialise EXACTEMENT cette sequence (identite -> spawn -> pid file),
    # pour les deux modes (dry ET reel -- un double dry-run pollue aussi le
    # pid file/sidecar). Il ne protege QUE la fenetre de demarrage, jamais
    # le reste du handler (GET /live, /live/arm, /live/stop restent hors
    # verrou : rien n'y spawn).
    _live_start_lock = threading.Lock()
    # BUG-016 (P2, meme patron que BUG-015) : ThreadingHTTPServer => chaque
    # POST /paper start tourne dans son propre thread. Lire _paper_identity()
    # (aucun paper en cours) PUIS spawn PUIS ecrire run/paper.pid n'est pas
    # atomique sans verrou -- deux threads peuvent tous deux lire "aucun
    # paper" avant que l'un des deux ait ecrit son pid, et demarrer deux
    # paper qui ecrivent le meme paper_state.json/paper_stats.csv (aucun
    # argent reel en jeu, mais corruption de l'historique). Ce Lock serialise
    # EXACTEMENT la sequence identite -> spawn -> pid file, comme
    # _live_start_lock ; il ne protege que la fenetre de demarrage (GET
    # /paper et l'action "stop" restent hors verrou).
    _paper_start_lock = threading.Lock()

    def _compute_view_now():
        """Relit les 3 fichiers et calcule la vue (factorise pour les deux routes)."""
        now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state = read_state(state_path)
        stats = read_last_stats(stats_path)
        log_lines = tail_log(log_path, 40)
        return compute_view(state, stats, log_lines, config.INITIAL_CAPITAL, now_str)

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send_html(self, content, code=200):
            body = content.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, data, code=200):
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            if not host_allowed(self.headers.get("Host"), bound_port[0]):
                self._send_html(
                    _error_page("403 - Host non autorisé",
                                "L'en-tête Host de cette requête n'est pas autorisé "
                                "par ce serveur local."),
                    code=403,
                )
                return False
            return True

        def _handle_job_status(self, job_id):
            # Lecture seule (polling JS) : pas de CSRF, juste la garde Host.
            if not self._host_ok():
                return
            st = jobs.status(job_id)
            if st is None:
                self._send_json({"error": "job introuvable"}, code=404)
                return
            self._send_json(st)

        def _handle_job_cancel(self, job_id):
            # Action d'etat (annulation) : CSRF requis, comme /options.
            if not self._host_ok():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            form = urllib.parse.parse_qs(raw.decode("utf-8", errors="replace"))
            submitted = (form.get("csrf_token") or [""])[0]
            if not csrf_valid(submitted, csrf_token):
                self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                return
            st = jobs.status(job_id)
            if st is None:
                self._send_json({"error": "job introuvable"}, code=404)
                return
            jobs.cancel(job_id)  # cooperatif : positionne le drapeau, sans effet si deja termine
            self._send_json(jobs.status(job_id))

        def _read_post_form(self):
            """Lit et parse le corps x-www-form-urlencoded en dict {nom: 1re valeur}.
            Factorise pour toute route POST hors /options (qui garde son propre
            `_one` historique -- inchange pour ne rien risquer de casser)."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            form = urllib.parse.parse_qs(raw.decode("utf-8", errors="replace"))
            return {k: v[0] for k, v in form.items() if v}

        def _research_backtest_get(self):
            return research_page.render_backtest_form(csrf_token)

        def _research_backtest_post(self, form):
            # CSRF verifie par l'appelant (do_POST) AVANT toute action -- ce job
            # demarre du travail (Backtester), jamais sans jeton valide.
            params, errors = research_page.parse_backtest_params(form)
            if errors:
                return research_page.render_backtest_form(csrf_token, errors=errors, values=form)

            def _target(progress):
                return run_backtest(params, progress)

            label = f"Backtest {params['strategy']} {params['symbol']} ({params['timeframe']})"
            try:
                job_id = jobs.submit(_target, label=label)
            except JobBusy:
                active_id = jobs.active_id
                active_status = jobs.status(active_id) if active_id else None
                active_label = active_status.get("label") if active_status else None
                return research_page.render_backtest_busy(active_label, active_id, csrf_token)
            return research_page.render_backtest_launched(job_id, csrf_token)

        def _research_compare_get(self):
            return compare_page.render_compare_form(csrf_token)

        def _research_compare_post(self, form):
            params, errors = compare_page.parse_compare_params(form)
            if errors:
                return compare_page.render_compare_form(csrf_token, errors=errors, values=form)

            def _target(progress):
                return run_compare(params, progress)

            label = f"Comparer {params['symbol']} ({params['timeframe']})"
            try:
                job_id = jobs.submit(_target, label=label)
            except JobBusy:
                active_id = jobs.active_id
                active_status = jobs.status(active_id) if active_id else None
                active_label = active_status.get("label") if active_status else None
                return compare_page.render_compare_busy(active_label, active_id, csrf_token)
            return compare_page.render_compare_launched(job_id, csrf_token)

        def _research_optimize_get(self):
            return optimize_page.render_optimize_form(csrf_token)

        def _research_optimize_post(self, form):
            params, errors = optimize_page.parse_optimize_params(form)
            if errors:
                return optimize_page.render_optimize_form(csrf_token, errors=errors, values=form)

            def _target(progress):
                return run_optimize(params, progress)

            label = f"Optimiser {params['strategy']} {params['symbol']} ({params['timeframe']})"
            try:
                job_id = jobs.submit(_target, label=label)
            except JobBusy:
                active_id = jobs.active_id
                active_status = jobs.status(active_id) if active_id else None
                active_label = active_status.get("label") if active_status else None
                return optimize_page.render_optimize_busy(active_label, active_id, csrf_token)
            return optimize_page.render_optimize_launched(job_id, csrf_token)

        def _research_portfolio_get(self):
            return portfolio_page.render_portfolio_form(csrf_token)

        def _research_portfolio_post(self, form):
            params, errors = portfolio_page.parse_portfolio_params(form)
            if errors:
                return portfolio_page.render_portfolio_form(csrf_token, errors=errors, values=form)

            def _target(progress):
                return run_portfolio(params, progress)

            label = f"Portefeuille {','.join(params['symbols'])} ({params['strategy']})"
            try:
                job_id = jobs.submit(_target, label=label)
            except JobBusy:
                active_id = jobs.active_id
                active_status = jobs.status(active_id) if active_id else None
                active_label = active_status.get("label") if active_status else None
                return portfolio_page.render_portfolio_busy(active_label, active_id, csrf_token)
            return portfolio_page.render_portfolio_launched(job_id, csrf_token)

        def _research_walkforward_get(self):
            return walkforward_page.render_walkforward_form(csrf_token)

        def _research_walkforward_post(self, form):
            # CSRF verifie par l'appelant (do_POST) AVANT toute action -- ce job
            # demarre du travail reel (walk_forward_multi, parfois holdout_check),
            # jamais sans jeton valide (spec §4.6 : "aucune" securite specifique
            # ne dispense PAS du CSRF standard de toute action qui lance un job).
            params, errors = walkforward_page.parse_walkforward_params(form)
            if errors:
                return walkforward_page.render_walkforward_form(csrf_token, errors=errors, values=form)

            def _target(progress):
                return run_walkforward(params, progress)

            label = f"Walk-forward {params['strategy']} {','.join(params['symbols'])} ({params['timeframe']})"
            try:
                job_id = jobs.submit(_target, label=label)
            except JobBusy:
                active_id = jobs.active_id
                active_status = jobs.status(active_id) if active_id else None
                active_label = active_status.get("label") if active_status else None
                return walkforward_page.render_walkforward_busy(active_label, active_id, csrf_token)
            return walkforward_page.render_walkforward_launched(job_id, csrf_token)

        def _report_get(self, job_id):
            st = jobs.status(job_id)
            if st is None:
                return 404, report_page.render_report_unknown()
            state = st["state"]
            if state in ("pending", "running"):
                return 200, report_page.render_report_pending(job_id, csrf_token)
            if state == "error":
                return 200, report_page.render_report_error(st.get("error_message"))
            if state == "cancelled":
                return 200, report_page.render_report_cancelled()
            # state == "done" : `has_result` False -> le runner a retourne None
            # (cas degenere, ne devrait pas arriver hors annulation -- deja geree
            # au-dessus) ; on affiche un message honnete plutot qu'un rapport vide.
            if not st.get("has_result"):
                return 200, report_page.render_report_error(
                    "Le job s'est termine sans produire de resultat exploitable."
                )
            result = jobs.result(job_id)
            # Lot 5 : dispatcher GENERALISE par result["kind"] (compare/optimize/
            # portfolio/backtest) -- remplace l'appel direct a render_report_done
            # (conserve pour compat, cf. trading/report_page.py render_result_done).
            return 200, report_page.render_result_done(result)

        def _options_page(self, saved=False):
            opts = read_options()
            return render_options_page(
                opts.get("log_level", "moyen"), keys_configured(), csrf_token,
                saved=saved,
            )

        def _home_page(self):
            return render_home_page(
                _compute_view_now(), _last_check["value"],
                keys_configured(), truststore_active(),
            )

        def _paper_status_view(self):
            """Assemble le statut affichable par render_paper_page : identite
            PID confirmee (BUG-009) + alerte inactivite reutilisee de
            compute_view (memes fichiers stats/log que /monitoring)."""
            pid, running, start_ts = _paper_identity(root)
            status = paper_page.compute_paper_status(running, start_ts)
            view = _compute_view_now() if running else {}
            return pid, status, bool(view.get("inactif")), view.get("age_seconds")

        def _paper_get(self, errors=None, values=None, message=None):
            _pid, status, inactif, age_seconds = self._paper_status_view()
            return paper_page.render_paper_page(
                status, csrf_token, errors=errors, values=values,
                message=message, inactif=inactif, age_seconds=age_seconds,
            )

        def _paper_post(self, form):
            action = (form.get("action") or "").strip().lower()
            pid, status, inactif, age_seconds = self._paper_status_view()

            if action == "start":
                if status["running"]:
                    return paper_page.render_paper_page(
                        status, csrf_token, inactif=inactif, age_seconds=age_seconds,
                        errors=["Un paper trading tourne deja -- arrete-le d'abord "
                                "(un seul a la fois, meme fichier d'etat)."],
                    )
                params, errors = paper_page.parse_paper_params(form)
                if errors:
                    return paper_page.render_paper_page(
                        status, csrf_token, errors=errors, values=form,
                    )
                # BUG-016 : identite -> spawn -> pid file, EN UN SEUL BLOC
                # atomique (deux "start" concurrents doivent aussi etre
                # refuses -- meme fichier d'etat/pid). Re-verifie l'identite
                # ICI (pas seulement au-dessus) : sans ce re-check DANS le
                # verrou, la fenetre TOCTOU persiste (cf. _live_start_lock,
                # BUG-015).
                with _paper_start_lock:
                    _pid2, running2, start_ts2 = _paper_identity(root)
                    if running2:
                        running_status = paper_page.compute_paper_status(
                            True, start_ts2)
                        return paper_page.render_paper_page(
                            running_status, csrf_token,
                            errors=["Un paper trading tourne deja -- arrete-le "
                                    "d'abord (un seul a la fois, meme fichier "
                                    "d'etat)."],
                        )
                    try:
                        new_pid, start_ts = _start_paper_from_params(root, params)
                    except OSError as exc:
                        # JAMAIS silencieux (M9) : trace + affiche, comme le
                        # respawn du monitor (_restart_server_thread).
                        try:
                            (root / "logs" / "paper_ui_error.log").write_text(
                                f"demarrage paper ECHEC : {type(exc).__name__}: {exc}\n",
                                encoding="utf-8")
                        except OSError:
                            pass
                        return paper_page.render_paper_page(
                            status, csrf_token, values=form,
                            errors=[f"Echec du demarrage du paper trading : {exc}"],
                        )
                    new_status = paper_page.compute_paper_status(True, start_ts)
                    return paper_page.render_paper_page(
                        new_status, csrf_token, message="Paper trading demarre.",
                    )

            if action == "stop":
                if not status["running"] or pid is None:
                    return paper_page.render_paper_page(
                        status, csrf_token, inactif=inactif, age_seconds=age_seconds,
                        errors=["Aucun paper trading en cours (rien a arreter)."],
                    )
                lancer.terminate_pid(pid)
                lancer.remove_pid_file(_paper_pid_path(root))
                stopped_status = paper_page.compute_paper_status(False, None)
                return paper_page.render_paper_page(
                    stopped_status, csrf_token,
                    message="Paper trading arrete. L'historique (paper_stats.csv, "
                            "paper_trades.log, paper_state.json) est conserve.",
                )

            return paper_page.render_paper_page(
                status, csrf_token, inactif=inactif, age_seconds=age_seconds,
                errors=["Action inconnue."],
            )

        # ------------------------------------------------------------- #
        #  Lot 8 -- Live verrouille (/live). P0 (argent reel). Suit      #
        #  docs/design/LOT8_LIVE_SPEC.md a la lettre : deux round-trips  #
        #  serveur (/live/arm PUIS /live/start) pour le reel, dry-run    #
        #  par defaut, aucun plafond ni cle en argument (N4/N6),         #
        #  re-validation des pre-requis a CHAQUE etape (N10).            #
        # ------------------------------------------------------------- #
        def _live_check_ok(self):
            val = _last_check["value"]
            return bool(val and val.get("ok"))

        def _live_prereq(self):
            # Pre-requis (A) RE-TESTES ici -- jamais mis en cache (N10) :
            # cet appel est refait a CHAQUE round-trip (GET /live, POST
            # /live/arm, POST /live/start).
            return live_control.check_prerequisites_a(
                keys_configured(), self._live_check_ok(), state_path.exists(),
            )

        def _live_get(self):
            pid, running, start_ts = live_control.live_identity(root)
            if running:
                sidecar = live_control.read_live_sidecar(
                    live_control.live_sidecar_path(root)) or {}
                now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                live_stats = read_last_stats(root / "live_stats.csv")
                live_log = tail_log(root / "live_trades.log", 60)
                # state=None (le live n'ecrit pas de JSON d'etat comme le
                # paper) -- compute_view deduit "investi" depuis l'exposition.
                view = compute_view(None, live_stats, live_log,
                                    config.INITIAL_CAPITAL, now_str)
                return live_page.render_live_running(sidecar, pid, start_ts,
                                                      csrf_token, view)
            prereq = self._live_prereq()
            return live_page.render_live_wall(
                prereq, keys_configured(), self._live_check_ok(),
                state_path.exists(), csrf_token,
            )

        def _live_arm_post(self, form):
            # Round-trip 1 du reel (spec §1.3). AVANT tout nonce : re-valide
            # (A) cote serveur, exige les 3 attestations (B) et mode=="reel"
            # EXACTEMENT -- un seul manque -> AUCUN nonce emis (N2).
            prereq = self._live_prereq()
            mode_ok = live_control.resolve_execute(form)
            attest_ok = live_control.attestations_ok(form)
            if not (prereq["ok"] and attest_ok and mode_ok):
                msgs = []
                if not prereq["ok"]:
                    msgs.append(live_page.prereq_refusal_message(prereq))
                if not attest_ok:
                    msgs.append("Les 3 attestations doivent être cochées avant "
                                "de continuer en réel.")
                if not mode_ok:
                    msgs.append("Mode réel non demandé.")
                return live_page.render_live_wall(
                    prereq, keys_configured(), self._live_check_ok(),
                    state_path.exists(), csrf_token, errors=msgs, values=form,
                )
            params, errors = live_page.parse_live_params(form)
            if errors:
                return live_page.render_live_wall(
                    prereq, keys_configured(), self._live_check_ok(),
                    state_path.exists(), csrf_token, errors=errors, values=form,
                )
            nonce = _arm_tokens.create(params)
            return live_page.render_live_recap(params, nonce, csrf_token)

        def _live_start_post(self, form):
            mode = (form.get("mode") or "").strip().lower()

            if mode == "dry":
                # Chemin court dry-run (spec §1.5) : AUCUN nonce/phrase
                # exige -- seulement (A.1) cles + CSRF + host (deja verifies
                # par l'appelant). Un mode absent/ambigu ne demarre RIEN
                # (fail-safe N3), gere par le "else" plus bas.
                if not keys_configured():
                    return live_page.render_live_wall(
                        self._live_prereq(), False, self._live_check_ok(),
                        state_path.exists(), csrf_token,
                        errors=["Clés API manquantes. Renseigne .env (voir "
                                ".env.example) avant le mode live."],
                    )
                params, errors = live_page.parse_live_params(form)
                if errors:
                    return live_page.render_live_wall(
                        self._live_prereq(), keys_configured(),
                        self._live_check_ok(), state_path.exists(), csrf_token,
                        errors=errors, values=form,
                    )
                # BUG-015 : identite -> spawn -> pid file, EN UN SEUL BLOC
                # atomique (deux dry-run concurrents doivent aussi etre
                # refuses -- meme pid file/sidecar que le reel).
                with _live_start_lock:
                    _pid, running, _start_ts = live_control.live_identity(root)
                    if running:
                        return self._live_get()
                    try:
                        live_control.start_live_process(root, params, execute=False)
                    except OSError as exc:
                        try:
                            (root / "logs" / "live_error.log").write_text(
                                f"demarrage live (dry) ECHEC : {type(exc).__name__}: {exc}\n",
                                encoding="utf-8")
                        except OSError:
                            pass
                        return live_page.render_live_wall(
                            self._live_prereq(), keys_configured(),
                            self._live_check_ok(), state_path.exists(), csrf_token,
                            errors=[f"Échec du démarrage (simulation) : {exc}"],
                        )
                    return self._live_get()

            # --- Chemin REEL (round-trip 2, spec §1.4) --------------------
            nonce = form.get("nonce")
            params = _arm_tokens.peek_params(nonce)
            if params is None:
                # Nonce absent/inconnu/consomme/expire -> REFUS, AUCUN spawn
                # (N2). Un POST /live/start direct (sans /live/arm prealable)
                # tombe TOUJOURS ici.
                return live_page.render_live_wall(
                    self._live_prereq(), keys_configured(), self._live_check_ok(),
                    state_path.exists(), csrf_token,
                    errors=["Armement expiré ou invalide. Recommence depuis "
                            "le début."],
                )
            prereq = self._live_prereq()  # RE-validation cote serveur (N10)
            if not prereq["ok"]:
                return live_page.render_live_wall(
                    prereq, keys_configured(), self._live_check_ok(),
                    state_path.exists(), csrf_token,
                    errors=["Un pré-requis a changé depuis l'armement. Annulé. "
                            "(Aucun ordre envoyé.)"],
                )
            if mode != "reel":
                return live_page.render_live_wall(
                    prereq, keys_configured(), self._live_check_ok(),
                    state_path.exists(), csrf_token,
                    errors=["Annulé. (Aucun ordre envoyé.)"],
                )
            phrase = form.get("phrase")
            if not live_control.phrase_ok(phrase):
                still_valid = _arm_tokens.register_failed_phrase(nonce)
                if still_valid:
                    return live_page.render_live_recap(
                        params, nonce, csrf_token,
                        errors=["Phrase incorrecte. Annulé. (Aucun ordre envoyé.)"],
                    )
                return live_page.render_live_wall(
                    self._live_prereq(), keys_configured(), self._live_check_ok(),
                    state_path.exists(), csrf_token,
                    errors=["Annulé. (Aucun ordre envoyé.) Trop de tentatives : "
                            "recommence depuis le début."],
                )
            # "Un seul live a la fois" (spec §1.4.6). BUG-015 : identite ->
            # consommation du nonce -> spawn -> pid file, EN UN SEUL BLOC
            # atomique (_live_start_lock) -- sans lui, deux threads porteurs
            # chacun d'un nonce distinct et valide peuvent tous deux lire
            # "aucun live en cours" avant que l'un des deux ait ecrit son pid
            # (reproduit 10/10 par la gate independante, FAIL-1). Le verrou
            # n'engage que cette fenetre de demarrage, jamais la duree de vie
            # du trader (le process reste detache, aucun changement d'archi).
            with _live_start_lock:
                _pid, running, _start_ts = live_control.live_identity(root)
                if running:
                    return self._live_get()
                # Tout est verifie -> consomme le nonce (USAGE UNIQUE) puis spawn.
                confirmed_params = _arm_tokens.consume(nonce)
                if confirmed_params is None:
                    # Rejeu du meme POST apres un 1er succes : le nonce a deja
                    # ete consomme -> AUCUN spawn (N2, anti-rejeu).
                    return live_page.render_live_wall(
                        self._live_prereq(), keys_configured(), self._live_check_ok(),
                        state_path.exists(), csrf_token,
                        errors=["Armement expiré ou invalide. Recommence depuis "
                                "le début."],
                    )
                try:
                    live_control.start_live_process(root, confirmed_params, execute=True)
                except OSError as exc:
                    try:
                        (root / "logs" / "live_error.log").write_text(
                            f"demarrage live (reel) ECHEC : {type(exc).__name__}: {exc}\n",
                            encoding="utf-8")
                    except OSError:
                        pass
                    return live_page.render_live_wall(
                        self._live_prereq(), keys_configured(), self._live_check_ok(),
                        state_path.exists(), csrf_token,
                        errors=[f"Échec du démarrage (réel) : {exc}"],
                    )
                return self._live_get()

        def _live_stop_post(self, form):
            pid, running, _start_ts = live_control.live_identity(root)
            if not running or pid is None:
                # Identite non confirmee (BUG-009) est deja NETTOYEE par
                # live_identity -- on n'appelle JAMAIS terminate_pid ici.
                return live_page.render_live_wall(
                    self._live_prereq(), keys_configured(), self._live_check_ok(),
                    state_path.exists(), csrf_token,
                    errors=["Aucun live en cours (rien à arrêter)."],
                )
            lancer.terminate_pid(pid)
            lancer.remove_pid_file(live_control.live_pid_path(root))
            live_control.remove_live_sidecar(live_control.live_sidecar_path(root))
            return live_page.render_live_stopped()

        def _stats_page(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            requested = (qs.get("file", [""])[0] or "").strip()
            directory = stats_path.parent
            chosen = resolve_stats_path(directory, requested, stats_path)
            available = list_stats_csvs(directory)
            # Le fichier par defaut peut ne pas matcher "*_stats.csv" (ex. le
            # nom par defaut "paper_stats.csv" le fait, mais un chemin custom
            # passe en test ne le fait pas forcement) : on le propose quand
            # meme dans la liste affichee s'il existe, SANS jamais lire un nom
            # different de celui deja resolu ci-dessus.
            if chosen.name not in available and chosen.exists():
                available = sorted(set(available) | {chosen.name})
            try:
                summary = summarize(load_stats(chosen))
                empty_message = None
            except FileNotFoundError as exc:
                summary = None
                empty_message = str(exc)
            return render_stats_page(chosen.name, available, summary, empty_message)

        def _check_page(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            symbol = (qs.get("symbol", [""])[0] or config.DEFAULT_SYMBOL).strip()
            if qs.get("run", ["0"])[0] == "1":
                # UN SEUL appel reseau, lecture seule (fetch_price) -- jamais
                # declenche par un simple chargement de page (cf. spec §4.2).
                result = run_web_check(symbol)
                _last_check["value"] = result
            else:
                result = _last_check["value"]
            return render_check_page(symbol, static_diagnostic_lines(), result=result)

        def _send_static(self, rel_path):
            result = serve_static(rel_path)
            if result is None:
                self._send_html(
                    _error_page("404 - Page introuvable",
                                "Cette adresse ne correspond à aucune page de l'application."),
                    code=404,
                )
                return
            data, content_type = result
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                if self.path.startswith("/static/"):
                    rel = urllib.parse.unquote(self.path[len("/static/"):].split("?", 1)[0])
                    self._send_static(rel)
                    return
                if self.path.startswith("/job/"):
                    m = _JOB_STATUS_RE.match(self.path.split("?", 1)[0])
                    if m:
                        self._handle_job_status(m.group(1))
                        return
                    self._send_html(
                    _error_page("404 - Page introuvable",
                                "Cette adresse ne correspond à aucune page de l'application."),
                    code=404,
                )
                    return
                if self.path.startswith("/research/backtest"):
                    if not self._host_ok():
                        return
                    self._send_html(self._research_backtest_get())
                    return
                if self.path.startswith("/research/compare"):
                    if not self._host_ok():
                        return
                    self._send_html(self._research_compare_get())
                    return
                if self.path.startswith("/research/optimize"):
                    if not self._host_ok():
                        return
                    self._send_html(self._research_optimize_get())
                    return
                if self.path.startswith("/research/portfolio"):
                    if not self._host_ok():
                        return
                    self._send_html(self._research_portfolio_get())
                    return
                if self.path.startswith("/research/walkforward"):
                    if not self._host_ok():
                        return
                    self._send_html(self._research_walkforward_get())
                    return
                if self.path.startswith("/report/"):
                    m = _REPORT_RE.match(self.path.split("?", 1)[0])
                    if not m:
                        self._send_html(
                    _error_page("404 - Page introuvable",
                                "Cette adresse ne correspond à aucune page de l'application."),
                    code=404,
                )
                        return
                    if not self._host_ok():
                        return
                    code, page = self._report_get(m.group(1))
                    self._send_html(page, code=code)
                    return
                if self.path.startswith("/options"):
                    if not self._host_ok():
                        return
                    saved = "saved=1" in (self.path.split("?", 1)[1]
                                          if "?" in self.path else "")
                    self._send_html(self._options_page(saved=saved))
                    return
                if self.path.startswith("/paper"):
                    if not self._host_ok():
                        return
                    self._send_html(self._paper_get())
                    return
                if self.path == "/live" or self.path.startswith("/live?"):
                    # Lot 8 : GET exact seulement ("/live/arm" etc. sont des
                    # routes POST -- pas de sous-route GET, cf. §7.1).
                    if not self._host_ok():
                        return
                    self._send_html(self._live_get())
                    return
                if self.path.startswith("/check"):
                    if not self._host_ok():
                        return
                    self._send_html(self._check_page())
                    return
                if self.path.startswith("/help"):
                    # Page statique (spec §4.14) : meme garde Host que le
                    # reste, aucune donnee lue (contenu entierement fixe).
                    if not self._host_ok():
                        return
                    self._send_html(render_help_page())
                    return
                if self.path.startswith("/stats"):
                    if not self._host_ok():
                        return
                    self._send_html(self._stats_page())
                    return
                if self.path.startswith("/monitoring"):
                    # Ex-"/" (Lot 0). Page complete (coquille + fragment + script JS).
                    self._send_html(build_html(_compute_view_now()))
                    return
                if self.path.startswith("/fragment"):
                    # Route fragment : retourne uniquement le contenu (pas la coquille).
                    # Chemin inchange par la bascule de route -- consomme par le JS
                    # de la page /monitoring, peu importe la page qui l'a chargee.
                    self._send_html(render_fragment(_compute_view_now()))
                    return
                if self.path == "/" or self.path.startswith("/?"):
                    if not self._host_ok():
                        return
                    self._send_html(self._home_page())
                    return
                self._send_html(
                    _error_page("404 - Page introuvable",
                                "Cette adresse ne correspond à aucune page de l'application."),
                    code=404,
                )
            except Exception as exc:  # ne JAMAIS crasher le serveur
                # NE JAMAIS inclure de donnee sensible : str(exc) ne porte pas de cle.
                # _error_page echappe deja le message (_esc) -- ne pas le faire 2x.
                self._send_html(_error_page("Erreur monitoring", str(exc)))

        def do_POST(self):
            # /job/<id>/cancel (Lot 3), /research/backtest (Lot 4),
            # /research/{compare,optimize,portfolio} (Lot 5),
            # /research/walkforward (Lot 6), /paper (Lot 7) et /options
            # acceptent un POST ; tout le reste -> 404.
            if self.path.startswith("/job/"):
                m = _JOB_CANCEL_RE.match(self.path.split("?", 1)[0])
                if m:
                    self._handle_job_cancel(m.group(1))
                    return
                self._send_html(
                    _error_page("404 - Page introuvable",
                                "Cette adresse ne correspond à aucune page de l'application."),
                    code=404,
                )
                return
            if self.path.startswith("/research/backtest"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._research_backtest_post(form))
                return
            if self.path.startswith("/research/compare"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._research_compare_post(form))
                return
            if self.path.startswith("/research/optimize"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._research_optimize_post(form))
                return
            if self.path.startswith("/research/portfolio"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._research_portfolio_post(form))
                return
            if self.path.startswith("/research/walkforward"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._research_walkforward_post(form))
                return
            if self.path.startswith("/paper"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._paper_post(form))
                return
            if self.path.startswith("/live/arm"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._live_arm_post(form))
                return
            if self.path.startswith("/live/start"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._live_start_post(form))
                return
            if self.path.startswith("/live/stop"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(self._live_stop_post(form))
                return
            if self.path.startswith("/server/stop"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                # Reponse envoyee AVANT de couper (sinon la requete ne recoit
                # jamais sa reponse -- le serveur qui la sert serait deja
                # arrete). L'arret reel se fait dans un thread SEPARE.
                self._send_html(render_server_stopped_page())
                _service_thread(_stop_server_thread, (server_ref, root)).start()
                return
            if self.path.startswith("/server/restart"):
                if not self._host_ok():
                    return
                form = self._read_post_form()
                if not csrf_valid(form.get("csrf_token"), csrf_token):
                    self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                    return
                self._send_html(render_server_restarting_page())
                _service_thread(_restart_server_thread,
                                (server_ref, root, bound_port[0], host)).start()
                return
            if not self.path.startswith("/options"):
                self._send_html(
                    _error_page("404 - Page introuvable",
                                "Cette adresse ne correspond à aucune page de l'application."),
                    code=404,
                )
                return
            if not self._host_ok():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            form = urllib.parse.parse_qs(raw.decode("utf-8", errors="replace"))

            def _one(name):
                vals = form.get(name)
                return vals[0] if vals else ""

            # Verification anti-CSRF AVANT toute action.
            if not csrf_valid(_one("csrf_token"), csrf_token):
                self._send_html(
                    _error_page("403 - Jeton CSRF invalide",
                                "Ce formulaire a expiré ou provient d'une autre "
                                "page. Recharge la page et réessaie."),
                    code=403,
                )
                return

            try:
                # 1) Niveau de logs (ecrit dans options.json si valide).
                level = _one("log_level")
                if level in LOG_LEVELS:
                    opts = read_options()
                    opts["log_level"] = level
                    write_options(opts)

                # 2) Cles API : seulement si fournies. Persistance .env si case cochee,
                #    sinon stockage memoire (session). Les VALEURS ne sont jamais
                #    loggees ni renvoyees.
                api_key = _one("api_key")
                api_secret = _one("api_secret")
                persist = _one("persist") == "1"
                updates = {}
                if api_key:
                    updates["KRAKEN_API_KEY"] = api_key
                if api_secret:
                    updates["KRAKEN_API_SECRET"] = api_secret
                if updates:
                    if persist:
                        update_env_file(updates)        # ecrit .env (preserve le reste)
                        _session_keys.clear()
                    else:
                        _session_keys.update(updates)   # memoire seulement
            except ValueError:
                # Valeur refusee (ex : retour a la ligne dans une cle). On NE remonte
                # PAS la valeur : message generique.
                self._send_html(
                    _error_page("400 - Valeur invalide",
                                "Un des champs soumis n'est pas accepté (ex. retour "
                                "à la ligne dans une clé). Rien n'a été enregistré."),
                    code=400,
                )
                return
            except Exception:
                self._send_html(
                    _error_page("500 - Erreur d'enregistrement",
                                "L'enregistrement des options a échoué côté serveur."),
                    code=500,
                )
                return

            # Redirection 303 (Post/Redirect/Get) -> evite le re-POST au refresh.
            self.send_response(303)
            self.send_header("Location", "/options?saved=1")
            self.end_headers()

        def log_message(self, *args):
            pass  # silence les logs http (ne pas polluer la console)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    bound_port[0] = server.server_address[1]   # port reel (utile si port=0)
    server.job_manager = jobs   # expose pour les tests + les futures routes /research/<type>
    server_ref[0] = server      # expose pour /server/stop et /server/restart
    return server


def run_monitor(port=8765, host="127.0.0.1",
                stats_path=None, log_path=None, state_path=None):
    """Demarre le serveur de monitoring (bloquant). Cf. build_monitor_server."""
    server = build_monitor_server(port=port, host=host, stats_path=stats_path,
                                  log_path=log_path, state_path=state_path)
    print(f"Monitoring sur http://{host}:{server.server_address[1]}  (Ctrl+C pour arreter)")
    server.serve_forever()
