"""
Socle web partage (Lot 0) : theme CSS commun + coquille de navigation persistante
+ service de fichiers statiques vendorises (Chart.js, etc.).

STDLIB UNIQUEMENT (comme monitor.py). Fonctions PURES et testables sans serveur :
- THEME_CSS       : variables + nav, source de verite unique du theme visuel.
- page_shell(...) : enveloppe toute page (nav + <html>/<head>/<body>).
- serve_static(...) : resout un chemin sous trading/static/ pour la route
  GET /static/<fichier>, avec garde anti path-traversal.

Ancrage design : direction visuelle validee dans docs/mockups/prototype.html
(memes variables CSS, meme nav) et docs/UI_UX_WEBAPP_SPEC.md §3.1/§7.1.

Perimetre Lot 0 (cf. docs/UI_UX_WEBAPP_SPEC.md §9) : seuls Monitoring et Options
sont des ecrans construits/branches. Les autres items de la nav (Accueil,
Diagnostic, Recherche, Paper, Stats, Aide) apparaissent DESACTIVES ("bientot") --
jamais de lien mort. Ils seront actives lot par lot.

Perimetre Lot 1 (bascule de route decidee §11.1) : Accueil (/) et Diagnostic
(/check) sont actives. Le monitoring quitte "/" pour "/monitoring" (nav +
routing dans trading/monitor.py) ; /fragment est inchange.
"""
import html
from pathlib import Path

import config

# --------------------------------------------------------------------------- #
#  Theme CSS partage (variables + nav persistante)                            #
# --------------------------------------------------------------------------- #
THEME_CSS = """
:root{
  --bg:#0e1116; --bg-deep:#0a0c10; --panel:#171c24; --panel2:#1b212b;
  --line:#232b36; --line-gold:rgba(214,170,90,.22);
  --txt:#d7dee8; --muted:#7f8c9c; --muted2:#6b7787;
  --gold:#d6aa5a; --gold-bright:#f0b429; --gold-soft:rgba(214,170,90,.10);
  --up:#46c46f; --down:#e5534b; --blue:#6cb6ff;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;
  --mono:ui-monospace,"SF Mono",Consolas,"Liberation Mono",Menlo,monospace;
  --sans:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0}
body{
  background:
    radial-gradient(1100px 560px at 82% -12%, rgba(214,170,90,.06), transparent 60%),
    radial-gradient(820px 460px at -8% 112%, rgba(70,196,111,.04), transparent 60%),
    var(--bg);
  color:var(--txt); font-family:var(--sans); -webkit-font-smoothing:antialiased;
  line-height:1.5; padding:0;
}
.nav{
  position:sticky; top:0; z-index:50;
  display:flex; align-items:center; gap:4px; flex-wrap:wrap;
  padding:0 22px; min-height:56px;
  background:rgba(11,13,17,.94); backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);
}
.nav .brand{
  font-family:var(--serif); font-weight:700; font-size:18px;
  letter-spacing:-.01em; color:var(--txt); margin-right:14px; white-space:nowrap;
  padding:10px 0;
}
.nav .brand .coin{color:var(--gold)}
.nav .tabs{display:flex; gap:2px; flex-wrap:wrap}
.nav a.tab{
  display:inline-block; color:var(--muted); font-family:var(--sans); font-size:13.5px;
  text-decoration:none; padding:8px 12px; border-radius:7px; letter-spacing:.01em;
}
.nav a.tab:hover{color:var(--txt); background:rgba(255,255,255,.04)}
.nav a.tab.active{color:var(--gold); background:var(--gold-soft); font-weight:600}
.nav span.tab.disabled{
  display:inline-block; color:var(--muted2); font-family:var(--sans); font-size:13.5px;
  padding:8px 12px; border-radius:7px; letter-spacing:.01em; cursor:default; opacity:.55;
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
.iyc-page{max-width:1160px; margin:0 auto}
"""


# --------------------------------------------------------------------------- #
#  Navigation persistante (spec §3.1)                                         #
# --------------------------------------------------------------------------- #
# (cle, libelle, href) -- ordre = sitemap docs/UI_UX_WEBAPP_SPEC.md §3.
NAV_ITEMS = (
    ("home", "Accueil", "/"),
    ("check", "Diagnostic", "/check"),
    ("research", "Recherche", "/research"),
    ("paper", "Paper", "/paper"),
    ("monitoring", "Monitoring", "/monitoring"),
    ("stats", "Stats", "/stats"),
    ("options", "Options", "/options"),
    ("help", "Aide", "/help"),
)

# Ecrans REELLEMENT construits et branches. Tenu a jour lot par lot -- c'est la
# seule ligne a etendre quand un nouvel ecran passe en prod.
ENABLED_SCREENS = frozenset({"home", "check", "monitoring", "options", "stats"})


def _esc(s):
    return html.escape("" if s is None else str(s))


def _render_nav(active_nav):
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
                "<span class='soon'>bientot</span></span>"
            )

    ssl_on = bool(getattr(config, "VERIFY_SSL", False))
    ssl_pill = (
        "<span class='pill ssl-ok'><span class='dot'></span>SSL verif. actif</span>"
        if ssl_on else
        "<span class='pill ssl-bad'>SSL VERIF. DESACTIVEE</span>"
    )

    return (
        "<nav class='nav'>"
        "<div class='brand'>Insert<span class='coin'>Your</span>Coin</div>"
        "<div class='tabs'>" + "".join(tabs) + "</div>"
        "<div class='spacer'></div>"
        "<div class='status'>"
        "<span class='pill'><span class='dot'></span>Local 127.0.0.1</span>"
        + ssl_pill +
        "</div>"
        "</nav>"
    )


def page_shell(title, active_nav, body_html, csrf=None):
    """
    Enveloppe commune de toute page : <!DOCTYPE>/<head>/<style THEME_CSS> + nav
    persistante (item `active_nav` surligne) + `body_html` (deja rendu par la
    page appelante -- qui peut embarquer son propre <style> de contenu, cf.
    monitor.py `_CSS` / `_OPTIONS_CSS`).

    `csrf` n'est utilise par AUCUN element de la coquille elle-meme (aucun
    formulaire au niveau nav) : parametre reserve pour une future action
    globale (ex. bouton d'arret rapide du paper) sans devoir changer cette
    signature partout ou elle est deja appelee.
    """
    return (
        "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(title)}</title>"
        f"<style>{THEME_CSS}</style></head><body>"
        + _render_nav(active_nav)
        + "<div class='iyc-page'>"
        + body_html
        + "</div></body></html>"
    )


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
