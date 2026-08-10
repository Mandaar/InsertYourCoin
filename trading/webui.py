"""
Socle web partage (Lot 0, reskin design Claude Design) : theme CSS commun (3
themes) + coquille de navigation persistante + service de fichiers statiques
vendorises (Chart.js, etc.).

STDLIB UNIQUEMENT (comme monitor.py). Fonctions PURES et testables sans serveur :
- THEME_CSS       : variables + nav, source de verite unique du theme visuel.
- page_shell(...) : enveloppe toute page (nav + <html>/<head>/<body>).
- serve_static(...) : resout un chemin sous trading/static/ pour la route
  GET /static/<fichier>, avec garde anti path-traversal.

Ancrage design : extraction fidele du site produit par Claude Design --
docs/design/from_claude_design/InsertYourCoin_v3.dc.html (source figee) +
docs/design/from_claude_design/rendered/ (48 rendus : 16 ecrans/etats x 3
themes, produits en EXECUTANT le vrai JS source, cf.
scripts/extract_claude_design.cjs). Les valeurs de THEME_CSS ci-dessous sont
generees depuis ce meme JS (scripts/_gen_theme_css.py, sur
docs/design/from_claude_design/_themes_dump.json) -- pas retapees a la main.

Contrat de retro-compatibilite (tests/test_webui.py) : `:root{}` (non
qualifie) reste l'UNIQUE bloc portant --bg/--panel/--muted2 en HEX PLAT (regex
`_css_var`), et les selecteurs `.nav`/`.tab`/`.pill`/`.research-subnav`
existants sont CONSERVES (memes classes, memes hrefs) -- seules leurs VALEURS
changent pour consommer les tokens du design. Les 2 themes additionnels
("Nuit"/violet, "Clair"/light) arrivent en `:root[data-theme="..."]`, qui ne
matche PAS la sous-chaine litterale `:root{` (donc `out.count(":root{")`
reste a 1, cf. tests/test_report_page.py).

Perimetre Lot 1 (bascule de route decidee §11.1) : Accueil (/) et Diagnostic
(/check) sont actives. Le monitoring quitte "/" pour "/monitoring" (nav +
routing dans trading/monitor.py) ; /fragment est inchange.
"""
import html
import json
from pathlib import Path

import config
from . import options as _options

