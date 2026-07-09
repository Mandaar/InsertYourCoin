"""
Ecran Diagnostic (/check) -- fonctions PURES de rendu (testables sans serveur,
sans reseau). Equivalent web de `python main.py check` (spec §4.2) :
- Installation (versions + etat truststore) : affiche TOUJOURS, aucun reseau.
- Connexion Kraken : seulement sur clic ("Lancer le diagnostic"), formulaire
  GET (lecture seule -> pas de mutation -> pas de jeton CSRF necessaire).
"""
import html

from .webui import page_shell

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
h2 { font-size: 14px; margin: 0 0 10px; color: #9fb0c3; text-transform: uppercase;
  letter-spacing: .5px; }
.muted { color: #6b7787; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.versions { font-family: ui-monospace, Consolas, Menlo, monospace; font-size: 13px;
  line-height: 1.7; white-space: pre-wrap; }
.diag-form { display: flex; gap: 10px; align-items: end; flex-wrap: wrap; margin: 4px 0 14px; }
.diag-form .field { display: flex; flex-direction: column; gap: 4px; }
.diag-form label { font-size: 12px; color: #9fb0c3; }
.diag-form input { padding: 8px 10px; background: #0e1116; color: #d7dee8;
  border: 1px solid #2a333f; border-radius: 6px; font-family: ui-monospace, Consolas, monospace; }
.btn { background: #1f6feb; color: #fff; border: none; border-radius: 7px;
  padding: 9px 18px; font-size: 14px; cursor: pointer; }
.btn:hover { background: #2a7bff; }
.result { border-radius: 8px; padding: 12px 16px; font-weight: 600; }
.result.ok-cat { background: #12331d; border: 1px solid #46c46f; color: #9ff0b8; }
.result.ssl { background: #3a2a12; border: 1px solid #f0b429; color: #ffd98a; }
.result.network { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad; }
.result .msg { font-weight: 400; font-size: 13px; white-space: pre-wrap; margin-top: 8px; }
.neutral { color: #7f8c9c; font-style: italic; }
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
"""


def _esc(s):
    return html.escape("" if s is None else str(s))


def _result_html(result):
    """`result` = dict de diagnostics_web.run_web_check(), ou None si jamais lance."""
    if result is None:
        return "<p class='neutral'>Diagnostic non lance cette session.</p>"
    if result.get("ok"):
        return (
            "<div class='result ok-cat'>Connexion OK -- "
            f"{_esc(result.get('symbol'))} = {_esc(result.get('price'))}"
            f"<div class='msg'>Verifie a {_esc(result.get('time'))}.</div></div>"
        )
    category = result.get("category") or "network"
    return (
        f"<div class='result {_esc(category)}'>Echec de connexion "
        f"[{_esc(category)}]"
        f"<div class='msg'>{_esc(result.get('message'))}</div></div>"
    )


def render_check_page(symbol, static_lines, result=None) -> str:
    """
    Page complete /check (fonction PURE, aucune I/O). `static_lines` = versions
    + etat truststore (diagnostics_web.static_diagnostic_lines(), sans reseau).
    `result` = dict de diagnostics_web.run_web_check() ou None (pas encore lance).
    """
    versions_html = "<div class='versions'>" + "<br>".join(
        _esc(line) for line in static_lines) + "</div>"

    retry_html = ""
    if result is not None and not result.get("ok"):
        retry_html = "<p><a class='navlink' href='/check'>Reessayer</a></p>"

    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Diagnostic</h1>"
        "<a class='navlink' href='/'>&larr; Accueil</a></div>"
        "<div class='card'><h2>Installation</h2>" + versions_html + "</div>"
        "<div class='card'><h2>Connexion Kraken</h2>"
        "<form class='diag-form' method='get' action='/check'>"
        "<input type='hidden' name='run' value='1'>"
        "<div class='field'><label for='symbol'>Symbole</label>"
        f"<input id='symbol' name='symbol' value='{_esc(symbol)}'></div>"
        "<button class='btn' type='submit'>Lancer le diagnostic</button>"
        "</form>"
        + _result_html(result)
        + retry_html +
        "</div>"
    )
    return page_shell("Diagnostic - InsertYourCoin", "check", body)
