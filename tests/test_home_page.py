"""
Tests de l'ecran Accueil (/) -- trading/home_page.py, cibles sur le point
P2-2 de l'audit L0-5 : le lien "passer en live" ne doit JAMAIS pointer vers
une mauvaise destination (ex. /options) sous un libelle qui promet le live.

Lot 8 (docs/design/LOT8_LIVE_SPEC.md §1.0) : /live existe desormais --
"passer en live" est un lien ACTIF, mais DISCRET (pas dans la nav
principale, cf. trading/webui.py NAV_ITEMS/ENABLED_SCREENS ou N7) et pointe
VERS LE MUR VERROUILLE lui-meme (/live), jamais une autre destination.

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


def test_live_link_points_to_live_wall_and_is_discreet():
    """Lot 8 : "passer en live" est desormais un vrai lien, mais UNIQUEMENT
    vers /live (le mur verrouille) -- jamais /options ni une autre route --
    et il n'apparait PAS dans la nav principale (webui.NAV_ITEMS)."""
    out = _render()
    assert "<a class='hublink' href='/live'>passer en live</a>" in out
    # Toujours absent de la nav persistante (N7 -- pas d'onglet /live).
    assert "href='/live'" not in out.split("<div class='hub'>", 1)[0]


def test_help_link_is_active_and_points_to_help_route():
    """Lot 9 : /help existe desormais -- le lien Aide de l'Accueil doit etre
    un vrai lien actif (fini le '<span>Aide (bientot)</span>' du Lot 0)."""
    out = _render()
    assert "<a class='hublink' href='/help'>Aide</a>" in out
    assert "Aide (bientot)" not in out


def test_settings_card_shows_keys_state():
    assert "<span class='ok'>OUI</span>" in _render(keys_ok=True)
    assert "<span class='no'>NON</span>" in _render(keys_ok=False)


def test_home_page_states_the_project_promise_and_its_limit():
    """La promesse du projet (protection, pas de gain, hausses ratees) doit
    etre lisible sur l'Accueil, AVANT les cartes -- ni repliee, ni grisee au
    dela du style '.lede' deja utilise pour le lede de la page (cf. §WHY de
    CLAUDE.md, realigne le 2026-09-02). L'honnetete se verifie sur la partie
    negative (ce que l'outil NE fait PAS), pas seulement la promesse positive."""
    out = _render()
    head, hub = out.split("<div class='hub'>", 1)

    # La promesse positive (protection) est presente...
    assert "protège du pire" in head
    assert "se met en cash" in head
    # ...ET la partie negative (pas de gain / pas un revenu), c'est
    # l'honnetete qu'on teste ici, pas seulement le cote flatteur.
    assert "ne fabrique pas de gain" in head
    assert "pas un revenu" in head
    # ...ET le prix de cette protection (hausses ratees).
    assert "rate une partie des hausses" in head

    # Le message est place AVANT la grille de cartes, pas dedans ni apres.
    assert "protège du pire" not in hub

    # Style : reutilise la classe '.lede' deja existante, aucune nouvelle
    # classe ni couleur en dur pour ce message.
    assert "<p class='lede'>Il protège du pire" in out