# --------------------------------------------------------------------------- #
#  Theme CSS partage (variables x3 themes + nav persistante + switch)         #
# --------------------------------------------------------------------------- #
#
# Genere par scripts/_gen_theme_css.py depuis
# docs/design/from_claude_design/_themes_dump.json (valeurs REELLEMENT
# calculees par le JS source du design, cf. scripts/extract_claude_design.cjs
# -- pas une recopie a la main). --muted2 est la SEULE valeur ajoutee
# manuellement (absente du design, contrat historique de contraste AA
# tests/test_webui.py) ; calculee et verifiee >=4.5:1 sur bg ET panel par
# scripts/_contrast_check.py (dark = valeur existante inchangee, violet/light
# = meme methode : blend muted->txt).
THEME_CSS = """
:root{
  --bg:#0e1116; --bg-deep:#0a0c10; --panel:#171c24; --panel2:#1b212b;
  --line:#232b36; --line-gold:rgba(224,138,60,.34);
  --txt:#d7dee8; --muted:#7f8c9c; --muted2:#8b97a6;
  --gold:#d6aa5a; --gold-bright:#f0b429; --gold-soft:rgba(214,170,90,.12);
  --up:#46c46f; --down:#e5534b; --blue:#6cb6ff;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;
  --mono:ui-monospace,"SF Mono",Consolas,"Liberation Mono",Menlo,monospace;
  --sans:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --panel-grad:linear-gradient(180deg,#1b212b,#171c24);
  --accent-ink:#d6aa5a; --on-accent:#1a140a; --accent-text:#f0b429;
  --logo-glow:drop-shadow(0 0.375rem 0.875rem rgba(214,170,90,.35)); --logo-ink:#f3ece0;
  --pill-fill:linear-gradient(120deg,#e08a3c,#d6aa5a);
  --warn-fill:#f0b429; --warn-big:#f0b429;
  --accent-fill:linear-gradient(120deg,#e08a3c,#d6aa5a);
  --warn:#f0b429; --on-danger:#ffffff; --accent2:#e08a3c; --accent2-soft:rgba(224,138,60,.14);
  --nav-bg:rgba(11,13,17,.94);
  --fees-grad:linear-gradient(180deg,rgba(240,180,41,.13),#171c24);
  --fees-line:rgba(240,180,41,.38);
  --shadow:0 1.125rem 2.5rem -1.75rem rgba(0,0,0,.85);
  --glow:0 1.125rem 2.5rem -1.75rem rgba(0,0,0,.85);
  --track:rgba(255,255,255,.022);
  --page-bg:radial-gradient(68.75rem 35rem at 82% -12%, rgba(214,170,90,.07), transparent 60%),radial-gradient(51.25rem 28.75rem at -8% 112%, rgba(70,196,111,.045), transparent 60%),#0e1116;
}
:root[data-theme="violet"]{
  --bg:#0b0a14; --bg-deep:#08070f; --panel:#141223; --panel2:#1a1734;
  --line:#2a2545; --line-gold:rgba(167,139,250,.34);
  --txt:#e7e4f6; --muted:#9a94b8; --muted2:#a59fc1;
  --gold:#a78bfa; --gold-bright:#c4b5fd; --gold-soft:rgba(167,139,250,.12);
  --up:#34d399; --down:#f04438; --blue:#67e8f9;
  --panel-grad:linear-gradient(180deg,#1a1734,#141223);
  --accent-ink:#a78bfa; --on-accent:#12101f; --accent-text:#c4b5fd;
  --logo-glow:drop-shadow(0 0.375rem 0.875rem rgba(167,139,250,.45)); --logo-ink:#e7e4f6;
  --pill-fill:linear-gradient(120deg,#e879f9,#a78bfa);
  --warn-fill:#fbbf24; --warn-big:#fbbf24;
  --accent-fill:linear-gradient(120deg,#e879f9,#a78bfa);
  --warn:#fbbf24; --on-danger:#ffffff; --accent2:#e879f9; --accent2-soft:rgba(232,121,249,.14);
  --nav-bg:rgba(9,8,18,.90);
  --fees-grad:linear-gradient(180deg,rgba(251,191,36,.13),#141223);
  --fees-line:rgba(251,191,36,.38);
  --shadow:0 1.5rem 3.75rem -2.125rem rgba(124,58,237,.75);
  --glow:0 0 0 1px rgba(167,139,250,.18), 0 1.5rem 3.75rem -2.125rem rgba(124,58,237,.8);
  --track:rgba(255,255,255,.03);
  --page-bg:radial-gradient(56.25rem 31.25rem at 80% -12%, rgba(167,139,250,.18), transparent 62%),radial-gradient(45rem 26.25rem at -6% 112%, rgba(52,211,153,.09), transparent 60%),#0b0a14;
}
:root[data-theme="light"]{
  --bg:#f2f5f7; --bg-deep:#eaeff3; --panel:#ffffff; --panel2:#ffffff;
  --line:#dde4ea; --line-gold:rgba(15,118,110,.35);
  --txt:#0f1720; --muted:#55606d; --muted2:#4b5662;
  --gold:#0b5f59; --gold-bright:#0f766e; --gold-soft:rgba(15,118,110,.10);
  --up:#116b3e; --down:#c1121f; --blue:#0d6ea8;
  --panel-grad:linear-gradient(180deg,#ffffff,#f5f9fa);
  --accent-ink:#0f766e; --on-accent:#ffffff; --accent-text:#0b5f59;
  --logo-glow:drop-shadow(0 0.375rem 0.875rem rgba(15,118,110,.28)); --logo-ink:#333333;
  --pill-fill:linear-gradient(120deg,#0e7490,#0f766e);
  --warn-fill:#dfa316; --warn-big:#dfa316;
  --accent-fill:linear-gradient(120deg,#0e7490,#0f766e);
  --warn:#c08c0c; --on-danger:#ffffff; --accent2:#0e7490; --accent2-soft:rgba(14,116,144,.10);
  --nav-bg:rgba(255,255,255,.92);
  --fees-grad:linear-gradient(180deg,rgba(223,163,22,.16),#ffffff);
  --fees-line:rgba(223,163,22,.48);
  --shadow:0 1.25rem 2.75rem -2rem rgba(15,30,45,.4);
  --glow:0 1.25rem 2.75rem -2rem rgba(15,30,45,.45);
  --track:rgba(15,23,32,.03);
  --page-bg:radial-gradient(68.75rem 35rem at 82% -12%, rgba(15,118,110,.10), transparent 60%),radial-gradient(51.25rem 28.75rem at -8% 112%, rgba(52,211,153,.10), transparent 60%),#f2f5f7;
}
*{box-sizing:border-box}
html,body{margin:0}
body{
  background:var(--page-bg);
  color:var(--txt); font-family:var(--sans); -webkit-font-smoothing:antialiased;
  line-height:1.5; padding:0;
}
a{color:var(--blue); text-decoration:none}
a:hover{color:var(--gold-bright)}
*:focus-visible{outline:2px solid var(--gold-bright); outline-offset:2px}
@keyframes iyc-pulse { 0%{ r:4; opacity:.55 } 70%{ r:13; opacity:0 } 100%{ r:13; opacity:0 } }
.nav{
  position:sticky; top:0; z-index:50;
  display:flex; align-items:center; gap:4px; flex-wrap:wrap;
  padding:0 22px; min-height:56px;
  background:var(--nav-bg); backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);
}
.nav .brand{
  display:inline-flex; align-items:center; gap:11px;
  font-family:var(--serif); font-weight:400; font-size:19px;
  letter-spacing:-.01em; color:var(--txt); margin-right:14px; white-space:nowrap;
  padding:10px 0;
}
.nav .brand svg{ width:34px; height:34px; display:block; filter:var(--logo-glow); flex:0 0 auto }
.nav .brand .coin{color:var(--accent2)}
.nav .tabs{display:flex; gap:2px; flex-wrap:wrap}
.nav a.tab{
  display:inline-block; color:var(--muted); font-family:var(--sans); font-size:13.5px;
  text-decoration:none; padding:8px 12px; border-radius:7px; letter-spacing:.01em;
}
.nav a.tab:hover{color:var(--txt); background:rgba(255,255,255,.04)}
.nav a.tab.active{color:var(--gold); background:var(--gold-soft); font-weight:600;
  box-shadow:inset 0 -2px 0 var(--accent2)}
.nav span.tab.disabled{
  display:inline-block; color:var(--muted2); font-family:var(--sans); font-size:13.5px;
  padding:8px 12px; border-radius:7px; letter-spacing:.01em; cursor:default;
}
.nav .tab .soon{font-family:var(--mono); font-size:9px; letter-spacing:.06em;
  text-transform:uppercase; margin-left:6px; padding:1px 5px; border:1px solid var(--line);
  border-radius:999px; color:var(--muted2); vertical-align:1px}
.nav .spacer{flex:1}
.nav .status{display:flex; gap:8px; align-items:center; padding:10px 0}
.pill{
  display:inline-flex; align-items:center; gap:6px; font-family:var(--mono);
  font-size:11.5px; color:var(--muted); border:1px solid var(--line);
  border-radius:999px; padding:4px 10px; white-space:nowrap;
}
.pill .dot{width:7px; height:7px; border-radius:50%; background:var(--up);
  box-shadow:0 0 6px rgba(70,196,111,.6)}
.pill.ssl-ok{color:var(--up); border-color:rgba(70,196,111,.35)}
.pill.ssl-bad{color:var(--down); border-color:rgba(229,83,75,.45)}
.theme-switch{display:inline-flex; border:1px solid var(--line); border-radius:999px;
  overflow:hidden}
.theme-switch form{margin:0}
.theme-switch button{cursor:pointer; border:none; padding:6px 11px; font-size:11.5px;
  font-family:var(--sans); display:inline-flex; align-items:center; gap:6px;
  background:transparent; font-weight:400; color:var(--txt)}
.theme-switch button.active{background:var(--accent-fill); font-weight:600; color:var(--on-accent)}
.theme-switch .dot{width:8px; height:8px; border-radius:999px; display:inline-block}
.iyc-page{max-width:1160px; margin:0 auto}
.research-subnav{display:flex; gap:4px; flex-wrap:wrap; margin-bottom:16px;
  padding-bottom:10px; border-bottom:1px solid var(--line)}
.research-subnav a.sub-tab{color:var(--muted); font-size:12.5px; text-decoration:none;
  padding:6px 11px; border-radius:6px}
.research-subnav a.sub-tab:hover{color:var(--txt); background:rgba(255,255,255,.04)}
.research-subnav a.sub-tab.active{color:var(--gold); background:var(--gold-soft); font-weight:600}
.research-subnav span.sub-tab.disabled{color:var(--muted2); font-size:12.5px;
  padding:6px 11px; border-radius:6px}
.research-subnav .soon{font-family:var(--mono); font-size:9px; letter-spacing:.06em;
  text-transform:uppercase; margin-left:5px; padding:1px 5px; border:1px solid var(--line);
  border-radius:999px; color:var(--muted2); vertical-align:1px}
"""


