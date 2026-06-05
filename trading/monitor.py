"""
Serveur de monitoring web LEGER pour visualiser le paper trading EN DIRECT.

STDLIB UNIQUEMENT (http.server) : zero nouvelle dependance (install propre,
anti-virus proof). Le serveur LIT seulement des fichiers (paper_stats.csv,
paper_trades.log, paper_state.json) -- il ne touche JAMAIS au trading.

Conception :
- des fonctions PURES (lecture fichiers, assemblage de la vue, rendu HTML)
  testables sans serveur ni reseau ;
- un petit serveur ThreadingHTTPServer qui relit les fichiers a CHAQUE requete
  (donnees fraiches) et sert deux routes :
    GET /          -> page complete (coquille + fragment initial + script JS)
    GET /fragment  -> fragment HTML seul (refresh partiel JS, sans rechargement)
  Le script JS cote client fait un fetch('/fragment') toutes les 7s et injecte
  le resultat dans <div id="content"> -- jamais de rechargement de page entiere.
"""
import csv
import datetime as dt
import html
import http.server
import json
from pathlib import Path

import config


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
        f"<span class='maj'>Derniere maj : {now} (auto-refresh 7s)</span>"
    )

    if not view.get("has_data"):
        return (
            horodatage
            + "<div class='card empty'>"
            "<h2>En attente de donnees du paper...</h2>"
            "<p class='muted'>Lance le paper trading pour voir apparaitre "
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
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; background: #0e1116; color: #d7dee8;
  font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
h1 { font-size: 18px; margin: 0 0 4px; }
h2 { font-size: 14px; margin: 0 0 10px; color: #9fb0c3; text-transform: uppercase;
  letter-spacing: .5px; }
.muted { color: #6b7787; }
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
.head .maj { color: #6b7787; font-size: 12px; }
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
    Coquille HTML chargee UNE SEULE FOIS. `fragment` est le contenu initial
    produit par render_fragment(view), injecte dans <div id='content'>.
    Le script JS met a jour ce div toutes les 7s via fetch('/fragment').
    AUCUN meta http-equiv='refresh' -- la page ne se recharge jamais.
    """
    return (
        "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Paper trading - monitoring</title>"
        f"<style>{_CSS}</style></head><body>"
        "<div class='head'><h1>Paper trading - monitoring</h1></div>"
        f"<div id='content'>{fragment}</div>"
        + _JS_REFRESH
        + "</body></html>"
    )


# --------------------------------------------------------------------------- #
#  Serveur (relit les fichiers a CHAQUE requete)                              #
# --------------------------------------------------------------------------- #
def run_monitor(port=8765, host="127.0.0.1",
                stats_path=None, log_path=None, state_path=None):
    """
    Demarre le serveur de monitoring (bloquant). Les chemins None sont resolus
    par defaut depuis project_root() (robuste au repertoire de lancement).
    """
    root = project_root()
    stats_path = Path(stats_path) if stats_path else root / "paper_stats.csv"
    log_path = Path(log_path) if log_path else root / "paper_trades.log"
    state_path = Path(state_path) if state_path else root / "paper_state.json"

    def _compute_view_now():
        """Relit les 3 fichiers et calcule la vue (factorise pour les deux routes)."""
        now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state = read_state(state_path)
        stats = read_last_stats(stats_path)
        log_lines = tail_log(log_path, 40)
        return compute_view(state, stats, log_lines, config.INITIAL_CAPITAL, now_str)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                view = _compute_view_now()
                if self.path.startswith("/fragment"):
                    # Route fragment : retourne uniquement le contenu (pas la coquille).
                    content = render_fragment(view)
                else:
                    # Route principale : page complete (coquille + fragment + script JS).
                    content = build_html(view)
            except Exception as exc:  # ne JAMAIS crasher le serveur
                content = (
                    "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>"
                    "<title>Erreur monitoring</title></head><body>"
                    f"<h1>Erreur monitoring : {html.escape(str(exc))}</h1>"
                    "</body></html>"
                )
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # silence les logs http (ne pas polluer la console)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    print(f"Monitoring sur http://{host}:{port}  (Ctrl+C pour arreter)")
    server.serve_forever()
