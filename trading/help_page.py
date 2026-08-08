"""
Ecran Aide (/help) -- fonction PURE de rendu (testable sans serveur, sans
reseau, sans lecture fichier), cf. docs/UI_UX_WEBAPP_SPEC.md §4.14.

Contenu (spec §4.14 + audit Lot 9, priorite 6) : ordre de travail honnete
(backtest -> walk-forward -> paper -> live), rappel SSL/antivirus
(truststore), rappel "ne jamais desactiver VERIFY_SSL", encart
risque/non-conseil, lien vers SETUP.md complet.

Securite : page STATIQUE, aucune donnee sensible, aucun etat lu -- ne
depend d'aucun parametre (contrairement aux autres ecrans, qui recoivent
tous leur etat de trading/monitor.py).
"""
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
.workflow { list-style: none; margin: 0; padding: 0; counter-reset: wf; }
.workflow li { counter-increment: wf; padding: 8px 0 8px 34px; position: relative;
  border-bottom: 1px solid #232b36; }
.workflow li:last-child { border-bottom: none; }
.workflow li::before { content: counter(wf); position: absolute; left: 0; top: 8px;
  width: 22px; height: 22px; border-radius: 50%; background: #d6aa5a; color: #171c24;
  font-weight: 700; font-size: 12px; display: flex; align-items: center;
  justify-content: center; }
.workflow strong { color: #d7dee8; }
.ssl-ok { color: #46c46f; font-weight: 600; }
.warn-full { border-color: #f0b429; color: #ffd98a; }
.risk-card { border-color: #e5534b; }
.risk-card h2 { color: #ffb4ad; }
code { background: #0e1116; border: 1px solid #232b36; border-radius: 4px;
  padding: 1px 5px; font-family: ui-monospace, Consolas, Menlo, monospace; }
"""


def render_help_page() -> str:
    """
    Page complete /help (fonction PURE, aucune I/O, aucun parametre --
    contenu entierement statique).
    """
    body = (
        f"<style>{_CSS}</style>"
        "<div class='head'><h1>Aide</h1>"
        "<a class='navlink' href='/'>&larr; Accueil</a></div>"

        "<div class='card'><h2>Ordre de travail recommandé (toujours dans cet ordre)</h2>"
        "<ol class='workflow'>"
        "<li><strong>Backtest / Comparer</strong> -- éliminer ce qui ne marche "
        "manifestement pas, sur les données déjà vues (IN-SAMPLE).</li>"
        "<li><strong>Walk-forward</strong> (le juge) -- ne garder que ce qui tient "
        "hors-échantillon, sur un holdout jamais vu pendant l'optimisation.</li>"
        "<li><strong>Paper trading</strong> -- faire tourner en réel avec de "
        "l'argent fictif, plusieurs semaines, avant tout engagement réel.</li>"
        "<li><strong>Live</strong> -- seulement après, petits montants, "
        "garde-fous serrés (<code>config.py</code>), verrouillé par défaut.</li>"
        "</ol></div>"

        "<div class='card'><h2>SSL / antivirus</h2>"
        "<p>Beaucoup d'antivirus (Avast, AVG, Kaspersky, ESET, Bitdefender...) et "
        "les proxys d'entreprise interceptent le HTTPS : ils re-signent les "
        "certificats avec leur propre autorité racine, absente du bundle de "
        "certificats de Python. Sans rien faire, la connexion à Kraken échoue "
        "en <code>CERTIFICATE_VERIFY_FAILED</code>.</p>"
        "<p><span class='ssl-ok'>Solution déjà en place</span> : le paquet "
        "<code>truststore</code> fait utiliser le magasin de certificats de "
        "l'OS (où la racine de l'antivirus est déjà approuvée) -- "
        "<strong>sans désactiver la vérification SSL</strong>.</p>"
        "<p class='muted'><strong>Ne jamais désactiver "
        "<code>config.VERIFY_SSL</code></strong> : il reste <code>True</code> "
        "sur cette machine, en toute circonstance. Le diagnostic "
        "(<a class='navlink' href='/check'>page Diagnostic</a>) confirme l'état "
        "réel de la connexion.</p></div>"

        "<div class='card risk-card'><h2>Risque -- ce n'est pas un conseil en investissement</h2>"
        "<p>Cet outil sert à <strong>rechercher et tester</strong> des stratégies, "
        "pas à garantir un gain. Le walk-forward (hors-échantillon) est le seul "
        "juge honnête d'une stratégie -- jamais le backtest seul. Aucune promesse "
        "de rendement régulier ni garanti. Décisions et risque appartiennent à "
        "l'utilisateur.</p></div>"

        "<div class='card'><h2>Guide complet</h2>"
        "<p>Installation détaillée, clés API (sans droit de retrait), lancement "
        "en un double-clic, sécurité git : voir "
        "<code>SETUP.md</code> à la racine du projet.</p></div>"
    )
    return page_shell("Aide - InsertYourCoin", "help", body)