# --------------------------------------------------------------------------- #
#  Navigation persistante (spec §3.1)                                         #
# --------------------------------------------------------------------------- #
# (cle, libelle, href) -- ordre = sitemap docs/UI_UX_WEBAPP_SPEC.md §3.
NAV_ITEMS = (
    ("home", "Accueil", "/"),
    ("check", "Diagnostic", "/check"),
    # Depuis le Lot 6, les 5 ecrans de "Recherche" (backtest/compare/optimize/
    # portfolio/walkforward) sont tous construits/branches -- la nav pointe
    # directement vers Backtest (premier onglet de la sous-nav Recherche)
    # plutot qu'un hub separe.
    ("research", "Recherche", "/research/backtest"),
    ("paper", "Paper", "/paper"),
    ("monitoring", "Monitoring", "/monitoring"),
    ("stats", "Stats", "/stats"),
    ("options", "Options", "/options"),
    ("help", "Aide", "/help"),
)

# Ecrans REELLEMENT construits et branches. Tenu a jour lot par lot -- c'est la
# seule ligne a etendre quand un nouvel ecran passe en prod.
ENABLED_SCREENS = frozenset(
    {"home", "check", "research", "paper", "monitoring", "options", "stats", "help"}
)

# Sous-navigation DANS la section Recherche (Lot 5 : compare/optimize/portfolio
# rejoignent backtest ; Lot 6 : walkforward rejoint aussi le groupe -- tous les
# ecrans de /research/<type> sont desormais construits/branches). Affichee en
# haut de chaque ecran (research_page.py, compare_page.py, optimize_page.py,
# portfolio_page.py, walkforward_page.py) -- meme convention "bientot" que
# NAV_ITEMS/ENABLED_SCREENS pour tout futur ecran desactive (jamais un <a> mort).
RESEARCH_SUBNAV = (
    ("backtest", "Backtest", "/research/backtest", True),
    ("compare", "Comparer", "/research/compare", True),
    ("optimize", "Optimiser", "/research/optimize", True),
    ("portfolio", "Portefeuille", "/research/portfolio", True),
    ("walkforward", "Walk-forward", "/research/walkforward", True),
)

