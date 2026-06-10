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
import secrets
import urllib.parse
from pathlib import Path

import config
from .options import (
    read_options, write_options, update_env_file, keys_configured, LOG_LEVELS,
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
        "<div class='head'><h1>Paper trading - monitoring</h1>"
        "<a class='navlink' href='/options'>Options</a></div>"
        f"<div id='content'>{fragment}</div>"
        + _JS_REFRESH
        + "</body></html>"
    )


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
  padding: 9px 18px; font-size: 14px; cursor: pointer; }
.btn:hover { background: #2a7bff; }
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
        "<div class='saved'>Modifications enregistrees.</div>" if saved else ""
    )

    # Boutons radio niveau de logs (l'actif est coche).
    radios = []
    labels = {"leger": "Leger (evenements seuls)",
              "moyen": "Moyen (defaut : + statut par cycle)",
              "complet": "Complet (+ detail par cycle)"}
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
        "<a class='navlink' href='/'>&larr; Retour au monitoring</a></div>"
        + saved_html
        + "<form class='opt' method='post' action='/options'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"

        # (a) Niveau de logs
        "<div class='card'><h2>Niveau de logs du paper</h2>"
        + radio_html
        + "<p class='help'>Applique a chaud (le paper relit ce reglage a chaque "
          "cycle). Les ACHAT/VENTE et les erreurs sont toujours journalises.</p>"
        "</div>"

        # (b) Liaison Kraken
        "<div class='card'><h2>Liaison Kraken</h2>"
        f"<p>Cles configurees : {etat_cles}</p>"
        "<div class='field'><label class='flabel' for='api_key'>Cle API "
        "(publique)</label>"
        "<input type='password' id='api_key' name='api_key' autocomplete='off' "
        "placeholder='(laisser vide pour ne pas changer)'></div>"
        "<div class='field'><label class='flabel' for='api_secret'>Cle privee "
        "(secret)</label>"
        "<input type='password' id='api_secret' name='api_secret' "
        "autocomplete='off' placeholder='(laisser vide pour ne pas changer)'></div>"
        "<div class='check-row'><input type='checkbox' id='persist' "
        "name='persist' value='1'>"
        "<label for='persist'>Enregistrer dans .env (sinon : session seulement, "
        "rien n'est ecrit sur disque)</label></div>"
        "<p class='help'>Cree ta cle sur Kraken avec UNIQUEMENT "
        "<strong>Query Funds</strong> + <strong>Create &amp; Modify Orders</strong>. "
        "<span class='warn'>JAMAIS</span> <strong>Withdraw Funds</strong> : cette "
        "application n'a aucun besoin de retirer des fonds.</p>"
        "<button class='btn' type='submit'>Enregistrer</button>"
        "</div>"
        "</form>"

        # (c) Wallet
        "<div class='card'><h2>Wallet</h2>"
        f"<p><a class='wallet' href='{_WITHDRAW_URL}' target='_blank' "
        "rel='noopener'>Transferer vers mon wallet (page officielle Kraken)</a></p>"
        "<p class='help'>Le retrait se fait sur Kraken avec ton 2FA. Conseil : "
        "active la <strong>whitelist d'adresses</strong> de retrait. "
        "CETTE APP NE FAIT JAMAIS DE RETRAIT ET N'ENREGISTRE RIEN COTE WALLET.</p>"
        "</div>"
    )

    return (
        "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Options - monitoring</title>"
        f"<style>{_OPTIONS_CSS}</style></head><body>"
        + body
        + "</body></html>"
    )


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
#  Serveur (relit les fichiers a CHAQUE requete)                              #
# --------------------------------------------------------------------------- #
def build_monitor_server(port=8765, host="127.0.0.1",
                         stats_path=None, log_path=None, state_path=None):
    """
    Construit le serveur de monitoring et le RETOURNE (sans le demarrer).
    Separe de run_monitor pour etre testable en integration (port=0 = port
    ephemere choisi par l'OS). Les chemins None sont resolus par defaut depuis
    project_root() (robuste au repertoire de lancement).
    """
    root = project_root()
    # Port reellement lie (mis a jour apres bind ; port=0 -> ephemere). Le
    # Handler lit bound_port[0] pour la verification Host (anti DNS-rebinding).
    bound_port = [port]
    stats_path = Path(stats_path) if stats_path else root / "paper_stats.csv"
    log_path = Path(log_path) if log_path else root / "paper_trades.log"
    state_path = Path(state_path) if state_path else root / "paper_state.json"

    # Token anti-CSRF genere au demarrage du serveur : un site malveillant ouvert
    # dans le navigateur peut POSTer vers 127.0.0.1, mais ne connait pas ce token.
    csrf_token = secrets.token_hex(32)
    # Cles "session seulement" (case decochee) : gardees EN MEMOIRE du process
    # monitor, JAMAIS ecrites sur disque. Utilisables pour un futur test de liaison.
    _session_keys = {}

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

        def _host_ok(self):
            if not host_allowed(self.headers.get("Host"), bound_port[0]):
                self._send_html("<h1>403 - Host non autorise</h1>", code=403)
                return False
            return True

        def _options_page(self, saved=False):
            opts = read_options()
            return render_options_page(
                opts.get("log_level", "moyen"), keys_configured(), csrf_token,
                saved=saved,
            )

        def do_GET(self):
            try:
                if self.path.startswith("/options"):
                    if not self._host_ok():
                        return
                    saved = "saved=1" in (self.path.split("?", 1)[1]
                                          if "?" in self.path else "")
                    self._send_html(self._options_page(saved=saved))
                    return
                view = _compute_view_now()
                if self.path.startswith("/fragment"):
                    # Route fragment : retourne uniquement le contenu (pas la coquille).
                    content = render_fragment(view)
                else:
                    # Route principale : page complete (coquille + fragment + script JS).
                    content = build_html(view)
                self._send_html(content)
            except Exception as exc:  # ne JAMAIS crasher le serveur
                # NE JAMAIS inclure de donnee sensible : str(exc) ne porte pas de cle.
                self._send_html(
                    "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>"
                    "<title>Erreur monitoring</title></head><body>"
                    f"<h1>Erreur monitoring : {html.escape(str(exc))}</h1>"
                    "</body></html>"
                )

        def do_POST(self):
            # Seule /options accepte un POST ; tout le reste -> 404.
            if not self.path.startswith("/options"):
                self._send_html("<h1>404</h1>", code=404)
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
                self._send_html("<h1>403 - jeton CSRF invalide</h1>", code=403)
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
                self._send_html("<h1>400 - valeur invalide</h1>", code=400)
                return
            except Exception:
                self._send_html("<h1>500 - erreur enregistrement</h1>", code=500)
                return

            # Redirection 303 (Post/Redirect/Get) -> evite le re-POST au refresh.
            self.send_response(303)
            self.send_header("Location", "/options?saved=1")
            self.end_headers()

        def log_message(self, *args):
            pass  # silence les logs http (ne pas polluer la console)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    bound_port[0] = server.server_address[1]   # port reel (utile si port=0)
    return server


def run_monitor(port=8765, host="127.0.0.1",
                stats_path=None, log_path=None, state_path=None):
    """Demarre le serveur de monitoring (bloquant). Cf. build_monitor_server."""
    server = build_monitor_server(port=port, host=host, stats_path=stats_path,
                                  log_path=log_path, state_path=state_path)
    print(f"Monitoring sur http://{host}:{server.server_address[1]}  (Ctrl+C pour arreter)")
    server.serve_forever()
