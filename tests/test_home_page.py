"""
Tests de l'ecran Accueil (/) -- trading/home_page.py, cibles sur le point
P2-2 de l'audit L0-5 : le lien "passer en live" ne doit JAMAIS pointer vers
une mauvaise destination (ex. /options) sous un libelle qui promet le live.

Fonctions PURES : aucun reseau, `render_home_page` prend toutes ses donnees
en parametres (paper_view/check_cache/keys_ok/truststore_ok).
"""
from trading.home_page import render_home_page

_EMPTY_PAPER_VIEW = {"has_data": False}


def _render(keys_ok=False):
    return render_home_page(_EMPTY_PAPER_VIEW, None, keys_ok, True)


def test_live_link_is_not_an_active_anchor_to_options():
    """P2-2 (audit L0-5) : avant le fix, deux <a> differents pointaient tous
    les deux vers /options, dont un libelle "passer en live (verrouille)" --
    lien actif menant a une mauvaise destination sous un libelle sensible.
    Desormais AUCUN <a href='/options'> ne doit porter le mot "live"."""
    out = _render()
    assert "<a class='hublink' href='/options'>live" not in out.lower()
    for line in out.split("<a "):
        if "href='/options'" in line and "live" in line.lower():
            raise AssertionError(f"lien actif vers /options avec le mot 'live' : {line[:80]!r}")


def test_live_mention_is_disabled_not_a_live_link():
    """Le concept "live" reste visible (transparence) mais SANS lien actif --
    meme patron que le reste de l'app pour le "pas encore livre" (span
    disabled + badge, jamais un <a> vers une destination arbitraire)."""
    out = _render()
    assert "passer en live" in out
    assert "<span class='soon-link'>passer en live" in out
    assert "<span class='soon'>bientôt</span>" in out


def test_help_link_is_active_and_points_to_help_route():
    """Lot 9 : /help existe desormais -- le lien Aide de l'Accueil doit etre
    un vrai lien actif (fini le '<span>Aide (bientot)</span>' du Lot 0)."""
    out = _render()
    assert "<a class='hublink' href='/help'>Aide</a>" in out
    assert "Aide (bientot)" not in out


def test_settings_card_shows_keys_state():
    assert "<span class='ok'>OUI</span>" in _render(keys_ok=True)
    assert "<span class='no'>NON</span>" in _render(keys_ok=False)
