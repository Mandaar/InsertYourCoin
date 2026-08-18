"""
Tests du socle web partage (Lot 0) : trading/webui.py.

Fonctions PURES, sans serveur ni reseau (l'integration serveur reelle est
couverte par tests/test_monitor_server.py pour la route /static/).
"""
import re

from trading import webui


# --------------------------------------------------------------------------- #
#  Contraste WCAG (P2-4, audit L0-5) -- ratio CALCULE (formule de luminance   #
#  relative officielle), jamais estime a l'oeil. Les couleurs sont EXTRAITES  #
#  du THEME_CSS reel (pas recopiees a la main) : le test re-teste la source.  #
# --------------------------------------------------------------------------- #
def _css_var(name):
    m = re.search(r"--" + re.escape(name) + r":\s*(#[0-9a-fA-F]{6})", webui.THEME_CSS)
    assert m, f"variable CSS --{name} introuvable dans THEME_CSS"
    return m.group(1)


def _luminance(hexcolor):
    hexcolor = hexcolor.lstrip("#")
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))

    def lin(c):
        cs = c / 255
        return cs / 12.92 if cs <= 0.03928 else ((cs + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast_ratio(c1, c2):
    l1, l2 = _luminance(c1), _luminance(c2)
    l1, l2 = max(l1, l2), min(l1, l2)
    return (l1 + 0.05) / (l2 + 0.05)


def test_muted2_reaches_aa_normal_text_on_bg_and_panel():
    """P2-4 : --muted2 echouait AA (4.15:1 sur --bg, 3.76:1 sur --panel, seuil
    4.5:1). Verifie le ratio REEL calcule depuis le THEME_CSS courant, sur les
    DEUX fonds ou il est utilise (nav + panneaux)."""
    muted2 = _css_var("muted2")
    bg = _css_var("bg")
    panel = _css_var("panel")
    ratio_bg = _contrast_ratio(muted2, bg)
    ratio_panel = _contrast_ratio(muted2, panel)
    assert ratio_bg >= 4.5, f"--muted2 vs --bg = {ratio_bg:.2f}:1 (< 4.5 requis)"
    assert ratio_panel >= 4.5, f"--muted2 vs --panel = {ratio_panel:.2f}:1 (< 4.5 requis, le pire cas)"


def test_disabled_nav_items_no_longer_dim_muted2_with_opacity():
    """P2-4 : l'opacity:.55 sur les elements nav desactives faisait tomber le
    rendu REEL a ~2.08:1 (bien pire que --muted2 seul). Non-regression :
    aucune regle de nav/sous-nav desactivee ne doit plus reduire l'opacite
    d'un texte porteur de sens."""
    assert "span.tab.disabled{" in webui.THEME_CSS
    disabled_block = webui.THEME_CSS.split("span.tab.disabled{", 1)[1].split("}", 1)[0]
    assert "opacity" not in disabled_block
    assert "span.sub-tab.disabled{" in webui.THEME_CSS
    sub_disabled_block = webui.THEME_CSS.split("span.sub-tab.disabled{", 1)[1].split("}", 1)[0]
    assert "opacity" not in sub_disabled_block


# --------------------------------------------------------------------------- #
#  page_shell / nav                                                           #
# --------------------------------------------------------------------------- #
def test_page_shell_contains_nav_and_theme():
    out = webui.page_shell("Titre - test", "monitoring", "<p>contenu</p>")
    assert "<nav class='nav'>" in out
    assert "InsertYourCoin" in out.replace("<span class='coin'>Your</span>", "Your")
    assert "Titre - test" in out
    assert "<p>contenu</p>" in out
    assert "Local 127.0.0.1" in out


def test_page_shell_highlights_active_item():
    # Lot 1 : le monitoring a quitte "/" pour "/monitoring" (bascule §11.1).
    out = webui.page_shell("T", "monitoring", "<p>x</p>")
    assert "class='tab active' href='/monitoring'>Monitoring</a>" in out
    # L'item Options (actif mais pas courant) reste un lien cliquable, non surligne.
    assert "class='tab' href='/options'>Options</a>" in out


def test_page_shell_disabled_items_are_not_links_and_marked_bientot():
    out = webui.page_shell("T", "monitoring", "<p>x</p>")
    for key, label, href in webui.NAV_ITEMS:
        if key in webui.ENABLED_SCREENS:
            continue
        # Pas de lien mort : ces items sont des <span> desactives, jamais un <a href=...>.
        assert f"<span class='tab disabled'>{label}" in out
        assert f"href='{href}'>{label}</a>" not in out
    assert out.count("bientot") == len(webui.NAV_ITEMS) - len(webui.ENABLED_SCREENS)


def test_page_shell_ssl_indicator_reflects_config(monkeypatch):
    monkeypatch.setattr(webui.config, "VERIFY_SSL", True, raising=False)
    out_on = webui.page_shell("T", "options", "<p>x</p>")
    assert "ssl-ok" in out_on
    assert "SSL VÉRIF. DÉSACTIVÉE" not in out_on

    monkeypatch.setattr(webui.config, "VERIFY_SSL", False, raising=False)
    out_off = webui.page_shell("T", "options", "<p>x</p>")
    assert "ssl-bad" in out_off
    assert "SSL VÉRIF. DÉSACTIVÉE" in out_off


# --------------------------------------------------------------------------- #
#  Switch de theme (reskin design Claude Design -- Nuit/Ambre/Clair)          #
# --------------------------------------------------------------------------- #
def test_page_shell_default_theme_is_dark_ambre(tmp_path, monkeypatch):
    # Pas d'options.json -> defaut "dark" (Ambre), continuite du theme historique.
    monkeypatch.setattr(webui._options, "OPTIONS_PATH", lambda: tmp_path / "nope.json")
    out = webui.page_shell("T", "options", "<p>x</p>")
    assert "data-theme='dark'" in out


def test_page_shell_reflects_persisted_theme(tmp_path, monkeypatch):
    monkeypatch.setattr(webui._options, "OPTIONS_PATH", lambda: tmp_path / "options.json")
    webui._options.write_options({"log_level": "moyen", "theme": "violet"}, tmp_path / "options.json")
    out = webui.page_shell("T", "options", "<p>x</p>")
    assert "data-theme='violet'" in out


def test_page_shell_theme_switch_has_3_forms_to_slash_theme(tmp_path, monkeypatch):
    monkeypatch.setattr(webui._options, "OPTIONS_PATH", lambda: tmp_path / "nope.json")
    out = webui.page_shell("T", "options", "<p>x</p>", csrf="tok-abc")
    assert out.count("action='/theme'") == 3
    for theme_id in ("violet", "dark", "light"):
        assert f"name='theme' value='{theme_id}'" in out
    assert out.count("name='csrf_token' value='tok-abc'") == 3
    # Le theme actif (defaut "dark") porte la classe active, pas les deux autres.
    assert "class='theme-btn active'>" in out
    assert out.count("class='theme-btn active'>") == 1


def test_page_shell_theme_switch_falls_back_to_runtime_csrf_token(tmp_path, monkeypatch):
    # page_shell() sans `csrf` explicite -> repli sur config._RUNTIME_CSRF_TOKEN
    # (pose par trading.monitor.build_monitor_server au demarrage du serveur reel).
    monkeypatch.setattr(webui._options, "OPTIONS_PATH", lambda: tmp_path / "nope.json")
    monkeypatch.setattr(webui.config, "_RUNTIME_CSRF_TOKEN", "server-wide-tok", raising=False)
    out = webui.page_shell("T", "options", "<p>x</p>")
    assert out.count("name='csrf_token' value='server-wide-tok'") == 3


def test_page_shell_escapes_title():
    out = webui.page_shell("<script>alert(1)</script>", "options", "<p>x</p>")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


# --------------------------------------------------------------------------- #
#  serve_static (anti path-traversal, MIME, 404)                              #
# --------------------------------------------------------------------------- #
def test_serve_static_serves_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "STATIC_DIR", tmp_path)
    (tmp_path / "app.js").write_text("console.log('ok');", encoding="utf-8")
    result = webui.serve_static("app.js")
    assert result is not None
    data, content_type = result
    assert data == b"console.log('ok');"
    assert content_type.startswith("application/javascript")


def test_serve_static_unknown_extension_falls_back_octet_stream(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "STATIC_DIR", tmp_path)
    (tmp_path / "data.bin").write_bytes(b"\x01\x02\x03")
    _, content_type = webui.serve_static("data.bin")
    assert content_type == "application/octet-stream"


def test_serve_static_404_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "STATIC_DIR", tmp_path)
    assert webui.serve_static("absent.js") is None


