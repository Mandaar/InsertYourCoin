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

#  Charte graphique (docs/design/CLAUDE_DESIGN_BRIEF.md §5 A1) : AUCUNE couleur
#  en dur -- tout vient des variables de theme injectees globalement par
#  webui.page_shell (THEME_CSS x3 themes, meme <html>). Les anciennes valeurs
#  hex de ce bloc (heritees d'avant la migration -- meme constat sur
#  trading/live_page.py) sont remplacees par leur token exact quand il existe
#  (#171c24->--panel, #232b36->--line, #0e1116->--bg, #d7dee8->--txt,
#  #46c46f->--up, #e5534b->--down, #6cb6ff->--blue, #8b97a6/#9fb0c3->--muted2
#  -- verifie >=4.5:1 sur bg ET panel dans les 3 themes, meme garantie que le
#  commentaire de webui.THEME_CSS). Le bouton primaire recoit --accent-fill/
#  --on-accent (paire deja utilisee par le design de reference pour "Demarrer
#  le paper", contraste mini calcule 5.36:1 sur les 3 themes). Les blocs
#  d'alerte (--down) restent en TRAIT + texte colore sur fond transparent
#  (meme idiome que "Redemarrer le serveur" du design de reference) plutot
#  qu'un fond teinte : un fond teinte a 10% avec texte --down est passe SOUS
#  4.5:1 en theme sombre une fois compose sur --panel (mesure : 4.15:1),
#  le trait+transparent, lui, reste >=4.5:1 dans les 3 themes (down vs bg
#  5.11-5.68, down vs panel 4.62-6.22, up vs bg/panel 6.0-9.58 -- calcule via
#  scripts/_contrast_check.py sur docs/design/from_claude_design/_themes_dump.json).
_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
h2 { font-size: 14px; margin: 0 0 10px; color: var(--muted2); text-transform: uppercase;
  letter-spacing: .5px; }
