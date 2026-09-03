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

# Tokens consommes depuis trading/webui.py THEME_CSS (3 themes, reagit au
# switch de la nav) -- valeurs alignees sur le design source (Accueil =
# "Session locale", cf. docs/design/from_claude_design/rendered/accueil_*).
_CSS = """
.head { display: flex; justify-content: space-between; align-items: flex-end;
  margin-bottom: 20px; flex-wrap: wrap; gap: 6px; }
.eyebrow { display: flex; align-items: center; gap: 10px; font-size: 10.5px;
  font-weight: 600; letter-spacing: .22em; text-transform: uppercase;
  color: var(--accent-text, var(--gold-bright)); margin-bottom: 12px; }
.eyebrow i { width: 24px; height: 2px; border-radius: 2px;
  background: var(--accent-fill); display: inline-block; }
h1 { font-family: var(--serif); font-size: 34px; font-weight: 400;
  letter-spacing: -.01em; margin: 0 0 6px; color: var(--txt); }
.lede { margin: 0; color: var(--muted); max-width: 56ch; }
.soon-link { color: var(--muted2); font-size: 13px; }
.soon-link .soon { font-family: var(--mono); font-size: 9px;
  letter-spacing: .06em; text-transform: uppercase; margin-left: 5px; padding: 1px 5px;
  border: 1px solid var(--line); border-radius: 999px; color: var(--muted2); vertical-align: 1px; }
h2 { font-size: 11px; margin: 0 0 12px; color: var(--txt); text-transform: uppercase;
  letter-spacing: .16em; font-weight: 600; display: flex; align-items: center; gap: 9px; }
h2 i { width: 7px; height: 7px; border-radius: 2px; background: var(--accent2); flex: 0 0 auto; }
.muted { color: var(--muted); }
.hub { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 18px 20px; }
.card.hero {
  border-color: var(--line-gold); background: var(--panel-grad);
  box-shadow: var(--glow); position: relative; overflow: hidden;
}
.card.hero::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px;
  background: linear-gradient(180deg, var(--accent2), var(--gold), transparent); }
.card.warn-full { grid-column: 1 / -1; border-color: var(--fees-line, var(--warn-fill));
  background: var(--fees-grad); color: var(--txt); display: flex; gap: 14px; align-items: flex-start; }
.card.warn-full .warn-icon { color: var(--warn-fill); font-family: var(--mono); font-size: 17px; }
.ok { color: var(--up); font-weight: 600; }
.no { color: var(--down); font-weight: 600; }
.warn { color: var(--warn-fill); font-weight: 600; }
.hublink { color: var(--blue); text-decoration: none; font-size: 13px; }
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
        "<div class='card'><h2><i></i>Diagnostic</h2>"
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
        "<div class='card hero'><h2><i></i>Paper trading</h2>" + body +
        "<div class='btnrow'><a class='hublink' href='/monitoring'>Voir le monitoring -&gt;</a></div>"
        "</div>"
    )


def _research_card():
    # Lot 4 : le Backtest est construit, mais aucun resultat n'est encore
    # PERSISTE par l'app (pas de "dernier walk-forward" a afficher tant que
    # /research/walkforward n'existe pas, Lot 6) -- etat vide honnete, jamais
    # de faux verdict fabrique.
    return (
        "<div class='card'><h2><i></i>Recherche</h2>"
        "<p class='muted'>Aucune analyse lancée.</p>"
        "<div class='btnrow'><a class='hublink' href='/research/backtest'>"
        "Nouvelle analyse -&gt;</a></div>"
        "</div>"
    )


def _settings_card(keys_ok):
    etat = "<span class='ok'>OUI</span>" if keys_ok else "<span class='no'>NON</span>"
    return (
        "<div class='card'><h2><i></i>Réglages</h2>"
        f"<p>Clés Kraken configurées : {etat}</p>"
        "<div class='btnrow'>"
        "<a class='hublink' href='/options'>Options</a>"
        "<a class='hublink' href='/help'>Aide</a>"
        # Lot 8 (docs/design/LOT8_LIVE_SPEC.md §1.0) : lien DISCRET vers
        # l'ecran verrouille -- /live n'est PAS un onglet de la nav
        # principale (N7) et ce lien est le SEUL point d'entree depuis
        # l'Accueil. La destination est le vrai mur verrouille : aucune
        # action reelle n'est possible sans y repasser toutes les gardes.
        "<a class='hublink' href='/live'>passer en live</a>"
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
        "<div class='head'><div>"
        "<div class='eyebrow'><i></i>Session locale &middot; poste de travail</div>"
        "<h1>État du poste</h1>"
        "<p class='lede'>Rien ne se lance tout seul. Cette page dit ce qui tourne, "
        "ce qui est prêt, et ce qui manque.</p>"
        "<p class='lede'>Il protège du pire : il se met en cash quand le marché "
        "s'effondre. Il ne fabrique pas de gain -- ce n'est pas un revenu. Le prix "
        "de cette protection : il rate une partie des hausses.</p>"
        "</div></div>"
        "<div class='hub'>"
        + _diag_card(check_cache, truststore_ok)
        + _paper_card(paper_view)
        + _research_card()
        + _settings_card(keys_ok)
        + "<div class='card warn-full'><span class='warn-icon'>&#9888;</span>"
          "<p>Avertissement : outil de recherche. "
          "Aucun gain promis. Le live engage de l'argent réel -- il est "
          "verrouillé par défaut.</p></div>"
        + "</div>"
    )
    return page_shell("Accueil - InsertYourCoin", "home", body)