def test_serve_static_refuses_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static").mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("ne doit jamais sortir", encoding="utf-8")
    assert webui.serve_static("../secret.txt") is None
    assert webui.serve_static("..%2fsecret.txt") is None  # pas d'unquote ici : segment litteral
    assert webui.serve_static("sub/../../secret.txt") is None


def test_serve_static_refuses_empty_or_none():
    assert webui.serve_static("") is None
    assert webui.serve_static(None) is None


# --------------------------------------------------------------------------- #
#  job_panel_html (Lot 3) -- panneau reutilisable, fonction PURE              #
# --------------------------------------------------------------------------- #
def test_job_panel_html_contains_job_id_and_cancel_form():
    out = webui.job_panel_html("abc123", "tok-secret")
    assert "data-job-id='abc123'" in out
    assert "action='/job/abc123/cancel'" in out
    assert "name='csrf_token' value='tok-secret'" in out
    assert "/job/abc123/status" in out  # reference dans le JS de polling
    assert "class='job-panel'" in out
    assert "class='job-log'" in out


def test_job_panel_html_escapes_job_id_and_csrf():
    out = webui.job_panel_html("<script>", "\"'<tok>")
    # Ni le job_id ni le token ne doivent introduire de balise executable non echappee.
    assert "data-job-id='<script>'" not in out
    assert "&lt;script&gt;" in out


