"""
Tests d'INTEGRATION du serveur monitor : VRAI HTTP en loopback, port ephemere.

Raison d'etre (BUG-008) : une typo de route (backslash-options au lieu de
"/options") dans do_POST rendait la page Options inenregistrable (404 sur tout
POST). Les tests purs (fonctions isolees) ne couvraient pas le handler HTTP.
Ici on demarre le VRAI serveur (build_monitor_server, port 0) et on exerce les
routes de bout en bout -- ce qui aurait attrape la typo.
"""
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from trading import monitor as mon
from trading.options import read_options


@pytest.fixture()
def server(tmp_path, monkeypatch):
    # Ne JAMAIS toucher au vrai options.json du repo pendant les tests.
    monkeypatch.setattr("trading.options.OPTIONS_PATH",
                        lambda: tmp_path / "options.json")
    srv = mon.build_monitor_server(port=0,
                                   stats_path=tmp_path / "s.csv",
                                   log_path=tmp_path / "l.log",
                                   state_path=tmp_path / "st.json")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def test_route_monitoring(server):
    # Lot 1 : le monitoring a quitte "/" pour "/monitoring" (decision §11.1).
    code, page = _get(server + "/monitoring")
    assert code == 200
    assert "Paper trading - monitoring" in page


def test_route_fragment_toujours_actif(server):
    # /fragment est INCHANGE par la bascule de route (consomme par le JS de
    # la page /monitoring quelle que soit la page qui l'a chargee).
    code, fragment = _get(server + "/fragment")
    assert code == 200
    assert "Paper trading - monitoring" not in fragment  # fragment seul, pas la coquille


def test_route_accueil_hub(server):
    # Lot 1 : "/" est desormais l'Accueil (hub), pas le monitoring.
    code, page = _get(server + "/")
    assert code == 200
    assert "<h1>Accueil</h1>" in page
    assert "Diagnostic" in page
    assert "Paper trading" in page
    assert "Recherche" in page
    assert "Reglages" in page
    # item de nav actif = 'home', pas 'monitoring'
    assert "<a class='tab active' href='/'>Accueil</a>" in page


def test_route_accueil_ne_declenche_aucun_reseau(server):
    # Garde-fou anti-spam Kraken : le simple chargement de l'Accueil ne doit
    # jamais avoir declenche de test de connexion (etat neutre par defaut).
    _, page = _get(server + "/")
    assert "Non verifie cette session." in page


def test_route_check_etat_initial_sans_reseau(server):
    # GET /check SANS ?run=1 -- aucun appel Kraken, juste les versions locales.
    code, page = _get(server + "/check")
    assert code == 200
    assert "<h1>Diagnostic</h1>" in page
    assert "Installation" in page
    assert "Python" in page
    assert "ccxt" in page
    assert "Diagnostic non lance cette session." in page
    assert "Lancer le diagnostic" in page


def test_route_options_formulaire_et_liens(server):
    code, page = _get(server + "/options")
    assert code == 200
    assert "name='csrf_token'" in page                      # token anti-CSRF embarque
    assert "kraken.com/u/funding/withdraw" in page          # lien retrait OFFICIEL
    assert "type='password'" in page                        # cles jamais en clair


def test_post_sans_csrf_rejete(server):
    data = urllib.parse.urlencode({"log_level": "leger"}).encode()
    req = urllib.request.Request(server + "/options", data=data, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 403


def test_post_avec_csrf_enregistre_et_redirige(server, tmp_path):
    # BUG-008 : avec la typo de route, ce test echouait en 404 au lieu de 303->200.
    _, page = _get(server + "/options")
    token = re.search(r"name='csrf_token'[^>]*value='([0-9a-f]+)'", page).group(1)
    data = urllib.parse.urlencode({"csrf_token": token, "log_level": "leger"}).encode()
    req = urllib.request.Request(server + "/options", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:       # urllib suit le 303
        assert r.status == 200
    assert read_options(tmp_path / "options.json")["log_level"] == "leger"


def test_post_route_inconnue_404(server):
    data = urllib.parse.urlencode({"x": "1"}).encode()
    req = urllib.request.Request(server + "/autre", data=data, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 404


def test_route_static_sert_chart_js_vendorise(server):
    # Lot 0 : Chart.js vendorise localement, servi par le VRAI serveur HTTP --
    # verifie le branchement de la route (pas seulement la fonction pure serve_static).
    code, page = _get(server + "/static/chart.umd.min.js")
    assert code == 200
    assert "Chart.js" in page


def test_route_static_404_fichier_absent(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server + "/static/n-existe-pas.js")
    assert exc.value.code == 404


def test_route_static_refuse_path_traversal(server):
    # Path-traversal encode ('..' litteral dans le chemin) -> jamais un fichier
    # hors de trading/static/ (cf. trading/webui.py serve_static, garde double).
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server + "/static/../monitor.py")
    assert exc.value.code == 404


def test_nav_presente_sur_monitoring_et_options(server):
    # Lot 0 : les deux pages existantes rendent desormais la nav commune (page_shell).
    _, monitoring = _get(server + "/monitoring")
    _, opts = _get(server + "/options")
    for page in (monitoring, opts):
        assert "<nav class='nav'>" in page
        assert "Local 127.0.0.1" in page