# Themes disponibles pour le switch nav (spec brief : Nuit/Ambre/Clair) --
# (id, libelle, couleur du point -- reprend exactement themeBtns du design
# source, docs/design/from_claude_design/InsertYourCoin_v3.dc.html ligne ~1092).
THEME_BUTTONS = (
    ("violet", "Nuit", "#a78bfa"),
    ("dark", "Ambre", "#d6aa5a"),
    ("light", "Clair", "#0f766e"),
)

# Logo -- reprend le mark SVG du design (cercle + eclair + icone piece), fills
# en var(--token) : il change de couleur avec le theme sans logique Python.
_LOGO_SVG = (
    "<svg viewBox='0 0 48 48' aria-hidden='true'>"
    "<defs><linearGradient id='logoG' gradientUnits='userSpaceOnUse' x1='6' y1='6' x2='42' y2='42'>"
    "<stop offset='0%' style='stop-color:var(--accent2)'></stop>"
    "<stop offset='100%' style='stop-color:var(--gold)'></stop>"
    "</linearGradient></defs>"
    "<circle cx='24' cy='24' r='22' fill='url(#logoG)' opacity='.10'></circle>"
    "<circle cx='24' cy='24' r='22' fill='none' stroke='url(#logoG)' stroke-width='2.6'></circle>"
    "<circle cx='24' cy='24' r='17.6' fill='none' stroke='url(#logoG)' stroke-width='1' opacity='.45'></circle>"
    "<clipPath id='logoClip'><circle cx='24' cy='24' r='17.6'></circle></clipPath>"
    "<g clip-path='url(#logoClip)'>"
    "<path d='M0,0 L24,24 L48,0' fill='none' stroke='url(#logoG)' stroke-width='8' stroke-linejoin='miter'></path>"
    "<path d='M24,22 L24,48' fill='none' stroke='url(#logoG)' stroke-width='8'></path>"
    "<rect x='12.4' y='25.9' width='2.2' height='8.4' rx='1.1' fill='var(--logo-ink)'></rect>"
    "<rect x='10.6' y='25.9' width='5.8' height='1.8' rx='.9' fill='var(--logo-ink)'></rect>"
    "<rect x='10.6' y='32.5' width='5.8' height='1.8' rx='.9' fill='var(--logo-ink)'></rect>"
    "<path d='M37.71,27.94 A3.05,3.05 0 1 0 37.71,32.26' fill='none' stroke='var(--logo-ink)' "
    "stroke-width='1.8' stroke-linecap='round'></path>"
    "</g></svg>"
)


