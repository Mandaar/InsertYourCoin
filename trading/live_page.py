"""
Ecran Live (/live) -- fonctions PURES de rendu et de parsing (testables sans
serveur, sans reseau), cf. docs/design/LOT8_LIVE_SPEC.md. L'ecran le plus
sensible de l'app (argent reel) : verrouille par defaut, dry-run par defaut,
double confirmation en 2 round-trips serveur pour le mode REEL.

Aucune I/O ici : tout ce qui touche au disque/process vit dans
trading/live_control.py (nonce, identite PID, spawn, sidecar). Ce module ne
fait que PARSER un dict de champs deja extrait du POST et RENDRE du HTML --
memes conventions que trading/paper_page.py et trading/research_page.py.

Securite (rappel, la logique vit cote route/live_control -- ce module ne fait
QUE de l'affichage) :
- Radio "Simulation (dry-run)" decorative, SELECTIONNEE PAR DEFAUT -- affichage
  seul, le mode REEL n'est JAMAIS atteignable par ce formulaire seul (deux
  FORMULAIRES SEPARES : un vers /live/start mode=dry, un vers /live/arm
  mode=reel -- aucun bouton ne peut faire prendre le raccourci).
- Plafonds config.py toujours affiches (mur ET recap).
- AUCUNE valeur de cle n'apparait jamais ici (seul un booleen "cles OK").
"""
import html

import config
from .live_control import ATTESTATION_FIELDS, PHRASE_CONFIRMATION
from .research_page import TIMEFRAME_CHOICES, parse_risk_fields
from .strategies import STRATEGIES, build_strategy
from .webui import page_shell

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
h2 { font-size: 14px; margin: 0 0 10px; color: #9fb0c3; text-transform: uppercase;
  letter-spacing: .5px; }
