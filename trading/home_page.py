"""
Ecran Accueil (/) -- hub d'etat (spec §4.1). Fonctions PURES de rendu
(testables sans serveur) : AUCUNE I/O ici, toutes les donnees sont calculees
par l'appelant (trading/monitor.py) et injectees en parametres.

4 zones : Diagnostic / Paper trading / Recherche / Reglages, + bandeau
d'avertissement. Le chargement de cette page NE DECLENCHE JAMAIS d'appel
Kraken (le diagnostic Kraken n'est affiche que si deja lance cette session --
cf. trading/diagnostics_web.run_web_check appele depuis /check).
"""
import html

from .webui import page_shell

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.soon-link { color: #8b97a6; font-size: 13px; }
.soon-link .soon { font-family: ui-monospace, Consolas, Menlo, monospace; font-size: 9px;
  letter-spacing: .06em; text-transform: uppercase; margin-left: 5px; padding: 1px 5px;
  border: 1px solid #232b36; border-radius: 999px; color: #8b97a6; vertical-align: 1px; }
h2 { font-size: 14px; margin: 0 0 10px; color: #9fb0c3; text-transform: uppercase;
  letter-spacing: .5px; }
.muted { color: #8b97a6; }
.hub { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 16px 18px; }
.card.warn-full { grid-column: 1 / -1; border-color: #f0b429; color: #ffd98a; }
.ok { color: #46c46f; font-weight: 600; }
.no { color: #e5534b; font-weight: 600; }
.warn { color: #f0b429; font-weight: 600; }
.hublink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.hublink:hover { text-decoration: underline; }
.btnrow { margin-top: 12px; display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
"""


def _esc(s):
    return html.escape("" if s is None else str(s))


def _diag_card(check_cache, truststore_ok):
    truststore_line = (
        "<span class='ok'>[OK]</span> truststore actif (SSL de l'OS)"
        if truststore_ok else
        "<span class='warn'>[!]</span> truststore indisponible"
    )
    if check_cache is None:
        conn_line = "<span class='muted'>Non vérifié cette session.</span>"
    elif check_cache.get("ok"):
        conn_line = (
            "<span class='ok'>[OK]</span> Connexion Kraken OK "
            f"({_esc(check_cache.get('symbol'))} = {_esc(check_cache.get('price'))}, "
            f"vérifié à {_esc(check_cache.get('time'))})"
        )
    else:
        category = check_cache.get("category") or "network"
        conn_line = f"<span class='no'>[ÉCHEC]</span> Connexion Kraken [{_esc(category)}]"

    return (
        "<div class='card'><h2>Diagnostic</h2>"
        f"<p>{conn_line}</p><p>{truststore_line}</p>"
        "<div class='btnrow'><a class='hublink' href='/check'>Lancer le diagnostic -&gt;</a></div>"
        "</div>"
    )


def _paper_card(paper_view):
    """`paper_view` = dict de monitor.compute_view() (reutilise tel quel)."""
    if not paper_view.get("has_data"):
        body = "<p class='muted'>Aucun paper en cours -- <a class='hublink' " \
               "href='/monitoring'>configurer</a>.</p>"
    else:
        statut = "INACTIF" if paper_view.get("inactif") else paper_view.get("statut")
        pnl = paper_view.get("pnl_total")
        pnl_pct = paper_view.get("pnl_pct") or 0
        pnl_txt = "-" if pnl is None else f"{pnl:,.2f}$ ({pnl_pct*100:+.2f}%)"
        equity = paper_view.get("equity")
        equity_txt = "-" if equity is None else f"{equity:,.2f}$"
        body = (
            f"<p>Statut : <strong>{_esc(statut)}</strong></p>"
            f"<p>Equity {equity_txt}  (P&amp;L {pnl_txt})</p>"
        )
    return (
        "<div class='card'><h2>Paper trading</h2>" + body +
        "<div class='btnrow'><a class='hublink' href='/monitoring'>Voir le monitoring -&gt;</a></div>"
        "</div>"
    )


def _research_card():
    # Lot 4 : le Backtest est construit, mais aucun resultat n'est encore
    # PERSISTE par l'app (pas de "dernier walk-forward" a afficher tant que
    # /research/walkforward n'existe pas, Lot 6) -- etat vide honnete, jamais
    # de faux verdict fabrique.
    return (
        "<div class='card'><h2>Recherche</h2>"
        "<p class='muted'>Aucune analyse lancée.</p>"
        "<div class='btnrow'><a class='hublink' href='/research/backtest'>"
        "Nouvelle analyse -&gt;</a></div>"
        "</div>"
    )


def _settings_card(keys_ok):
    etat = "<span class='ok'>OUI</span>" if keys_ok else "<span class='no'>NON</span>"
    return (
        "<div class='card'><h2>Réglages</h2>"
        f"<p>Clés Kraken configurées : {etat}</p>"
        "<div class='btnrow'>"
        "<a class='hublink' href='/options'>Options</a>"
        "<a class='hublink' href='/help'>Aide</a>"
        "<span class='soon-link'>passer en live"
        "<span class='soon'>bientôt</span></span>"
        "</div></div>"
    )


def render_home_page(paper_view, check_cache, keys_ok, truststore_ok) -> str:
    """
    Page complete Accueil (fonction PURE, aucune I/O). `paper_view` = sortie de
    monitor.compute_view() ; `check_cache` = dernier dict de
    diagnostics_web.run_web_check() (ou None) ; `keys_ok` = options.keys_configured() ;
    `truststore_ok` = diagnostics_web.truststore_active().
    """
    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Accueil</h1></div>"
        "<div class='hub'>"
        + _diag_card(check_cache, truststore_ok)
        + _paper_card(paper_view)
        + _research_card()
        + _settings_card(keys_ok)
        + "<div class='card warn-full'>Avertissement : outil de recherche. "
          "Aucun gain promis. Le live engage de l'argent réel -- il est "
          "verrouillé par défaut.</div>"
        + "</div>"
    )
    return page_shell("Accueil - InsertYourCoin", "home", body)