def research_subnav_html(active_key):
    """Fragment HTML de sous-nav Recherche (fonction PURE). `active_key` =
    cle RESEARCH_SUBNAV active (surlignee)."""
    items = []
    for key, label, href, enabled in RESEARCH_SUBNAV:
        if enabled:
            cls = "sub-tab active" if key == active_key else "sub-tab"
            items.append(f"<a class='{cls}' href='{_esc(href)}'>{_esc(label)}</a>")
        else:
            items.append(
                f"<span class='sub-tab disabled'>{_esc(label)}"
                "<span class='soon'>bientôt</span></span>"
            )
    return "<div class='research-subnav'>" + "".join(items) + "</div>"


def _esc(s):
    return html.escape("" if s is None else str(s))


def _current_theme():
    """Theme visuel courant persiste (options.json), fonction PURE de
    lecture-seule cote fichier (meme precedent que _render_nav qui lit deja
    config.VERIFY_SSL -- page_shell n'est pas une fonction "pure" au sens
    strict depuis toujours, elle lit deja de l'etat global)."""
    try:
        return _options.read_options().get("theme", "dark")
    except Exception:
        return "dark"


def _theme_switch_html(current_theme, csrf_token):
    """3 mini-formulaires POST /theme (fonctionne SANS JavaScript -- vrai
    POST/redirect/GET). csrf_token peut etre vide (page rendue hors serveur,
    ex. tests unitaires) : le bouton reste visible mais la soumission
    echouera cote serveur (CSRF invalide), jamais un lien mort silencieux."""
    token = _esc(csrf_token or "")
    items = []
    for tid, label, dot in THEME_BUTTONS:
        active = " active" if tid == current_theme else ""
        items.append(
            "<form method='post' action='/theme'>"
            f"<input type='hidden' name='theme' value='{tid}'>"
            f"<input type='hidden' name='csrf_token' value='{token}'>"
            f"<button type='submit' class='theme-btn{active}'>"
            f"<i class='dot' style='background:{dot}'></i>{_esc(label)}</button>"
            "</form>"
        )
    return "<div class='theme-switch'>" + "".join(items) + "</div>"