.muted { color: #8b97a6; }
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.banner-risk { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 12px 16px; margin-bottom: 14px; font-weight: 600; }
.mode-banner { border-radius: 8px; padding: 12px 16px; margin-bottom: 14px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .5px; }
.mode-banner.reel { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad; }
.mode-banner.dry { background: #3a2a12; border: 1px solid #f0b429; color: #ffd98a; }
.prereq-row { display: flex; flex-direction: column; gap: 6px; margin: 8px 0; }
.prereq { font-size: 13px; }
.prereq .ok { color: #46c46f; font-weight: 600; }
.prereq .no { color: #e5534b; font-weight: 600; }
.caps { font-size: 13px; line-height: 1.7; }
.radio-row { display: flex; gap: 18px; flex-wrap: wrap; margin: 6px 0 4px; }
.radio-row label { display: flex; align-items: center; gap: 6px; }
.lp-form .row { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 14px; }
.lp-form .field { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.lp-form label.flabel { font-size: 12px; color: #9fb0c3; }
.lp-form input, .lp-form select { padding: 8px 10px; background: #0e1116;
  color: #d7dee8; border: 1px solid #2a333f; border-radius: 6px;
  font-family: ui-monospace, Consolas, monospace; font-size: 13px; }
.check-row { display: flex; align-items: flex-start; gap: 8px; margin: 8px 0; font-size: 13px; }
.btn { background: #1f6feb; color: #fff; border: none; border-radius: 7px;
  padding: 10px 18px; font-size: 14px; cursor: pointer; }
.btn:hover { background: #2a7bff; }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn-danger { background: #e5534b; color: #fff; border: none; border-radius: 7px;
  padding: 10px 18px; font-size: 14px; cursor: pointer; font-weight: 700; }
.btn-danger:hover { background: #ff6b62; }
.btn-stop { background: #3a1d12; color: #ffb4ad; border: 1px solid #e5534b;
  border-radius: 7px; padding: 9px 18px; font-size: 14px; cursor: pointer; }
.btn-stop:hover { background: #4a2417; }
.errors { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.errors ul { margin: 4px 0 0; padding-left: 18px; }
.caps-line { font-size: 13px; color: #9fb0c3; margin: 8px 0; }
.recap dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; font-size: 13px; }
.recap dt { color: #9fb0c3; }
.phrase-input { font-family: ui-monospace, Consolas, monospace; padding: 10px 12px;
  background: #0e1116; color: #d7dee8; border: 1px solid #2a333f; border-radius: 6px;
  width: 100%; max-width: 320px; }
.log { font-family: ui-monospace, Consolas, Menlo, monospace; font-size: 12px;
  line-height: 1.5; max-height: 320px; overflow-y: auto; white-space: pre-wrap;
  word-break: break-word; }
.log .execline { color: #ff7b72; font-weight: 600; }
.log .dryline { color: #f0b429; }
"""

_PREREQ_LABELS = {
    "keys": "Clés API Kraken configurées",
    "check": "Diagnostic de connexion OK (cette session)",
    "paper": "Paper trading déjà lancé au moins une fois",
}

_PREREQ_REFUSAL_MESSAGES = {
    "keys": "Clés API manquantes. Renseigne .env (voir .env.example) avant le mode live.",
    "check": "Lance le diagnostic (Vérifier la connexion) avant d'armer le réel.",
    "paper": "Lance un paper trading au moins une fois avant le réel.",
}

DEFAULT_FORM_VALUES = {
    "strategy": "sma",
    "symbol": None,     # resolu depuis config.DEFAULT_SYMBOL au rendu
    "timeframe": None,  # resolu depuis config.DEFAULT_TIMEFRAME au rendu
    "stop_loss": "",
    "take_profit": "",
    "trailing_stop": "",
    "position_sizing": "none",
    "target_vol": "",
}


def _esc(s):
    return html.escape("" if s is None else str(s))


# --------------------------------------------------------------------------- #
#  Parsing (aucune I/O) -- meme convention que trading/paper_page.py          #
# --------------------------------------------------------------------------- #
def parse_live_params(fields: dict):
    """
    Valide les champs de config du formulaire /live (strategie/symbole/
    timeframe/risque). Retourne (params, errors) -- fonction PURE. AUCUN
    champ `source` (le live est TOUJOURS Kraken, spec §1.1) et AUCUN plafond
    (les plafonds ne sont JAMAIS des champs de formulaire, N4).
    """
    strategy = (fields.get("strategy") or "").strip().lower()
    errors = []
    if strategy not in STRATEGIES:
        errors.append(f"Stratégie inconnue : {strategy or '(vide)'}.")

    symbol = (fields.get("symbol") or "").strip() or config.DEFAULT_SYMBOL

    timeframe = (fields.get("timeframe") or "").strip() or config.DEFAULT_TIMEFRAME
    if timeframe not in TIMEFRAME_CHOICES:
        errors.append(
            f"Timeframe non supporté : {timeframe} "
            f"(attendu : {', '.join(TIMEFRAME_CHOICES)})."
        )

    risk = parse_risk_fields(fields)

    if errors:
        return None, errors

    params = {"strategy": strategy, "symbol": symbol, "timeframe": timeframe}
    params.update(risk)
    return params, []


def prereq_refusal_message(prereq: dict) -> str:
    """Message(s) FR pour le(s) pre-requis fautif(s) -- reutilise les libelles
    CLI existants quand ils existent (main.py:261 pour les cles). Fonction
    PURE."""
    msgs = [_PREREQ_REFUSAL_MESSAGES[code] for code in prereq.get("missing", [])
           if code in _PREREQ_REFUSAL_MESSAGES]
    return " ".join(msgs) if msgs else "Pré-requis manquant."


# --------------------------------------------------------------------------- #
#  Fragments partages                                                         #
# --------------------------------------------------------------------------- #
def _risk_summary(params) -> str:
    bits = []
    if params.get("stop_loss") is not None:
        bits.append(f"stop {params['stop_loss']:g}%")
    if params.get("take_profit") is not None:
        bits.append(f"objectif {params['take_profit']:g}%")
    if params.get("trailing_stop") is not None:
        bits.append(f"trailing {params['trailing_stop']:g}%")
    if params.get("position_sizing") == "vol":
        tv = params.get("target_vol")
        bits.append(f"sizing vol cible {tv:g}%" if tv is not None else "sizing vol")
    return ", ".join(bits) if bits else "aucun (tout-ou-rien, pas de stop)"


def _plafonds_html() -> str:
    return (
        "<div class='card'><h2>Plafonds (config.py)</h2>"
        f"<p>Ordre max : <strong>{config.MAX_TRADE_VALUE_USD:g} $</strong> | "
        f"Exposition max : <strong>{config.MAX_POSITION_VALUE_USD:g} $</strong> | "
        f"Délai minimum entre ordres : <strong>{config.MIN_TRADE_INTERVAL_SEC:g} s "
        "(1 h)</strong></p>"
        "<p class='muted'>Ces plafonds sont lus de config.py par le process live "
        "lui-même à chaque ordre -- aucun réglage de cet écran ne peut les "
        "dépasser.</p>"
        "</div>"
    )


def _prereq_pastille(ok: bool) -> str:
    return "<span class='ok'>OK</span>" if ok else "<span class='no'>manquant</span>"


def _prereq_html(prereq: dict) -> str:
    missing = set(prereq.get("missing", []))
    rows = []
    for code, label in _PREREQ_LABELS.items():
        rows.append(
            f"<div class='prereq'>{_esc(label)} : {_prereq_pastille(code not in missing)}</div>"
        )
    return "<div class='card'><h2>Pré-requis</h2><div class='prereq-row'>" \
           + "".join(rows) + "</div></div>"


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


def _config_fields_html(prefix, values):
    v = dict(DEFAULT_FORM_VALUES)
    v.update({k: val for k, val in (values or {}).items() if val is not None})
    symbol = v.get("symbol") or config.DEFAULT_SYMBOL
    timeframe = v.get("timeframe") or config.DEFAULT_TIMEFRAME
    vol_checked = " selected" if v.get("position_sizing") == "vol" else ""
    none_checked = " selected" if v.get("position_sizing", "none") != "vol" else ""
    return (
        "<div class='row'>"
        f"<div class='field'><label class='flabel' for='{prefix}_strategy'>Stratégie</label>"
        f"<select id='{prefix}_strategy' name='strategy'>{strategy_options(v.get('strategy'))}</select></div>"
        f"<div class='field'><label class='flabel' for='{prefix}_symbol'>Symbole</label>"
        f"<input id='{prefix}_symbol' name='symbol' value='{_esc(symbol)}'></div>"
        f"<div class='field'><label class='flabel' for='{prefix}_timeframe'>Timeframe</label>"
        f"<select id='{prefix}_timeframe' name='timeframe'>{timeframe_options(timeframe)}</select></div>"
        "</div>"
        "<div class='row'>"
        f"<div class='field'><label class='flabel' for='{prefix}_stop_loss'>Stop (%)</label>"
        f"<input id='{prefix}_stop_loss' name='stop_loss' type='number' step='0.1' "
        f"value='{_esc(v.get('stop_loss'))}' placeholder='(désactivé)'></div>"
        f"<div class='field'><label class='flabel' for='{prefix}_take_profit'>Objectif (%)</label>"
        f"<input id='{prefix}_take_profit' name='take_profit' type='number' step='0.1' "
        f"value='{_esc(v.get('take_profit'))}' placeholder='(désactivé)'></div>"
        f"<div class='field'><label class='flabel' for='{prefix}_trailing_stop'>Trailing (%)</label>"
        f"<input id='{prefix}_trailing_stop' name='trailing_stop' type='number' step='0.1' "
        f"value='{_esc(v.get('trailing_stop'))}' placeholder='(désactivé)'></div>"
        f"<div class='field'><label class='flabel' for='{prefix}_position_sizing'>Sizing</label>"
        f"<select id='{prefix}_position_sizing' name='position_sizing'>"
        f"<option value='none'{none_checked}>none (tout-ou-rien)</option>"
        f"<option value='vol'{vol_checked}>vol (cible de volatilité)</option>"
        "</select></div>"
        f"<div class='field'><label class='flabel' for='{prefix}_target_vol'>Vol cible (%)</label>"
        f"<input id='{prefix}_target_vol' name='target_vol' type='number' step='1' "
        f"value='{_esc(v.get('target_vol'))}' placeholder='si sizing=vol'></div>"
        "</div>"
    )


# --------------------------------------------------------------------------- #
#  Le MUR (GET /live verrouillé, spec §1.1)                                   #
# --------------------------------------------------------------------------- #
def render_live_wall(prereq, keys_ok, check_ok, paper_ever_started, csrf_token,
                     errors=None, values=None) -> str:
    """
    Page complète du mur /live (fonction PURE, testable sans serveur).
    `prereq` = live_control.check_prerequisites_a(...). Deux FORMULAIRES
    SÉPARÉS (jamais un seul bouton générique) :
    - form dry -> POST /live/start, mode=dry, AUCUNE attestation exigée.
    - form réel -> POST /live/arm, mode=reel, 3 attestations, bouton
      DÉSACTIVÉ tant que `prereq["ok"]` est faux (l'état "réel accessible"
      est calculé SERVEUR -- le client ne peut pas l'activer en bricolant
      le HTML, la vraie garde vit côté route /live/arm, N1/N10).
    """
    token = _esc(csrf_token)

    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Action refusée :<ul>{items}</ul></div>"

    banner = (
        "<div class='banner-risk'>ARGENT RÉEL. Pertes possibles jusqu'à la "
        "totalité du capital. Outil sans garantie.</div>"
    )

    mode_display = (
        "<div class='card'><h2>Mode</h2>"
        "<div class='radio-row'>"
        "<label><input type='radio' name='mode_display' value='dry' checked disabled> "
        "Simulation (dry-run) — par défaut</label>"
        "<label><input type='radio' name='mode_display' value='reel' disabled> RÉEL</label>"
        "</div>"
        "<p class='muted'>Décoratif : le mode réel exige toujours le "
        "formulaire « Continuer en RÉEL » ci-dessous, jamais ce sélecteur.</p>"
        "</div>"
    )

    reel_disabled = "" if prereq.get("ok") else " disabled"

    fields = _config_fields_html("dry", values)
    dry_form = (
        "<div class='card'><h2>Démarrer en simulation (dry-run)</h2>"
        "<form class='lp-form' method='post' action='/live/start'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<input type='hidden' name='mode' value='dry'>"
        + fields +
        "<button class='btn' type='submit'>Démarrer en simulation</button>"
        "</form>"
        "<p class='muted caps-line'>Aucun ordre réel n'est jamais envoyé en "
        "simulation.</p>"
        "</div>"
    )

    reel_fields = _config_fields_html("reel", values)
    attest = (
        f"<div class='check-row'><input type='checkbox' id='attest_no_withdraw' "
        "name='attest_no_withdraw' value='1'>"
        "<label for='attest_no_withdraw'>Mes clés n'ont <strong>PAS</strong> le "
        "droit <strong>Withdraw</strong> (Query Funds + Orders seulement).</label></div>"
        "<div class='check-row'><input type='checkbox' id='attest_paper_done' "
        "name='attest_paper_done' value='1'>"
        "<label for='attest_paper_done'>J'ai lancé un paper sur cette config et "
        "compris le risque.</label></div>"
        f"<div class='check-row'><input type='checkbox' id='attest_caps_read' "
        "name='attest_caps_read' value='1'>"
        f"<label for='attest_caps_read'>J'ai lu les plafonds : ordre max "
        f"{config.MAX_TRADE_VALUE_USD:g} $ / position max "
        f"{config.MAX_POSITION_VALUE_USD:g} $.</label></div>"
    )
    reel_form = (
        "<div class='card'><h2>Continuer en RÉEL</h2>"
        "<form class='lp-form' method='post' action='/live/arm'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<input type='hidden' name='mode' value='reel'>"
        + reel_fields
        + attest +
        f"<button class='btn-danger' type='submit'{reel_disabled}>Continuer en RÉEL</button>"
        "</form>"
        "</div>"
    )

    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Live (verrouillé)</h1>"
        "<a class='navlink' href='/'>Accueil</a></div>"
        + banner
        + errors_html
        + _prereq_html(prereq)
        + _plafonds_html()
        + mode_display
        + dry_form
        + reel_form
    )
    return page_shell("Live - InsertYourCoin", "", body, csrf=csrf_token)


# --------------------------------------------------------------------------- #
#  Le RECAP (round-trip 1 réussi, spec §1.3.8)                                #
# --------------------------------------------------------------------------- #
def render_live_recap(params, nonce, csrf_token, attempts_left=None, errors=None) -> str:
    """Écran de récapitulation SERVI PAR LE SERVEUR (pas une modale JS,
    spec §1.3.8). `params` = ceux figés au moment de l'armement (jamais
    resoumis). `errors` réaffiche l'écran après une phrase fausse -- le
    nonce reste valide jusqu'au plafond de tentatives (spec §1.4.5)."""
    token = _esc(csrf_token)
    n = _esc(nonce)
    strat_name = build_strategy(params["strategy"]).name

    attempts_note = ""
    if attempts_left is not None:
        attempts_note = f"<p class='muted'>Tentatives restantes : {attempts_left}.</p>"

    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Refusé :<ul>{items}</ul></div>"

    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Confirmer le RÉEL</h1></div>"
        "<div class='banner-risk'>ARGENT RÉEL. Pertes possibles jusqu'à la "
        "totalité du capital. Outil sans garantie.</div>"
        + errors_html
        + "<div class='card recap'><h2>Récapitulatif</h2>"
        "<dl>"
        f"<dt>Paire</dt><dd>{_esc(params['symbol'])}</dd>"
        f"<dt>Stratégie</dt><dd>{_esc(strat_name)}</dd>"
        f"<dt>Timeframe</dt><dd>{_esc(params['timeframe'])}</dd>"
        f"<dt>Risque</dt><dd>{_esc(_risk_summary(params))}</dd>"
        "</dl>"
        "</div>"
        + _plafonds_html()
        + "<div class='card'>"
        f"<p>Tape exactement <code>{_esc(PHRASE_CONFIRMATION)}</code> pour continuer :</p>"
        + attempts_note
        + "<form method='post' action='/live/start'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        f"<input type='hidden' name='nonce' value='{n}'>"
        "<input type='hidden' name='mode' value='reel'>"
        f"<input class='phrase-input' type='text' name='phrase' autocomplete='off' "
        f"placeholder='{_esc(PHRASE_CONFIRMATION)}'>"
        "<div style='margin-top:12px; display:flex; gap:10px;'>"
        "<button class='btn-danger' type='submit'>DÉMARRER EN RÉEL</button>"
        "<a class='navlink' href='/live'>Annuler</a>"
        "</div>"
        "</form>"
        "</div>"
    )
    return page_shell("Confirmer le réel - InsertYourCoin", "", body, csrf=csrf_token)


# --------------------------------------------------------------------------- #
#  Live EN COURS (GET /live quand un process est détecté, spec §1.6/§4)       #
# --------------------------------------------------------------------------- #
def _log_html(log_lines):
    if not log_lines:
        return "<p class='muted'>Aucune ligne de journal pour l'instant.</p>"
    out = []
    for line in log_lines:
        cls = ""
        if "EXECUTE" in line:
            cls = " class='execline'"
        elif "[DRY-RUN]" in line:
            cls = " class='dryline'"
        out.append(f"<div{cls}>{_esc(line)}</div>")
    return "<div class='log'>" + "".join(out) + "</div>"


def render_live_running(sidecar, pid, start_ts, csrf_token, view=None) -> str:
    """
    Page "live en cours" (spec §1.6/§4) -- lue depuis le SIDECAR serveur
    (jamais déduite d'une donnée cliente, §3.5). Bandeau ROUGE si mode réel,
    SIMULATION (ambre) si dry -- couleur + libellé + position, jamais la
    couleur seule (accessibilité, §4).
    """
    sidecar = sidecar or {}
    mode = sidecar.get("mode")
    view = view or {}
    token = _esc(csrf_token)

    if mode == "reel":
        banner = ("<div class='mode-banner reel'>ARGENT RÉEL — ordres passés</div>")
    else:
        banner = ("<div class='mode-banner dry'>SIMULATION (dry-run) — aucun "
                  "ordre réel</div>")

    since = ""
    if start_ts:
        import datetime as dt
        try:
            since = dt.datetime.fromtimestamp(float(start_ts)).strftime("%Y-%m-%d %H:%M")
        except (OSError, OverflowError, ValueError):
            since = ""

    infos = (
        "<div class='card'><h2>En cours</h2>"
        f"<p>PID {_esc(pid)}{' depuis ' + _esc(since) if since else ''} | "
        f"Stratégie : {_esc(sidecar.get('strategy'))} | "
        f"Paire : {_esc(sidecar.get('symbol'))} ({_esc(sidecar.get('timeframe'))})</p>"
        f"<p>Prix : {_esc(view.get('price'))} | Équity : {_esc(view.get('equity'))} | "
        f"Exposition : {_esc(view.get('exposure'))} | Cycles : {_esc(view.get('n_cycles'))}</p>"
        "</div>"
    )

    stop_card = (
        "<div class='card'>"
        "<form method='post' action='/live/stop'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<button class='btn-stop' type='submit'>Arrêter immédiatement</button>"
        "</form>"
        "<p class='muted caps-line'>Arrête le bot. Ta position ouverte sur "
        "Kraken reste -- gère-la sur Kraken ; le bot ne liquide pas.</p>"
        "</div>"
    )

    journal = (
        "<div class='card'><h2>Journal</h2>"
        + _log_html(view.get("log_lines"))
        + "</div>"
    )

    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Live</h1>"
        "<a class='navlink' href='/'>Accueil</a></div>"
        + banner
        + _plafonds_html()
        + infos
        + stop_card
        + journal
    )
    return page_shell("Live - InsertYourCoin", "", body, csrf=csrf_token)


def render_live_stopped() -> str:
    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Live arrêté</h1></div>"
        "<div class='card'>"
        "<p>Le bot live est arrêté.</p>"
        "<p class='muted'>Ta position ouverte sur Kraken (le cas échéant) "
        "n'est PAS liquidée -- gère-la directement sur Kraken si besoin.</p>"
        "<p><a class='navlink' href='/live'>Retour à /live</a></p>"
        "</div>"
    )
    return page_shell("Live arrêté - InsertYourCoin", "", body)
