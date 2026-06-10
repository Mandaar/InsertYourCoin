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


def test_route_dashboard(server):
    code, page = _get(server + "/")
    assert code == 200
    assert "Paper trading - monitoring" in page


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