def _render_nav(active_nav, current_theme="dark", csrf_token=None):
    """Construit la barre de nav persistante. `active_nav` = cle NAV_ITEMS active
    (surlignee en accent or). Les ecrans hors ENABLED_SCREENS sont rendus en
    <span> desactive avec un badge "bientot" -- jamais un <a> (pas de lien mort)."""
    tabs = []
    for key, label, href in NAV_ITEMS:
        if key in ENABLED_SCREENS:
            cls = "tab active" if key == active_nav else "tab"
            tabs.append(f"<a class='{cls}' href='{_esc(href)}'>{_esc(label)}</a>")
        else:
            tabs.append(
                f"<span class='tab disabled'>{_esc(label)}"
                "<span class='soon'>bientôt</span></span>"
            )

    ssl_on = bool(getattr(config, "VERIFY_SSL", False))
    ssl_pill = (
        "<span class='pill ssl-ok'><span class='dot'></span>SSL vérif. actif</span>"
        if ssl_on else
        "<span class='pill ssl-bad'>SSL VÉRIF. DÉSACTIVÉE</span>"
    )

    return (
        "<nav class='nav'>"
        f"<a class='brand' href='/'>{_LOGO_SVG}<span>Insert<span class='coin'>Your</span>Coin</span></a>"
        "<div class='tabs'>" + "".join(tabs) + "</div>"
        "<div class='spacer'></div>"
        "<div class='status'>"
        "<span class='pill'><span class='dot'></span>Local 127.0.0.1</span>"
        + ssl_pill
        + _theme_switch_html(current_theme, csrf_token) +
        "</div>"
        "</nav>"
    )


def page_shell(title, active_nav, body_html, csrf=None):
    """
    Enveloppe commune de toute page : <!DOCTYPE>/<head>/<style THEME_CSS> + nav
    persistante (item `active_nav` surligne, switch de theme 3 boutons) +
    `body_html` (deja rendu par la page appelante -- qui peut embarquer son
    propre <style> de contenu, cf. monitor.py `_CSS` / `_OPTIONS_CSS`).

    `csrf` alimente les mini-formulaires du switch de theme (nav) -- utilise
    en PRIORITE si fourni par l'appelant (deja le cas pour live_page/
    paper_page/options), SINON repli sur `config._RUNTIME_CSRF_TOKEN` (le
    jeton unique du serveur en cours, pose par trading/monitor.py au demarrage
    -- meme jeton que tous les autres formulaires de l'app, donc valide pour
    /theme). Absent des deux (tests unitaires hors serveur) -> bouton rendu,
    soumission simplement refusee cote serveur (jamais un lien mort muet).
    """
    token = csrf if csrf is not None else getattr(config, "_RUNTIME_CSRF_TOKEN", None)
    theme = _current_theme()
    return (
        "<!DOCTYPE html><html lang='fr' data-theme='" + _esc(theme) + "'>"
        "<head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(title)}</title>"
        f"<style>{THEME_CSS}</style></head><body>"
        + _render_nav(active_nav, theme, token)
        + "<div class='iyc-page'>"
        + body_html
        + "</div></body></html>"
    )


