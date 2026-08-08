"""
Tests de l'ecran Aide (/help) -- trading/help_page.py (Lot 9, spec §4.14).

Fonction PURE, sans I/O, sans parametre : le rendu ne peut varier -- on
verifie donc son contenu directement (workflow honnete, SSL, non-conseil,
lien SETUP.md) et sa coquille commune (nav avec "Aide" actif).
"""
from trading.help_page import render_help_page


def test_render_help_page_has_common_shell():
    out = render_help_page()
    assert "<nav class='nav'>" in out
    assert "class='tab active' href='/help'>Aide</a>" in out


def test_render_help_page_shows_honest_workflow_order():
    """spec §4.14 : ordre de travail honnete backtest -> walk-forward -> paper
    -> live, dans cet ordre exact dans le HTML."""
    out = render_help_page()
    i_bt = out.index("Backtest / Comparer")
    i_wf = out.index("Walk-forward")
    i_paper = out.index("Paper trading")
    i_live = out.index("<strong>Live</strong>")
    assert i_bt < i_wf < i_paper < i_live


def test_render_help_page_reminds_ssl_truststore_and_never_disable():
    out = render_help_page()
    assert "truststore" in out
    assert "Ne jamais désactiver" in out
    assert "config.VERIFY_SSL" in out


def test_render_help_page_has_risk_disclaimer():
    out = render_help_page()
    assert "pas un conseil en investissement" in out.lower() \
        or "conseil en investissement" in out.lower()
    assert "Aucune promesse" in out or "aucune promesse" in out.lower()


def test_render_help_page_links_to_setup_md():
    out = render_help_page()
    assert "SETUP.md" in out


def test_render_help_page_is_pure_no_args():
    """Page statique (spec §4.14) : deux appels sans parametre rendent un
    contenu identique, aucun etat lu."""
    assert render_help_page() == render_help_page()
