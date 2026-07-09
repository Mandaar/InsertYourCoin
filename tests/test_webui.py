"""
Tests du socle web partage (Lot 0) : trading/webui.py.

Fonctions PURES, sans serveur ni reseau (l'integration serveur reelle est
couverte par tests/test_monitor_server.py pour la route /static/).
"""
from trading import webui


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
    assert "SSL VERIF. DESACTIVEE" not in out_on

    monkeypatch.setattr(webui.config, "VERIFY_SSL", False, raising=False)
    out_off = webui.page_shell("T", "options", "<p>x</p>")
    assert "ssl-bad" in out_off
    assert "SSL VERIF. DESACTIVEE" in out_off


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