.muted { color: var(--muted2); }
.navlink { color: var(--blue); text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.statut-line { font-size: 15px; }
.ok { color: var(--up); }
.no { color: var(--down); }

/* Regroupement par NATURE de decision (design brief §3.4a) : "Marche" = CE
   qui est trade et COMMENT les ordres partent ; "Risque" = QUAND on sort.
   Pas de nouvelle couleur, juste un intitule au-dessus de chaque rangee. */
.group-label { font-size: 11px; color: var(--muted2); text-transform: uppercase;
  letter-spacing: .6px; margin: 12px 0 4px; }
.group-label:first-child { margin-top: 0; }

.pp-form .row { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 14px; }
.pp-form .field { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.pp-form label.flabel { font-size: 12px; color: var(--muted2); }
.pp-form input, .pp-form select { padding: 8px 10px; background: var(--bg);
  color: var(--txt); border: 1px solid var(--line); border-radius: 6px;
  font-family: var(--mono); font-size: 13px; min-height: 40px; }
.btn { background: var(--accent-fill); color: var(--on-accent); border: none;
  border-radius: 10px; padding: 0 18px; min-height: 44px; font-size: 14px;
  font-weight: 600; cursor: pointer; }
.btn:hover { filter: brightness(1.08); }
.btn-stop { background: transparent; color: var(--down); border: 1px solid var(--down);
  border-radius: 10px; padding: 0 18px; min-height: 44px; font-size: 14px;
  font-weight: 600; cursor: pointer; }
.btn-stop:hover { filter: brightness(1.15); }
.errors { background: transparent; border: 1px solid var(--down); color: var(--down);
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.errors ul { margin: 4px 0 0; padding-left: 18px; }
.saved { background: transparent; border: 1px solid var(--up); color: var(--up);
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-weight: 600; }
.alert { background: transparent; border: 1px solid var(--down); color: var(--down);
  border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; font-weight: 600; }
.honesty { font-size: 12px; color: var(--muted2); line-height: 1.6; }
.reset-row { align-items: center; margin: 4px 0 6px; }
.check-inline { display: flex; align-items: center; gap: 6px; font-size: 13px;
  color: var(--txt); cursor: pointer; }
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
    "order_type": "market",
}

# Libelles NON techniques (l'utilisateur a explicitement demande d'eviter le
# jargon "maker/taker") pour les 2 seuls types d'ordre de config.ORDER_TYPES.
# Le compromis (parfois plus cher mais garanti, vs. moins cher mais peut ne
# jamais s'executer) est ecrit dans le libelle lui-meme, pas cache dans une
# infobulle -- c'est le fait qui compte pour decider.
_ORDER_TYPE_LABELS = {
    "market": "Ordre au marché — part tout de suite, frais 0,80 %",
    "limit": "Ordre à prix fixé — moins cher (0,40 %), mais peut ne jamais s'exécuter",
}


def _esc(s):
    return html.escape("" if s is None else str(s))


def paper_control_disabled(env_value) -> bool:
    """
    Parse IYC_DISABLE_PAPER_CONTROL (deploiement Docker multi-conteneurs ou
    paper et monitor sont deux conteneurs SEPARES partageant un volume --
    docs/DEPLOY_DOCKER.md §7). Fonction PURE, testable sans os.environ.

    Absent/vide -> False : comportement LOCAL (mono-machine, Lot 7)
    STRICTEMENT INCHANGE. "1"/"true"/"yes" (insensible a la casse, espaces
    tolerees) -> True : le formulaire Demarrer et le bouton Arreter de /paper
    sont retires cote rendu, ET tout POST /paper (start OU stop) est refuse
    cote serveur (trading/monitor.py::_paper_post) AVANT toute decision de
    spawn/terminate -- un POST forge ne peut rien declencher, le controle
    n'est pas seulement une absence de bouton en HTML.
    """
    return (env_value or "").strip().lower() in ("1", "true", "yes")


_DISABLED_NOTICE_HTML = (
    "<div class='card'><h2>Pilotage</h2>"
    "<p class='muted'>Pilotage désactivé en déploiement conteneurisé — "
    "gère le paper via <code>docker compose ... restart/stop/logs paper</code> "
    "(voir README / DEPLOY_DOCKER.md §7).</p></div>"
)


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
        errors.append(f"Stratégie inconnue : {strategy or '(vide)'}.")

    symbol = (fields.get("symbol") or "").strip() or config.DEFAULT_SYMBOL

    timeframe = (fields.get("timeframe") or "").strip() or "5m"
    if timeframe not in TIMEFRAME_CHOICES:
        errors.append(
            f"Timeframe non supporté : {timeframe} "
            f"(attendu : {', '.join(TIMEFRAME_CHOICES)})."
        )

    risk = parse_risk_fields(fields)  # reutilise trading/research_page.py

    order_type = (fields.get("order_type") or "market").strip().lower()
    if order_type not in config.ORDER_TYPES:
        errors.append(
            f"Type d'ordre inconnu : {order_type or '(vide)'} "
            f"(attendu : {', '.join(config.ORDER_TYPES)})."
        )

    # Remise a zero (--reset) : n'a de sens qu'au demarrage. Case a cocher
    # ('1' si cochee, meme convention que trading/live_control.ATTESTATION_
    # FIELDS) + confirmation EXPLICITE distincte -- sans elle, "reset" coche
    # seul est REJETE (jamais transmis tel quel a la commande construite).
    # Contrairement au mur du live (2 round-trips + nonce + phrase), une
    # simple case suffit ici : le geste est deja non destructif (archivage).
    reset_wanted = (fields.get("reset") or "").strip() == "1"
    reset_confirmed = (fields.get("reset_confirm") or "").strip() == "1"
    if reset_wanted and not reset_confirmed:
        errors.append(
            "Remise à zéro demandée sans confirmation : coche aussi "
            "« Je confirme » pour repartir de zéro."
        )

    if errors:
        return None, errors

    params = {"strategy": strategy, "symbol": symbol, "timeframe": timeframe}
    params.update(risk)
    params["order_type"] = order_type
    params["reset"] = reset_wanted
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


def order_type_options(selected):
    opts = []
    for key in config.ORDER_TYPES:
        checked = " selected" if key == selected else ""
        label = _ORDER_TYPE_LABELS.get(key, key)
        opts.append(f"<option value='{_esc(key)}'{checked}>{_esc(label)}</option>")
    return "".join(opts)


def _form_html(csrf_token, values) -> str:
    v = dict(DEFAULT_FORM_VALUES)
    v.update({k: val for k, val in (values or {}).items() if val is not None})
    symbol = v.get("symbol") or config.DEFAULT_SYMBOL
    timeframe = v.get("timeframe") or "5m"
    vol_checked = " selected" if v.get("position_sizing") == "vol" else ""
    none_checked = " selected" if v.get("position_sizing", "none") != "vol" else ""
    token = _esc(csrf_token)

    reset_checked = " checked" if v.get("reset") == "1" else ""
    reset_confirm_checked = " checked" if v.get("reset_confirm") == "1" else ""

    return (
        "<form class='pp-form' method='post' action='/paper'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<input type='hidden' name='action' value='start'>"

        # Groupe "Marche" (design brief §3.4a) : CE qui est trade (strategie,
        # symbole, timeframe) et COMMENT les ordres partent (type d'ordre) --
        # ce sont les memes decisions "avant de trader", donc la meme rangee.
        "<p class='group-label'>Marché</p>"
        "<div class='row'>"
        "<div class='field'><label class='flabel' for='strategy'>Stratégie</label>"
        f"<select id='strategy' name='strategy'>{strategy_options(v.get('strategy'))}</select></div>"
        "<div class='field'><label class='flabel' for='symbol'>Symbole</label>"
        f"<input id='symbol' name='symbol' value='{_esc(symbol)}'></div>"
        "<div class='field'><label class='flabel' for='timeframe'>Timeframe</label>"
        f"<select id='timeframe' name='timeframe'>{timeframe_options(timeframe)}</select></div>"
        "<div class='field'><label class='flabel' for='order_type'>Type d'ordre</label>"
        f"<select id='order_type' name='order_type'>{order_type_options(v.get('order_type'))}</select></div>"
        "</div>"
        "<p class='muted honesty'>L'ordre au marché part à coup sûr mais coûte plus cher "
        "(0,80 %). L'ordre à prix fixé coûte moins cher (0,40 %) mais peut ne jamais "
        "s'exécuter — le cycle suivant redécide.</p>"

        # Groupe "Risque" (design brief §3.4a) : QUAND on sort de la position.
        "<p class='group-label'>Risque</p>"
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

        # Remise a zero : n'a de sens qu'AU DEMARRAGE -- groupe distinct, ni
        # "Marché" ni "Risque". Case a cocher + confirmation EXPLICITE
        # distincte (label 'for' apparie, comme le reste du formulaire).
        "<p class='group-label'>Au démarrage</p>"
        "<div class='row reset-row'>"
        f"<label class='check-inline' for='reset'>"
        f"<input type='checkbox' id='reset' name='reset' value='1'{reset_checked}> "
        "Repartir de zéro</label>"
        f"<label class='check-inline' for='reset_confirm'>"
        f"<input type='checkbox' id='reset_confirm' name='reset_confirm' value='1'"
        f"{reset_confirm_checked}> Je confirme</label>"
        "</div>"
        "<p class='muted honesty'>Repartir de zéro archive l'historique actuel "
        "(paper_state.json, paper_stats.csv — renommés avec un horodatage, rien n'est "
        "supprimé) puis recrée un état neuf. Ne prend effet qu'au prochain démarrage.</p>"

        "<button class='btn' type='submit'>Démarrer le paper trading</button>"
        "</form>"
    )


def _stop_form_html(csrf_token) -> str:
    token = _esc(csrf_token)
    return (
        "<form method='post' action='/paper' style='display:inline-block;margin-right:10px'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<input type='hidden' name='action' value='stop'>"
        "<button class='btn-stop' type='submit'>Arrêter</button>"
        "</form>"
    )


def render_paper_page(status, csrf_token, errors=None, values=None,
                      message=None, inactif=False, age_seconds=None,
                      control_disabled=False) -> str:
    """
    Page complete GET/POST /paper (fonction PURE, testable sans serveur).
    `status` = compute_paper_status(...). `errors`/`values` re-affichent le
    formulaire apres un POST invalide (meme convention que research_page).
    `message` = bandeau de confirmation (demarre/arrete). `inactif`/`age_seconds`
    = alerte reprise de trading/monitor.py compute_view (>360s sans cycle).

    `control_disabled` (IYC_DISABLE_PAPER_CONTROL, deploiement Docker
    multi-conteneurs, cf. paper_control_disabled ci-dessus) : quand True, le
    formulaire Demarrer et le bouton Arreter sont RETIRES du rendu (statut
    reste consultable en lecture seule) et remplaces par un encart explicatif.
    Ne change RIEN d'autre (monitoring, recherche, options, live inchanges).
    """
    errors_html = ""
    if errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in errors)
        errors_html = f"<div class='errors'>Action refusée :<ul>{items}</ul></div>"

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
        control_html = "" if control_disabled else _stop_form_html(csrf_token)
        status_card = (
            "<div class='card'><h2>Statut</h2>"
            f"<p class='statut-line'>Statut : <strong class='ok'>EN COURS</strong> "
            f"depuis {since}</p>"
            + inactif_html
            + control_html
            + "<a class='navlink' href='/monitoring'>Voir le monitoring &rarr;</a>"
            "</div>"
            + (_DISABLED_NOTICE_HTML if control_disabled else "")
            + "<p class='muted honesty'>Démarrer/arrêter ne touche pas à "
            "l'historique accumulé : paper_stats.csv et paper_trades.log "
            "continuent d'exister, et reprennent au prochain démarrage.</p>"
        )
    elif control_disabled:
        status_card = (
            "<div class='card'><h2>Statut</h2>"
            "<p class='statut-line'>Statut : <strong class='no'>ARRÊTÉ</strong></p>"
            "</div>"
            + _DISABLED_NOTICE_HTML
        )
    else:
        status_card = (
            "<div class='card'><h2>Statut</h2>"
            "<p class='statut-line'>Statut : <strong class='no'>ARRÊTÉ</strong></p>"
            "</div>"
            "<div class='card'>" + _form_html(csrf_token, values) + "</div>"
            "<p class='muted honesty'>Aucune clé Kraken requise (le paper "
            "n'utilise que des données publiques et de l'argent fictif). "
            "L'historique existant (paper_stats.csv) est conservé et "
            "continuera de grandir au démarrage.</p>"
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