# --------------------------------------------------------------------------- #
#  Panneau de job asynchrone (Lot 3) -- reutilisable par les futures pages   #
#  de recherche (Lots 4-6 : backtest/compare/optimize/walkforward/portfolio) #
#                                                                             #
#  `job_panel_html(job_id, csrf_token, ...)` est une fonction PURE (aucun    #
#  reseau, aucun etat) qui rend un fragment HTML autonome : barre de         #
#  progression indeterminee, log live (meme esprit visuel que `.log` du     #
#  monitor, cf. trading/monitor.py), bouton Annuler (POST CSRF). Le JS       #
#  embarque fait un polling GET /job/<id>/status (~1.2s, sans dependance     #
#  externe) et, a l'etat 'done', redirige vers `result_url` si fourni --     #
#  les Lots 4-6 la cablent vers /report/<id> ou la vue dediee ; le Lot 3 ne  #
#  connait encore aucune de ces vues, `result_url` reste optionnel.          #
# --------------------------------------------------------------------------- #
JOB_PANEL_CSS = """
.job-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 16px; margin: 14px 0; }
.job-panel .job-bar { position: relative; height: 6px; border-radius: 999px;
  background: var(--bg); overflow: hidden; margin-bottom: 10px; }
.job-panel .job-bar-fill { position: absolute; top: 0; left: 0; height: 100%;
  width: 35%; border-radius: 999px; background: var(--gold); }
.job-panel .job-bar.indeterminate .job-bar-fill {
  animation: job-bar-slide 1.1s ease-in-out infinite; }
@keyframes job-bar-slide {
  0% { left: -35%; width: 35%; }
  50% { left: 40%; width: 45%; }
  100% { left: 100%; width: 35%; }
}
.job-panel .job-state { font-size: 13px; margin-bottom: 8px; }
.job-panel .job-state.state-error { color: var(--down); }
.job-panel .job-state.state-done { color: var(--up); }
.job-panel .job-state.state-cancelled { color: var(--gold-bright); }
.job-panel .job-log { font-family: var(--mono);
  font-size: 12px; line-height: 1.5; max-height: 260px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-word; background: var(--bg);
  border-radius: 6px; padding: 8px 10px; margin-bottom: 10px; }
.job-panel .job-cancel { margin: 0; }
.job-panel .btn-cancel { background: #3a1d12; color: #ffb4ad;
  border: 1px solid var(--down); border-radius: 7px; padding: 7px 16px;
  font-size: 13px; cursor: pointer; }
.job-panel .btn-cancel:hover { background: #4a2417; }
.job-panel .btn-cancel:disabled { opacity: .5; cursor: default; }
"""

_JOB_STATE_LABELS = {
    "pending": "En attente...",
    "running": "En cours...",
    "done": "Terminé.",
    "error": "Erreur.",
    "cancelled": "Annulé.",
}

_JOB_JS_TEMPLATE = """
<script>
(function(){
  var panel = document.getElementById(__PANEL_ID__);
  if(!panel){ return; }
  var statusUrl = __STATUS_URL__;
  var cancelUrl = __CANCEL_URL__;
  var resultUrl = panel.getAttribute('data-result-url');
  var stateEl = panel.querySelector('.job-state');
  var logEl = panel.querySelector('.job-log');
  var barEl = panel.querySelector('.job-bar');
  var cancelForm = panel.querySelector('.job-cancel');
  var cancelBtn = panel.querySelector('.btn-cancel');
  var labels = __STATE_LABELS__;
  var timer = null;

  function render(st){
    var label = labels[st.state] || st.state;
    stateEl.textContent = label + (st.error_message ? (' ' + st.error_message) : '');
    stateEl.className = 'job-state state-' + st.state;
    logEl.textContent = (st.log || []).join('\\n');
    logEl.scrollTop = logEl.scrollHeight;
    var terminal = (st.state === 'done' || st.state === 'error' || st.state === 'cancelled');
    if(terminal){
      barEl.classList.remove('indeterminate');
      if(cancelBtn){ cancelBtn.disabled = true; }
      if(timer){ clearInterval(timer); timer = null; }
      if(st.state === 'done' && st.has_result && resultUrl){
        window.location.href = resultUrl;
      }
    } else {
      barEl.classList.add('indeterminate');
    }
  }

  function poll(){
    fetch(statusUrl, {cache: 'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(st){ if(st){ render(st); } })
      .catch(function(){});
  }

  if(cancelForm){
    cancelForm.addEventListener('submit', function(ev){
      ev.preventDefault();
      var data = new URLSearchParams(new FormData(cancelForm));
      fetch(cancelUrl, {method: 'POST', body: data})
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(st){ if(st){ render(st); } })
        .catch(function(){});
    });
  }

  poll();
  timer = setInterval(poll, 1200);
})();
</script>
"""