def test_job_panel_html_without_result_url_has_empty_attribute():
    out = webui.job_panel_html("jid", "tok")
    assert "data-result-url=''" in out


def test_job_panel_html_with_result_url_embeds_it():
    out = webui.job_panel_html("jid", "tok", result_url="/report/jid")
    assert "data-result-url='/report/jid'" in out


def test_job_panel_html_js_references_state_labels_as_json():
    out = webui.job_panel_html("jid", "tok")
    assert '"done": "Terminé."' in out
    assert '"error": "Erreur."' in out
    assert '"cancelled": "Annulé."' in out


def test_le_fond_est_ancre_au_viewport_pas_au_contenu():
    """Non-regression du defaut signale par l'utilisateur le 2026-08-18
    (capture a l'appui) : sur l'accueil, page courte, les deux radial-gradient
    de --page-bg etaient dimensionnes sur la boite du body (~630 px) alors que
    la couleur de fond, elle, se propage au canvas -- d'ou une coupure nette et
    une bande plate en bas de fenetre.

    Les deux proprietes ci-dessous sont ce qui ancre le fond au viewport ; les
    retirer fait revenir le defaut a l'identique. La source Claude Design portait
    deja `minHeight: 100vh` sur son conteneur racine."""
    # Ancrer sur un saut de ligne suivi de "body{" : la 1re occurrence de
    # "body{" tout court est `html,body{margin:0}`, qui ne porte pas le fond.
    regle_body = webui.THEME_CSS.split("\nbody{", 1)[1].split("\n}", 1)[0]
    # Retirer les commentaires CSS AVANT d'assertir : le commentaire de cette
    # regle nomme justement les deux proprietes, donc sans ce nettoyage le test
    # passerait meme si les declarations disparaissaient (mesure du 2026-08-18).
    declarations = re.sub(r"/\*.*?\*/", "", regle_body, flags=re.S)
    assert "background-attachment:fixed" in declarations
    assert "min-height:100vh" in declarations


def test_les_trois_themes_gardent_leur_propre_page_bg():
    """Le correctif d'ancrage ne doit pas uniformiser les fonds : chaque theme
    garde le sien (Ambre par defaut sur :root, Nuit et Clair en surcharge)."""
    fonds = re.findall(r"--page-bg:([^;]+);", webui.THEME_CSS)
    assert len(fonds) == 3, "il faut exactement 3 --page-bg (Ambre, Nuit, Clair)"
    assert len(set(fonds)) == 3, "les 3 themes doivent avoir des fonds distincts"