def job_panel_html(job_id, csrf_token, result_url=None):
    """
    Panneau de progression reutilisable pour un job asynchrone (Lot 3+).
    Fonction PURE (le rendu ne fait aucun reseau : c'est le JS embarque, cote
    navigateur, qui poll). `job_id` et `csrf_token` sont echappes HTML par
    prudence (defense en profondeur -- la route serveur valide deja le
    format du job_id, cf. trading/monitor.py _JOB_STATUS_RE/_JOB_CANCEL_RE).
    """
    jid = _esc(job_id)            # pour les attributs HTML (id, data-*, action=)
    token = _esc(csrf_token)
    target = _esc(result_url) if result_url else ""
    raw_id = str(job_id)          # pour les URLs JS (echappees JS via json.dumps, pas HTML)
    panel = (
        f"<div class='job-panel' id='job-panel-{jid}' data-job-id='{jid}' "
        f"data-result-url='{target}'>"
        "<div class='job-bar indeterminate'><div class='job-bar-fill'></div></div>"
        "<div class='job-state'>En attente...</div>"
        "<div class='job-log'></div>"
        f"<form class='job-cancel' method='post' action='/job/{jid}/cancel'>"
        f"<input type='hidden' name='csrf_token' value='{token}'>"
        "<button class='btn-cancel' type='submit'>Annuler</button>"
        "</form>"
        "</div>"
    )
    js = (
        _JOB_JS_TEMPLATE
        .replace("__PANEL_ID__", json.dumps("job-panel-" + jid))
        .replace("__STATUS_URL__", json.dumps(f"/job/{raw_id}/status"))
        .replace("__CANCEL_URL__", json.dumps(f"/job/{raw_id}/cancel"))
        .replace("__STATE_LABELS__", json.dumps(_JOB_STATE_LABELS, ensure_ascii=False))
    )
    return panel + js


# --------------------------------------------------------------------------- #
#  Fichiers statiques vendorises (Chart.js, etc.) -- route GET /static/<...>  #
# --------------------------------------------------------------------------- #
STATIC_DIR = Path(__file__).resolve().parent / "static"

_MIME_TYPES = {
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def serve_static(rel_path):
    """
    Resout `rel_path` sous STATIC_DIR pour la route GET /static/<rel_path>.
    Retourne (bytes, content_type) ou None si absent/invalide.

    Anti path-traversal (double garde) : refuse tout segment '..' AVANT
    resolution, PUIS verifie que le chemin resolu reste bien sous STATIC_DIR
    (protege aussi contre les liens symboliques qui sortiraient du dossier).
    """
    if not rel_path:
        return None
    if ".." in Path(rel_path).parts:
        return None
    try:
        base = STATIC_DIR.resolve()
        candidate = (base / rel_path).resolve()
        candidate.relative_to(base)
    except (ValueError, OSError):
        return None
    if not candidate.is_file():
        return None
    ext = candidate.suffix.lower()
    content_type = _MIME_TYPES.get(ext, "application/octet-stream")
    try:
        return candidate.read_bytes(), content_type
    except OSError:
        return None
