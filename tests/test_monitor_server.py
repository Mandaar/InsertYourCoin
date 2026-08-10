"""
Tests d'INTEGRATION du serveur monitor : VRAI HTTP en loopback, port ephemere.

Raison d'etre (BUG-008) : une typo de route (backslash-options au lieu de
"/options") dans do_POST rendait la page Options inenregistrable (404 sur tout
POST). Les tests purs (fonctions isolees) ne couvraient pas le handler HTTP.
Ici on demarre le VRAI serveur (build_monitor_server, port 0) et on exerce les
routes de bout en bout -- ce qui aurait attrape la typo.
"""
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

import lancer
from trading import monitor as mon
from trading.options import read_options
from trading.stats import StatsRecorder
from trading.strategies import STRATEGIES


def _teardown_server(srv):
    """BUG-012 : ferme REELLEMENT le serveur de test (loop + socket d'ecoute).

    Cause racine mesuree (docs/SQA.md BUG-012) : `srv.shutdown()` seul
    n'appelle jamais `server_close()` -- le socket d'ecoute reste ouvert
    (fileno() valide) apres shutdown(). Pire : `server.RequestHandlerClass`
    (Handler) ferme un CYCLE de references sur `srv` via les closures des
    routes /server/stop et /server/restart (`server_ref[0] = srv`), donc le
    refcounting seul ne libere JAMAIS l'objet -- prouve par script (gc
    desactive : `ref() is None` -> False ; gc.collect() : 96 objets
    cycliques retrouves). Sur ~65 serveurs construits par ce fichier de test
    (fixtures `server`/`server_obj`/`server_with_jobs`), chacun laissait un
    socket d'ecoute ouvert en attente d'un cycle du garbage collector
    generationnel dont le declenchement n'est PAS synchronise avec les
    requetes -- une collecte (ou la pression memoire/threads qu'elle
    implique) tombant pendant le transfert du plus GROS payload de toute la
    suite (chart.umd.min.js, 205 Ko, largement le plus long a servir) est le
    mecanisme le plus probable du `TimeoutError` intermittent.

    On utilise `type(srv).shutdown(srv)` / `type(srv).server_close(srv)`
    (methodes NON LIEES, sur la CLASSE) plutot que `srv.shutdown()` : 4 tests
    de ce fichier monkeypatchent `srv.shutdown` en instance (pour observer le
    SUT sans que le vrai arret n'interrompe le serveur pendant le test) --
    passer par la classe garantit que le VRAI arret + la VRAIE fermeture ont
    toujours lieu au teardown, quel que soit le mock pose par le test."""
    try:
        type(srv).shutdown(srv)
    finally:
        type(srv).server_close(srv)


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
        _teardown_server(srv)


@pytest.fixture()
def server_obj(tmp_path, monkeypatch):
    """Comme `server`, mais expose aussi l'objet serveur ET force root=tmp_path
    (jamais le run/monitor.pid ni les commandes de respawn du VRAI projet) --
    necessaire pour monkeypatcher shutdown()/spawn dans les tests stop/restart
    sans jamais toucher au monitor reel de la machine."""
    monkeypatch.setattr("trading.options.OPTIONS_PATH",
                        lambda: tmp_path / "options.json")
    monkeypatch.setattr(mon, "project_root", lambda: tmp_path)
    srv = mon.build_monitor_server(port=0,
                                   stats_path=tmp_path / "s.csv",
                                   log_path=tmp_path / "l.log",
                                   state_path=tmp_path / "st.json")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", srv
    finally:
        _teardown_server(srv)


@pytest.fixture()
def server_with_jobs(tmp_path, monkeypatch):
    # Meme fixture que `server`, mais expose aussi le JobManager du serveur
    # (Lot 3) pour y injecter des jobs synthetiques depuis les tests.
    monkeypatch.setattr("trading.options.OPTIONS_PATH",
                        lambda: tmp_path / "options.json")
    srv = mon.build_monitor_server(port=0,
                                   stats_path=tmp_path / "s.csv",
                                   log_path=tmp_path / "l.log",
                                   state_path=tmp_path / "st.json")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", srv.job_manager
    finally:
        _teardown_server(srv)


# --------------------------------------------------------------------------- #
#  BUG-012 -- test de non-regression du garde-fou de fermeture (_teardown_    #
#  server) : `srv.shutdown()` SEUL laisse le socket d'ecoute ouvert (fileno() #
#  valide) parce que le serveur ferme un cycle de references sur lui-meme via #
#  les closures des routes /server/stop et /server/restart -- le refcounting  #
#  seul ne le libere jamais. `_teardown_server` (utilise par les 3 fixtures   #
#  `server`/`server_obj`/`server_with_jobs`) DOIT fermer reellement le socket #
#  -- ce test le prouve directement (fileno() redevient invalide), sans       #
#  dependre d'un flake de timing pour le detecter.                            #
# --------------------------------------------------------------------------- #
def test_teardown_server_ferme_reellement_le_socket_decoute(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.options.OPTIONS_PATH",
                        lambda: tmp_path / "options.json")
    srv = mon.build_monitor_server(port=0,
                                   stats_path=tmp_path / "s.csv",
                                   log_path=tmp_path / "l.log",
                                   state_path=tmp_path / "st.json")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    assert srv.fileno() >= 0  # socket bien ouvert pendant que le serveur sert

    _teardown_server(srv)

    # BUG-012 : avant le correctif, `srv.shutdown()` seul laissait fileno()
    # >= 0 ici (socket toujours ouvert) -- server_close() DOIT avoir ete
    # appele (via type(srv), pas l'instance, pour rester correct meme si un
    # test a monkeypatche shutdown ou server_close sur l'instance). Un socket
    # ferme renvoie fileno() == -1 (ne leve pas OSError -- verifie empiriquement).
    assert srv.fileno() == -1


def test_teardown_server_ferme_le_socket_meme_si_shutdown_est_mocke_sur_linstance(
    tmp_path, monkeypatch,
):
    # Reproduit le contexte des 4 tests server_obj qui monkeypatchent
    # `srv.shutdown` en instance (pour observer le SUT sans interrompre le
    # serveur pendant le test) : _teardown_server doit malgre tout fermer le
    # VRAI socket au teardown, via type(srv).shutdown(srv)/server_close(srv).
    monkeypatch.setattr("trading.options.OPTIONS_PATH",
                        lambda: tmp_path / "options.json")
    srv = mon.build_monitor_server(port=0,
                                   stats_path=tmp_path / "s.csv",
                                   log_path=tmp_path / "l.log",
                                   state_path=tmp_path / "st.json")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(srv, "shutdown", lambda: None)  # comme les tests /server/stop

    _teardown_server(srv)

    assert srv.fileno() == -1  # socket reellement ferme malgre le mock d'instance
    # type(srv).shutdown(srv) est BLOQUANT (retourne seulement quand la boucle
    # serve_forever() a reellement quitte) -- au retour de _teardown_server le
    # thread a deja fini sa cible ; join(timeout=5) est une marge genereuse,
    # pas une dependance de timing (V12).
    t.join(timeout=5)
    assert not t.is_alive()  # la vraie boucle serve_forever s'est bien arretee


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _csrf_token(base_url):
    _, page = _get(base_url + "/options")
    return re.search(r"name='csrf_token'[^>]*value='([0-9a-f]+)'", page).group(1)


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
    # Reskin design (Claude Design) : le h1 reprend le libelle EXACT de
    # l'ecran Accueil source ("État du poste", cf.
    # docs/design/from_claude_design/rendered/accueil_*) -- l'ancien "Accueil"
    # devient l'eyebrow/le titre d'onglet, plus le h1 (fidelite au design).
    code, page = _get(server + "/")
    assert code == 200
    assert "<h1>État du poste</h1>" in page
    assert "Diagnostic" in page
    assert "Paper trading" in page
    assert "Recherche" in page
    assert "Réglages" in page
    # item de nav actif = 'home', pas 'monitoring'
    assert "<a class='tab active' href='/'>Accueil</a>" in page


def test_route_help_get(server):
    """Lot 9 (spec §4.14) : /help est desormais branche sur le VRAI serveur
    (pas seulement la fonction pure render_help_page)."""
    code, page = _get(server + "/help")
    assert code == 200
    assert "<h1>Aide</h1>" in page
    assert "class='tab active' href='/help'>Aide</a>" in page
    assert "SETUP.md" in page


def test_route_accueil_ne_declenche_aucun_reseau(server):
    # Garde-fou anti-spam Kraken : le simple chargement de l'Accueil ne doit
    # jamais avoir declenche de test de connexion (etat neutre par defaut).
    _, page = _get(server + "/")
    assert "Non vérifié cette session." in page


def test_route_check_etat_initial_sans_reseau(server):
    # GET /check SANS ?run=1 -- aucun appel Kraken, juste les versions locales.
    code, page = _get(server + "/check")
    assert code == 200
    assert "<h1>Diagnostic</h1>" in page
    assert "Installation" in page
    assert "Python" in page
    assert "ccxt" in page
    assert "Diagnostic non lancé cette session." in page
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


def test_route_404_uses_themed_page_shell(server):
    """P3-4 (audit L0-5) : les pages d'erreur brutes (<h1>404</h1>, sans
    doctype/charset/nav/theme) rompaient la coherence visuelle. Desormais
    404 passe par page_shell comme le reste de l'app."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server + "/cette-route-n-existe-pas")
    assert exc.value.code == 404
    body = exc.value.read().decode("utf-8")
    assert "<!DOCTYPE html>" in body
    assert "<meta charset='utf-8'>" in body
    assert "<nav class='nav'>" in body
    assert "<h1>404" in body


def test_route_403_host_non_autorise_uses_themed_page_shell(server):
    """Idem pour le 403 Host (anti-DNS-rebinding) : theme + nav, jamais un
    <h1> nu (P3-4)."""
    req = urllib.request.Request(server + "/", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 403
    body = exc.value.read().decode("utf-8")
    assert "<!DOCTYPE html>" in body
    assert "<nav class='nav'>" in body
    assert "403" in body


def test_route_403_csrf_invalide_uses_themed_page_shell(server):
    """Idem pour le 403 CSRF (POST /options sans jeton valide) -- P3-4."""
    data = urllib.parse.urlencode({"csrf_token": "bidon"}).encode()
    req = urllib.request.Request(server + "/options", data=data, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 403
    body = exc.value.read().decode("utf-8")
    assert "<!DOCTYPE html>" in body
    assert "<nav class='nav'>" in body
    assert "CSRF" in body


def test_route_static_sert_chart_js_vendorise(server):
    # Lot 0 : Chart.js vendorise localement, servi par le VRAI serveur HTTP --
    # verifie le branchement de la route (pas seulement la fonction pure serve_static).
    #
    # BUG-012 (docs/SQA.md) -- CAUSE RACINE REELLE, mesuree le 2026-08-08 :
    # cette route sert le SEUL fichier reellement lu sur disque et transmis
    # tel quel de toute la suite (chart.umd.min.js, 205 Ko, content-type
    # application/javascript) -- toutes les autres routes generent du HTML
    # dynamique en memoire. Un antivirus actif sur cette machine (Avast :
    # AvastSvc + AvastUI confirmes en cours d'execution) intercepte le trafic
    # HTTP en boucle locale et, sur une fraction des requetes (mesure :
    # ~10 %, 4/40 runs isoles), retarde ou RESET la connexion :
    #   - 4/40 executions de CE SEUL test, en isolation totale (aucun autre
    #     test, process pytest neuf a chaque fois) : timeout client a un
    #     delai QUASI CONSTANT de ~5,9 s (pas un GC pause aleatoire) ;
    #   - sonde dediee (timeout client porte a 20 s) : 1/25 executions =
    #     ConnectionResetError (WinError 10054, "connexion fermee par
    #     l'hote distant") apres ~19 s -- la connexion est activement
    #     COUPEE cote pair, pas seulement lente : aucun allongement de
    #     timeout cote client ne peut garantir la reussite dans ce cas.
    #   - reproduit aussi en isolation totale du FICHIER (10/10 runs
    #     sequentiels, aucune autre suite active) ET en suite complete --
    #     donc PAS un effet de pollution entre tests malgre l'hypothese
    #     initiale (fixtures corrigees separement, cf. `_teardown_server` :
    #     fuite de socket reelle et prouvee, mais non suffisante seule pour
    #     expliquer ce flake).
    # Correctif a la source pour CETTE interference externe non-deterministe
    # (ni un retry generique, ni un skip : 1 seule route, 2 tentatives max,
    # AUCUN affaiblissement d'assertion -- le contenu attendu est identique) :
    # on rejoue la requete si la 1re tentative est perturbee par l'AV.
    last_exc = None
    for attempt in range(2):
        try:
            code, page = _get(server + "/static/chart.umd.min.js")
            break
        except (TimeoutError, ConnectionResetError, urllib.error.URLError) as exc:
            last_exc = exc
    else:
        raise AssertionError(
            f"GET /static/chart.umd.min.js a echoue 2 fois de suite "
            f"(derniere erreur : {last_exc!r}) -- cf. docs/SQA.md BUG-012"
        )
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


def test_route_stats_etat_vide(server):
    # Lot 2 : pas de CSV -> message pedagogique EXACT de load_stats, 200 (pas
    # une erreur), encart d'honnetete quand meme present.
    code, page = _get(server + "/stats")
    assert code == 200
    assert "Labo de stats" in page
    assert "Aucune donnee" in page
    assert "Lance d&#x27;abord du paper trading" in page or "Lance d'abord du paper" in page
    assert "DESCRIPTIVES" in page


def test_route_stats_avec_donnees(server, tmp_path):
    stats_csv = tmp_path / "s.csv"
    rec = StatsRecorder(str(stats_csv))
    rec.record({"time": "2022-01-01 00:00:00", "hour": 0, "weekday": 0,
               "equity": 100.0, "exposure": 0.0, "action": "buy",
               "pnl": 0.0, "fee_paid": 0.26})
    rec.record({"time": "2022-01-01 01:00:00", "hour": 1, "weekday": 0,
               "equity": 120.0, "exposure": 1.0, "action": "sell",
               "pnl": 20.0, "fee_paid": 0.31})
    code, page = _get(server + "/stats")
    assert code == 200
    assert "Cycles" in page
    assert "PnL total" in page
    assert "Frais" in page
    assert "DESCRIPTIVES" in page


def test_route_stats_ignore_chemin_arbitraire(server, tmp_path):
    # Fichier HORS liste blanche (ne matche pas '*_stats.csv') : meme s'il
    # existe, /stats ne doit JAMAIS le lire -- retombe sur l'etat vide par
    # defaut (aucune donnee de secret.env qui ne fuite dans la page).
    secret = tmp_path / "secret.env"
    secret.write_text("KRAKEN_API_SECRET=do-not-leak", encoding="utf-8")
    code, page = _get(server + "/stats?file=secret.env")
    assert code == 200
    assert "do-not-leak" not in page
    assert "Aucune donnee" in page  # aucun stats.csv par defaut -> etat vide


def test_route_stats_ignore_path_traversal(server, tmp_path):
    code, page = _get(server + "/stats?file=..%2f..%2fsecret.env")
    assert code == 200
    assert "do-not-leak" not in page


# --------------------------------------------------------------------------- #
#  Lot 3 -- routes jobs asynchrones (GET /job/<id>/status, POST /job/<id>/cancel)
# --------------------------------------------------------------------------- #
def test_route_job_status_unknown_id_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server + "/job/" + "0" * 32 + "/status")
    assert exc.value.code == 404


def test_route_job_status_malformed_id_404(server):
    # Ne matche pas le format uuid4 hex attendu -> 404 generique, jamais
    # transmis a JobManager.status (defense en profondeur, cf. _JOB_STATUS_RE).
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server + "/job/not-a-valid-id/status")
    assert exc.value.code == 404


def test_route_job_status_returns_expected_json(server_with_jobs):
    url, mgr = server_with_jobs
    started = threading.Event()
    release = threading.Event()

    def target(progress):
        started.set()
        progress.log("etape 1")
        release.wait(timeout=2)
        return {"ok": True}

    job_id = mgr.submit(target, label="job test")
    assert started.wait(timeout=2)

    code, body = _get(url + f"/job/{job_id}/status")
    assert code == 200
    data = json.loads(body)
    assert data["id"] == job_id
    assert data["label"] == "job test"
    assert data["state"] in ("running", "pending")
    assert "etape 1" in data["log"]
    assert "result" not in data  # jamais le resultat lui-meme dans /status

    release.set()


def test_route_job_cancel_sans_csrf_rejete(server_with_jobs):
    url, mgr = server_with_jobs
    job_id = mgr.submit(lambda p: None)
    data = urllib.parse.urlencode({}).encode()
    req = urllib.request.Request(url + f"/job/{job_id}/cancel", data=data, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 403


def test_route_job_cancel_avec_csrf_annule(server_with_jobs):
    url, mgr = server_with_jobs
    started = threading.Event()

    def target(progress):
        started.set()
        while not progress.cancelled:
            time.sleep(0.01)
        return None

    job_id = mgr.submit(target)
    assert started.wait(timeout=2)

    token = _csrf_token(url)
    data = urllib.parse.urlencode({"csrf_token": token}).encode()
    req = urllib.request.Request(url + f"/job/{job_id}/cancel", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200
        body = json.loads(r.read().decode("utf-8"))
    assert body["state"] in ("running", "cancelled")  # cooperatif : bascule pas forcement immediate

    deadline = time.time() + 2
    state = None
    while time.time() < deadline:
        _, st_body = _get(url + f"/job/{job_id}/status")
        state = json.loads(st_body)["state"]
        if state == "cancelled":
            break
        time.sleep(0.02)
    assert state == "cancelled"


def test_route_job_cancel_job_inconnu_404(server_with_jobs):
    url, _mgr = server_with_jobs
    token = _csrf_token(url)
    data = urllib.parse.urlencode({"csrf_token": token}).encode()
    req = urllib.request.Request(url + "/job/" + "a" * 32 + "/cancel", data=data, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 404


def test_nav_presente_sur_monitoring_et_options(server):
    # Lot 0 : les deux pages existantes rendent desormais la nav commune (page_shell).
    _, monitoring = _get(server + "/monitoring")
    _, opts = _get(server + "/options")
    for page in (monitoring, opts):
        assert "<nav class='nav'>" in page
        assert "Local 127.0.0.1" in page


# --------------------------------------------------------------------------- #
#  Reskin design (Claude Design) -- switch de theme POST /theme               #
# --------------------------------------------------------------------------- #
def test_route_theme_default_is_dark_ambre(server):
    _, page = _get(server + "/")
    assert "data-theme='dark'" in page


def test_route_theme_post_sans_csrf_rejete(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server + "/theme", {"theme": "violet"})
    assert exc.value.code == 403


def test_route_theme_post_switches_and_persists(server):
    token = _csrf_token(server)
    code, page_after_redirect = _post(server + "/theme", {"theme": "violet", "csrf_token": token})
    assert code == 200  # urlopen suit le 303 -> 200 final sur la page de retour
    assert "data-theme='violet'" in page_after_redirect
    # Persistance reelle (pas juste la reponse de cette requete) : une AUTRE
    # page, sur une AUTRE requete, reflete desormais aussi le theme choisi.
    _, options_page = _get(server + "/options")
    assert "data-theme='violet'" in options_page


def test_route_theme_post_invalid_value_ignored_silently(server):
    # Une valeur hors THEME_IDS est ignoree (pas d'exception, pas de crash) --
    # le theme persiste reste celui d'avant (defaut "dark").
    token = _csrf_token(server)
    code, page = _post(server + "/theme", {"theme": "n-existe-pas", "csrf_token": token})
    assert code == 200
    assert "data-theme='dark'" in page


def test_route_theme_post_redirects_to_referer_path(server):
    token = _csrf_token(server)
    data = urllib.parse.urlencode({"theme": "light", "csrf_token": token}).encode()
    req = urllib.request.Request(server + "/theme", data=data, method="POST")
    req.add_header("Referer", server + "/stats")
    with urllib.request.urlopen(req, timeout=5) as r:
        # urlopen a suivi la redirection : l'URL finale est bien /stats (pas "/").
        assert r.geturl() == server + "/stats"
        page = r.read().decode("utf-8")
    assert "Labo de stats" in page
    assert "data-theme='light'" in page


def test_route_theme_post_never_redirects_off_origin(server):
    # _safe_next_path ne recopie QUE le chemin du Referer (jamais son schema
    # ni son hote) : meme avec un Referer forge vers un autre domaine, la
    # redirection reste TOUJOURS sur ce serveur (127.0.0.1:<port>) -- jamais
    # une evasion vers l'exterieur. Ici le chemin "/phishing" n'existe pas
    # sur ce serveur -> 404, mais l'hote redirige, lui, reste le notre.
    token = _csrf_token(server)
    data = urllib.parse.urlencode({"theme": "dark", "csrf_token": token}).encode()
    req = urllib.request.Request(server + "/theme", data=data, method="POST")
    req.add_header("Referer", "http://evil.example/phishing")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 404
    assert exc.value.geturl().startswith(server + "/")  # jamais evil.example


def test_route_theme_post_referer_without_scheme_stays_local(server):
    # Referer "propre" (meme origine, comme un vrai navigateur l'envoie) ->
    # redirection fonctionnelle vers CE chemin precis.
    token = _csrf_token(server)
    data = urllib.parse.urlencode({"theme": "dark", "csrf_token": token}).encode()
    req = urllib.request.Request(server + "/theme", data=data, method="POST")
    req.add_header("Referer", server + "/help")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.geturl() == server + "/help"


# --------------------------------------------------------------------------- #
#  Lot 4 -- Recherche / Backtest + Rapport inline (routage HTTP reel,         #
#  AUCUN reseau : trading.research_runners._load_ohlcv est monkeypatche)      #
# --------------------------------------------------------------------------- #
def _post(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _extract_job_id(page):
    m = re.search(r"data-job-id='([0-9a-f]{32})'", page)
    assert m, "aucun panneau de job (data-job-id) trouve dans la page"
    return m.group(1)


def _wait_job_done(base_url, job_id, timeout=5):
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        _, body = _get(base_url + f"/job/{job_id}/status")
        state = json.loads(body)["state"]
        if state in ("done", "error", "cancelled"):
            return state
        time.sleep(0.02)
    return state


def test_route_research_backtest_form_lists_strategies(server):
    code, page = _get(server + "/research/backtest")
    assert code == 200
    assert "Recherche" in page
    assert "action='/research/backtest'" in page
    for key in STRATEGIES:
        assert f"value='{key}'" in page
    assert "name='csrf_token'" in page


def test_route_research_backtest_post_sans_csrf_rejete(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server + "/research/backtest", {"strategy": "sma"})
    assert exc.value.code == 403


def test_route_research_backtest_post_invalide_reaffiche_formulaire(server):
    token = _csrf_token(server)
    code, page = _post(server + "/research/backtest",
                       {"csrf_token": token, "strategy": "n-existe-pas"})
    assert code == 200
    assert "Stratégie inconnue" in page
    assert "class='job-panel'" not in page  # pas de job lance sur un formulaire invalide


def test_route_research_backtest_post_creates_job_and_report_shows_result(
    server, monkeypatch, make_df,
):
    closes = [100 + i * 0.5 for i in range(150)]
    df = make_df(closes)
    monkeypatch.setattr("trading.research_runners._load_ohlcv",
                        lambda params, progress: df)

    token = _csrf_token(server)
    code, launched = _post(server + "/research/backtest", {
        "csrf_token": token, "strategy": "sma", "symbol": "ETH/USD",
        "timeframe": "1d", "days": "150", "source": "kraken",
    })
    assert code == 200
    assert "class='job-panel'" in launched
    job_id = _extract_job_id(launched)
    assert f"/report/{job_id}" in launched  # result_url du panneau

    state = _wait_job_done(server, job_id)
    assert state == "done"

    code, report = _get(server + f"/report/{job_id}")
    assert code == 200
    assert "IN-SAMPLE" in report
    assert "walk-forward" in report.lower()
    assert 'id="equity"' in report
    assert "ETH/USD" in report


def test_route_research_backtest_post_second_job_refuses_with_busy_message(
    server_with_jobs,
):
    url, mgr = server_with_jobs
    started = threading.Event()
    release = threading.Event()

    def blocking(progress):
        started.set()
        release.wait(timeout=2)
        return None

    mgr.submit(blocking, label="Backtest sma ETH/USD (1d)")
    assert started.wait(timeout=2)

    token = _csrf_token(url)
    code, page = _post(url + "/research/backtest", {
        "csrf_token": token, "strategy": "sma",
    })
    assert code == 200
    assert "déjà en cours" in page
    assert "Backtest sma ETH/USD (1d)" in page
    assert "class='job-panel'" in page  # panneau du job EN COURS, pas un nouveau job

    release.set()


def test_route_report_job_inconnu_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server + "/report/" + "0" * 32)
    assert exc.value.code == 404


def test_route_report_id_malforme_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server + "/report/not-a-valid-id")
    assert exc.value.code == 404


def test_route_report_pending_affiche_panneau_job(server_with_jobs):
    url, mgr = server_with_jobs
    started = threading.Event()
    release = threading.Event()

    def blocking(progress):
        started.set()
        release.wait(timeout=2)
        return {"ok": True}

    job_id = mgr.submit(blocking, label="job test")
    assert started.wait(timeout=2)

    code, page = _get(url + f"/report/{job_id}")
    assert code == 200
    assert "class='job-panel'" in page

    release.set()


def test_route_nav_recherche_active_et_habilitee(server):
    code, page = _get(server + "/research/backtest")
    assert code == 200
    assert "<a class='tab active' href='/research/backtest'>Recherche</a>" in page


# --------------------------------------------------------------------------- #
#  Lot 5 -- Recherche / Comparer + Optimiser + Portefeuille (routage HTTP     #
#  reel, AUCUN reseau : research_runners._load_ohlcv / _load_basket_ohlcv     #
#  sont monkeypatches). Le rendu resultat passe par le /report/<job_id>       #
#  GENERALISE (trading/report_page.py render_result_done, cf. Lot 5).         #
# --------------------------------------------------------------------------- #
def test_route_research_compare_form_has_csrf_and_no_strategy_field(server):
    code, page = _get(server + "/research/compare")
    assert code == 200
    assert "action='/research/compare'" in page
    assert "name='csrf_token'" in page
    assert "name='strategy'" not in page


def test_route_research_compare_post_sans_csrf_rejete(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server + "/research/compare", {"symbol": "ETH/USD"})
    assert exc.value.code == 403


def test_route_research_compare_post_creates_job_and_report_shows_result(
    server, monkeypatch, make_df,
):
    closes = [100 + i * 0.5 for i in range(150)]
    df = make_df(closes)
    monkeypatch.setattr("trading.research_runners._load_ohlcv",
                        lambda params, progress: df)

    token = _csrf_token(server)
    code, launched = _post(server + "/research/compare", {
        "csrf_token": token, "symbol": "ETH/USD", "timeframe": "1d",
        "days": "150", "source": "kraken",
    })
    assert code == 200
    assert "class='job-panel'" in launched
    job_id = _extract_job_id(launched)

    state = _wait_job_done(server, job_id)
    assert state == "done"

    code, report = _get(server + f"/report/{job_id}")
    assert code == 200
    assert "Recherche &mdash; Comparer" in report
    assert "Buy &amp; Hold" in report
    assert "IN-SAMPLE" in report


def test_route_research_optimize_form_lists_strategies_and_metrics(server):
    code, page = _get(server + "/research/optimize")
    assert code == 200
    assert "action='/research/optimize'" in page
    for key in STRATEGIES:
        assert f"value='{key}'" in page
    assert "value='sharpe'" in page


def test_route_research_optimize_post_invalide_reaffiche_formulaire(server):
    token = _csrf_token(server)
    code, page = _post(server + "/research/optimize",
                       {"csrf_token": token, "strategy": "n-existe-pas"})
    assert code == 200
    assert "Stratégie inconnue" in page
    assert "class='job-panel'" not in page


def test_route_research_optimize_post_creates_job_and_report_shows_result(
    server, monkeypatch, make_df,
):
    closes = [100 + 20 * math.sin(i / 12.0) for i in range(600)]
    df = make_df(closes)
    monkeypatch.setattr("trading.research_runners._load_ohlcv",
                        lambda params, progress: df)

    token = _csrf_token(server)
    code, launched = _post(server + "/research/optimize", {
        "csrf_token": token, "strategy": "sma", "symbol": "ETH/USD",
        "timeframe": "1d", "days": "600", "source": "kraken",
        "metric": "sharpe", "train_frac": "0.6",
    })
    assert code == 200
    assert "class='job-panel'" in launched
    job_id = _extract_job_id(launched)

    state = _wait_job_done(server, job_id)
    assert state == "done"

    code, report = _get(server + f"/report/{job_id}")
    assert code == 200
    assert "Train (in-sample)" in report
    assert "Test (hors-échantillon)" in report


def test_route_research_portfolio_form_shows_default_symbols(server):
    code, page = _get(server + "/research/portfolio")
    assert code == 200
    assert "action='/research/portfolio'" in page
    assert "BTC/USD,ETH/USD,SOL/USD" in page


def test_route_research_portfolio_post_creates_job_and_report_shows_result(
    server, monkeypatch, make_df,
):
    btc = make_df([100 + 20 * math.sin(i / 12.0) for i in range(150)])
    eth = make_df([50 + 10 * math.sin(i / 9.0) for i in range(150)])

    def _fake_basket(params, progress):
        return {"BTC/USD": btc, "ETH/USD": eth}, []

    monkeypatch.setattr("trading.research_runners._load_basket_ohlcv", _fake_basket)

    token = _csrf_token(server)
    code, launched = _post(server + "/research/portfolio", {
        "csrf_token": token, "symbols": "BTC/USD,ETH/USD", "strategy": "sma",
        "timeframe": "1d", "days": "150", "source": "kraken",
    })
    assert code == 200
    assert "class='job-panel'" in launched
    job_id = _extract_job_id(launched)

    state = _wait_job_done(server, job_id)
    assert state == "done"

    code, report = _get(server + f"/report/{job_id}")
    assert code == 200
    assert "corr-table" in report
    assert "Corrélation moyenne" in report


def test_route_research_subnav_links_all_four_screens(server):
    code, page = _get(server + "/research/backtest")
    assert code == 200
    for href in ("/research/backtest", "/research/compare",
                "/research/optimize", "/research/portfolio"):
        assert f"href='{href}'" in page


# --------------------------------------------------------------------------- #
#  Lot 6 -- Recherche / Walk-forward (LE JUGE), routage HTTP reel, AUCUN      #
#  reseau (research_runners._load_basket_ohlcv monkeypatche). Meme patron que #
#  les routes Lot 5 ci-dessus.                                                #
# --------------------------------------------------------------------------- #
def test_route_research_walkforward_form_has_csrf_and_default_holdout(server):
    code, page = _get(server + "/research/walkforward")
    assert code == 200
    assert "action='/research/walkforward'" in page
    assert "name='csrf_token'" in page
    assert "id='holdout'" in page
    assert "value='20.0'" in page          # holdout sacre pre-rempli a 20%
    assert "window.confirm(" in page       # friction --final (confirmation modale)
    assert "<a class='sub-tab active' href='/research/walkforward'>" in page


def test_route_research_walkforward_post_sans_csrf_rejete(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server + "/research/walkforward", {"strategy": "sma"})
    assert exc.value.code == 403


def test_route_research_walkforward_post_invalide_reaffiche_formulaire(server):
    token = _csrf_token(server)
    code, page = _post(server + "/research/walkforward",
                       {"csrf_token": token, "strategy": "n-existe-pas"})
    assert code == 200
    assert "Stratégie inconnue" in page
    assert "class='job-panel'" not in page


def test_route_research_walkforward_post_holdout_out_of_range_exact_cli_message(server):
    # Garde reprise EXACTEMENT de main.py cmd_walkforward (lignes 181-182),
    # appliquee COTE SERVEUR (jamais seulement cote client).
    token = _csrf_token(server)
    code, page = _post(server + "/research/walkforward",
                       {"csrf_token": token, "strategy": "sma", "holdout": "95"})
    assert code == 200
    assert "Holdout : pourcentage attendu dans [0, 90[." in page
    assert "class='job-panel'" not in page


def test_route_research_walkforward_post_final_sans_holdout_exact_cli_message(server):
    # --final exige --holdout > 0 (main.py:183-184) -- verifie cote serveur :
    # meme un POST forge sans passer par la modale JS est refuse.
    token = _csrf_token(server)
    code, page = _post(server + "/research/walkforward",
                       {"csrf_token": token, "strategy": "sma", "holdout": "0",
                        "final": "1"})
    assert code == 200
    # '>' est HTML-echappe par le rendu de la liste d'erreurs (_esc), cf.
    # trading/walkforward_page.py render_walkforward_form.
    assert (
        "Validation finale : exige un holdout &gt; 0 (sans holdout, pas de segment sacré)."
        in page
    )
    assert "class='job-panel'" not in page


def test_route_research_walkforward_post_creates_job_and_report_shows_verdict(
    server, monkeypatch, make_df,
):
    closes = [100 + 20 * math.sin(i / 12.0) for i in range(600)]
    df = make_df(closes)

    def _fake_basket(params, progress):
        return {"ETH/USD": df}, []

    monkeypatch.setattr("trading.research_runners._load_basket_ohlcv", _fake_basket)

    token = _csrf_token(server)
    code, launched = _post(server + "/research/walkforward", {
        "csrf_token": token, "strategy": "sma", "symbols": "ETH/USD",
        "timeframe": "1d", "days": "600", "source": "kraken",
        "fixed": "fast=10,slow=50", "windows": "4", "train_frac": "0.5",
        "metric": "sharpe", "holdout": "0",
    })
    assert code == 200
    assert "class='job-panel'" in launched
    job_id = _extract_job_id(launched)

    state = _wait_job_done(server, job_id)
    assert state == "done"

    code, report = _get(server + f"/report/{job_id}")
    assert code == 200
    assert "VERDICT :" in report
    assert "Recherche &mdash; Walk-forward" in report
    assert "NON consommé" in report   # holdout=0 -> jamais consomme


def test_route_research_subnav_links_walkforward_screen(server):
    code, page = _get(server + "/research/backtest")
    assert code == 200
    assert "href='/research/walkforward'" in page


@pytest.mark.parametrize("path,fields", [
    ("/research/compare", {}),
    ("/research/optimize", {"strategy": "sma"}),
    ("/research/portfolio", {"strategy": "sma"}),
    ("/research/walkforward", {"strategy": "sma"}),
])
def test_route_research_lot5_screens_refuse_second_job_while_busy(
    server_with_jobs, path, fields,
):
    # Un seul job a la fois (spec §7.2), verifie sur les 3 nouveaux ecrans --
    # meme garde-fou que /research/backtest (Lot 4).
    url, mgr = server_with_jobs
    started = threading.Event()
    release = threading.Event()

    def blocking(progress):
        started.set()
        release.wait(timeout=2)
        return None

    mgr.submit(blocking, label="job bloquant")
    assert started.wait(timeout=2)

    token = _csrf_token(url)
    data = dict(fields, csrf_token=token)
    code, page = _post(url + path, data)
    assert code == 200
    assert "déjà en cours" in page
    assert "class='job-panel'" in page

    release.set()


# --------------------------------------------------------------------------- #
#  Serveur web : arret / redemarrage (Options) -- CONTROLE UNIQUEMENT le      #
#  serveur, jamais le paper trading. shutdown()/spawn TOUJOURS mockes ici :   #
#  ces tests ne doivent ni couper le serveur de test avant la fin des         #
#  assertions, ni lancer un VRAI process.                                     #
# --------------------------------------------------------------------------- #
def test_route_server_stop_sans_csrf_rejete(server_obj):
    url, srv = server_obj
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(url + "/server/stop", {})
    assert exc.value.code == 403


def test_route_server_stop_avec_csrf_repond_puis_demande_arret(server_obj, monkeypatch):
    url, srv = server_obj
    called = threading.Event()
    monkeypatch.setattr(srv, "shutdown", lambda: called.set())

    token = _csrf_token(url)
    code, page = _post(url + "/server/stop", {"csrf_token": token})
    assert code == 200
    assert "arrêt" in page.lower()
    assert "n'est pas touché" in page.lower() or "continue" in page.lower()

    # L'arret est demande APRES la reponse, dans un thread separe (sinon la
    # requete ne recevrait jamais sa reponse -- cf. do_POST /server/stop).
    assert called.wait(timeout=2)


def test_route_server_stop_cleans_own_pid_file(server_obj, monkeypatch, tmp_path):
    url, srv = server_obj
    monkeypatch.setattr(srv, "shutdown", lambda: None)  # pas de vrai arret ici
    (tmp_path / "run").mkdir(exist_ok=True)
    pid_path = tmp_path / "run" / "monitor.pid"
    pid_path.write_text(f"{os.getpid()}:1700000000.0", encoding="ascii")

    token = _csrf_token(url)
    _post(url + "/server/stop", {"csrf_token": token})

    deadline = time.time() + 2
    while time.time() < deadline and pid_path.exists():
        time.sleep(0.02)
    assert not pid_path.exists()


def test_route_server_stop_does_not_remove_pid_file_of_other_process(
    server_obj, monkeypatch, tmp_path,
):
    # Garde-fou identite (meme esprit que lancer.py is_our_process) : un pid
    # file qui ne pointe PAS ce process n'est jamais touche.
    url, srv = server_obj
    monkeypatch.setattr(srv, "shutdown", lambda: None)
    (tmp_path / "run").mkdir(exist_ok=True)
    pid_path = tmp_path / "run" / "monitor.pid"
    pid_path.write_text("999999999:1700000000.0", encoding="ascii")

    token = _csrf_token(url)
    _post(url + "/server/stop", {"csrf_token": token})
    time.sleep(0.2)
    assert pid_path.exists()
    assert pid_path.read_text(encoding="ascii") == "999999999:1700000000.0"


def test_route_server_stop_ne_touche_jamais_paper_pid(server_obj, monkeypatch, tmp_path):
    # Garde-fou explicite du perimetre (brief) : le bouton stop ne controle
    # QUE le serveur web, jamais le paper trading.
    url, srv = server_obj
    monkeypatch.setattr(srv, "shutdown", lambda: None)
    (tmp_path / "run").mkdir(exist_ok=True)
    paper_pid = tmp_path / "run" / "paper.pid"
    paper_pid.write_text("424242:1700000000.0", encoding="ascii")

    token = _csrf_token(url)
    _post(url + "/server/stop", {"csrf_token": token})
    time.sleep(0.2)
    assert paper_pid.read_text(encoding="ascii") == "424242:1700000000.0"


def test_route_server_restart_sans_csrf_rejete(server_obj):
    url, srv = server_obj
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(url + "/server/restart", {})
    assert exc.value.code == 403


def test_route_server_restart_avec_csrf_repond_puis_relance(server_obj, monkeypatch):
    url, srv = server_obj
    shutdown_called = threading.Event()
    monkeypatch.setattr(srv, "shutdown", lambda: shutdown_called.set())
    monkeypatch.setattr(srv, "server_close", lambda: None)
    spawned = []
    monkeypatch.setattr(
        mon, "_spawn_detached_monitor",
        lambda cmd, log_path, cwd: spawned.append((cmd, log_path, cwd)) or 999999,
    )

    token = _csrf_token(url)
    code, page = _post(url + "/server/restart", {"csrf_token": token})
    assert code == 200
    assert "redémarr" in page.lower()

    assert shutdown_called.wait(timeout=2)
    deadline = time.time() + 2
    while time.time() < deadline and not spawned:
        time.sleep(0.02)
    assert spawned, "un nouveau process monitor aurait du etre (re)spawn (mocke)"
    cmd, log_path, cwd = spawned[0]
    assert "monitor" in cmd and "--port" in cmd


def test_route_server_restart_forwards_host_and_data_paths(server_obj, monkeypatch, tmp_path):
    # Deploiement Docker (2026-08-09) : --host et --stats/--log/--state DOIVENT
    # survivre a un clic "Redemarrer le serveur", sinon le respawn revient
    # silencieusement a 127.0.0.1 (injoignable depuis le reverse proxy, sur un
    # AUTRE conteneur du reseau) et aux chemins par defaut de project_root()
    # (qui divergent du volume Docker passe au demarrage). server_obj construit
    # le serveur avec stats_path=tmp_path/s.csv, log_path=tmp_path/l.log,
    # state_path=tmp_path/st.json -- on verifie qu'ils sont bien reforwardes.
    url, srv = server_obj
    monkeypatch.setattr(srv, "shutdown", lambda: None)
    monkeypatch.setattr(srv, "server_close", lambda: None)
    spawned = []
    monkeypatch.setattr(
        mon, "_spawn_detached_monitor",
        lambda cmd, log_path, cwd: spawned.append((cmd, log_path, cwd)) or 999999,
    )

    token = _csrf_token(url)
    _post(url + "/server/restart", {"csrf_token": token})

    deadline = time.time() + 2
    while time.time() < deadline and not spawned:
        time.sleep(0.02)
    assert spawned
    cmd, _log_path, _cwd = spawned[0]
    assert "--host" in cmd and "127.0.0.1" in cmd
    assert "--stats" in cmd and str(tmp_path / "s.csv") in cmd
    assert "--log" in cmd and str(tmp_path / "l.log") in cmd
    assert "--state" in cmd and str(tmp_path / "st.json") in cmd


def test_restart_thread_forwards_data_paths_when_provided(tmp_path, monkeypatch):
    # Unit : appel direct de _restart_server_thread avec les 3 chemins fournis
    # -> ils apparaissent dans la commande de respawn (complement du test
    # existant test_restart_thread_ecrit_l_erreur_au_lieu_de_l_avaler, qui
    # appelle sans eux -- doit rester valide : defauts None retro-compatibles).
    captured = []
    monkeypatch.setattr(
        mon, "_spawn_detached_monitor",
        lambda cmd, log_path, cwd: captured.append(cmd) or 4242,
    )
    mon._restart_server_thread(
        [None], tmp_path, 8765, "0.0.0.0",
        stats_path=tmp_path / "s.csv",
        data_log_path=tmp_path / "l.log",
        state_path=tmp_path / "st.json",
    )
    assert captured
    cmd = captured[0]
    assert cmd[cmd.index("--host") + 1] == "0.0.0.0"
    assert cmd[cmd.index("--stats") + 1] == str(tmp_path / "s.csv")
    assert cmd[cmd.index("--log") + 1] == str(tmp_path / "l.log")
    assert cmd[cmd.index("--state") + 1] == str(tmp_path / "st.json")


def test_restart_thread_forwards_allowed_hosts_when_provided(tmp_path, monkeypatch):
    # Deploiement derriere un reverse-proxy EXISTANT (SWAG, 2026-08-09) : meme
    # classe de bug que host/stats/log/state ci-dessus -- sans re-forward,
    # un clic "Redemarrer le serveur" ferait perdre l'allowlist et le
    # nouveau process respawn tomberait en 403 sur toute requete via SWAG.
    captured = []
    monkeypatch.setattr(
        mon, "_spawn_detached_monitor",
        lambda cmd, log_path, cwd: captured.append(cmd) or 4242,
    )
    mon._restart_server_thread(
        [None], tmp_path, 8765, "0.0.0.0",
        allowed_hosts=("iyc.eunivers.net", "other.example"),
    )
    assert captured
    cmd = captured[0]
    idx = [i for i, tok in enumerate(cmd) if tok == "--allowed-host"]
    assert len(idx) == 2
    assert cmd[idx[0] + 1] == "iyc.eunivers.net"
    assert cmd[idx[1] + 1] == "other.example"


def test_restart_thread_without_allowed_hosts_omits_the_flag(tmp_path, monkeypatch):
    # Non-regression : allowed_hosts=() (defaut) -> aucun --allowed-host dans
    # la commande de respawn, comportement identique a avant ce patch.
    captured = []
    monkeypatch.setattr(
        mon, "_spawn_detached_monitor",
        lambda cmd, log_path, cwd: captured.append(cmd) or 4242,
    )
    mon._restart_server_thread([None], tmp_path, 8765, "127.0.0.1")
    assert captured
    assert "--allowed-host" not in captured[0]


def test_route_server_restart_forwards_allowed_hosts(tmp_path, monkeypatch):
    # Integration bout-en-bout : un serveur construit avec allowed_hosts=(...)
    # doit les re-forwarder au respawn declenche par POST /server/restart.
    monkeypatch.setattr("trading.options.OPTIONS_PATH",
                        lambda: tmp_path / "options.json")
    monkeypatch.setattr(mon, "project_root", lambda: tmp_path)
    srv = mon.build_monitor_server(port=0,
                                   stats_path=tmp_path / "s.csv",
                                   log_path=tmp_path / "l.log",
                                   state_path=tmp_path / "st.json",
                                   allowed_hosts=("iyc.eunivers.net",))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        monkeypatch.setattr(srv, "shutdown", lambda: None)
        monkeypatch.setattr(srv, "server_close", lambda: None)
        spawned = []
        monkeypatch.setattr(
            mon, "_spawn_detached_monitor",
            lambda cmd, log_path, cwd: spawned.append(cmd) or 999999,
        )

        token = _csrf_token(url)
        _post(url + "/server/restart", {"csrf_token": token})

        deadline = time.time() + 2
        while time.time() < deadline and not spawned:
            time.sleep(0.02)
        assert spawned
        cmd = spawned[0]
        assert "--allowed-host" in cmd
        assert cmd[cmd.index("--allowed-host") + 1] == "iyc.eunivers.net"
    finally:
        _teardown_server(srv)


def test_route_server_restart_writes_new_pid_file(server_obj, monkeypatch, tmp_path):
    url, srv = server_obj
    monkeypatch.setattr(srv, "shutdown", lambda: None)
    monkeypatch.setattr(srv, "server_close", lambda: None)
    monkeypatch.setattr(mon, "_spawn_detached_monitor",
                        lambda cmd, log_path, cwd: 123456)

    token = _csrf_token(url)
    _post(url + "/server/restart", {"csrf_token": token})

    pid_path = tmp_path / "run" / "monitor.pid"
    deadline = time.time() + 2
    while time.time() < deadline and not pid_path.exists():
        time.sleep(0.02)
    assert pid_path.exists()
    assert pid_path.read_text(encoding="ascii").split(":", 1)[0] == "123456"


def test_service_thread_est_non_daemon():
    # BUG-014 : avec daemon=True, le process se terminait des la fin de
    # serve_forever() en TUANT le thread avant la fin de son travail -- le
    # respawn du restart ne naissait jamais (mesure E2E : port mort apres
    # /server/restart). La factory garantit non-daemon PAR CONSTRUCTION.
    t = mon._service_thread(lambda: None, ())
    assert t.daemon is False


def test_routes_stop_et_restart_passent_par_service_thread(server_obj, monkeypatch):
    # Les routes doivent creer leur thread via _service_thread (et donc
    # heriter du non-daemon) -- on remplace la factory par un enregistreur
    # inoffensif : le vrai target n'est jamais lance (le serveur survit).
    url, srv = server_obj
    captured = []

    class _NoopThread:
        def start(self):
            pass

    def recording_factory(target, args):
        captured.append(target.__name__)
        return _NoopThread()

    monkeypatch.setattr(mon, "_service_thread", recording_factory)
    token = _csrf_token(url)
    _post(url + "/server/stop", {"csrf_token": token})
    token = _csrf_token(url)
    _post(url + "/server/restart", {"csrf_token": token})
    assert captured == ["_stop_server_thread", "_restart_server_thread"]


def test_spawn_detached_monitor_survit_a_un_log_verrouille(tmp_path, monkeypatch):
    # BUG-014 (cause racine mesuree) : la redirection shell '>>' du monitor
    # courant tient monitor_console.log en verrou EXCLUSIF -> open('ab') leve
    # PermissionError et le respawn ne naissait jamais. Le spawn doit REPLIER
    # sur DEVNULL et spawner quand meme.
    captured = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kw):
        captured["stdout"] = kw.get("stdout")
        return FakeProc()

    monkeypatch.setattr(mon.subprocess, "Popen", fake_popen)
    # log_path dont le parent est un FICHIER -> open('ab') leve OSError a coup sur
    bad_parent = tmp_path / "pas_un_dossier.txt"
    bad_parent.write_text("x", encoding="ascii")
    locked_log = bad_parent / "respawn.log"

    pid = mon._spawn_detached_monitor(["python", "-u", "main.py"], locked_log, tmp_path)
    assert pid == 4242
    assert captured["stdout"] == mon.subprocess.DEVNULL


def test_restart_thread_ecrit_l_erreur_au_lieu_de_l_avaler(tmp_path, monkeypatch):
    # M9 signaler-pas-masquer : si le respawn echoue, l'erreur DOIT laisser une
    # trace (logs/monitor_respawn_error.log), jamais un pass silencieux.
    def boom(cmd, log_path, cwd):
        raise OSError("respawn impossible (simule)")

    monkeypatch.setattr(mon, "_spawn_detached_monitor", boom)
    mon._restart_server_thread([None], tmp_path, 8765, "127.0.0.1")
    err = tmp_path / "logs" / "monitor_respawn_error.log"
    assert err.exists()
    assert "respawn ECHEC" in err.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Lot 7 -- Paper pilotable depuis l'UI (/paper). AUCUN vrai process paper    #
#  n'est lance : _spawn_paper_detached est TOUJOURS mocke. Identite PID       #
#  (BUG-009 : Windows recycle les PID) et verrou de log (BUG-014) verifies    #
#  explicitement, comme pour le monitor. `server_obj` force root=tmp_path --  #
#  jamais run/paper.pid ni logs/ du VRAI projet touches par ces tests.        #
# --------------------------------------------------------------------------- #
def test_route_paper_get_arrete_par_defaut_affiche_formulaire(server_obj):
    url, srv = server_obj
    code, page = _get(url + "/paper")
    assert code == 200
    assert "ARRÊTÉ" in page
    assert "action='/paper'" in page
    assert "name='csrf_token'" in page
    assert "name='strategy'" in page
    assert "Démarrer le paper trading" in page
    assert "name='source'" not in page  # paper = Kraken only, jamais de source


def test_route_paper_nav_active_et_habilitee(server_obj):
    url, srv = server_obj
    code, page = _get(url + "/paper")
    assert code == 200
    assert "<a class='tab active' href='/paper'>Paper</a>" in page


def test_route_paper_post_sans_csrf_rejete(server_obj):
    url, srv = server_obj
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(url + "/paper", {"action": "start", "strategy": "sma"})
    assert exc.value.code == 403


def test_route_paper_post_start_invalide_reaffiche_formulaire_sans_spawn(
    server_obj, monkeypatch,
):
    url, srv = server_obj

    def boom(*a, **k):
        raise AssertionError("le spawn ne doit PAS etre appele sur un formulaire invalide")
    monkeypatch.setattr(mon, "_spawn_paper_detached", boom)

    token = _csrf_token(url)
    code, page = _post(url + "/paper", {
        "csrf_token": token, "action": "start", "strategy": "n-existe-pas",
    })
    assert code == 200
    assert "Stratégie inconnue" in page
    assert "ARRÊTÉ" in page


def test_route_paper_post_start_lance_process_et_ecrit_pid(
    server_obj, monkeypatch, tmp_path,
):
    url, srv = server_obj
    spawned = []

    def fake_spawn(cmd, log_path, cwd):
        spawned.append((cmd, log_path, cwd))
        return 555555
    monkeypatch.setattr(mon, "_spawn_paper_detached", fake_spawn)

    token = _csrf_token(url)
    code, page = _post(url + "/paper", {
        "csrf_token": token, "action": "start",
        "strategy": "rsi", "symbol": "BTC/USD", "timeframe": "15m",
        "stop_loss": "5", "take_profit": "10", "trailing_stop": "8",
        "position_sizing": "none",
    })
    assert code == 200
    assert "EN COURS" in page
    assert "Paper trading demarre" in page

    assert spawned, "le paper aurait du etre spawn (mocke)"
    cmd, log_path, cwd = spawned[0]
    assert "paper" in cmd
    assert "-u" in cmd                     # flush immediat (autopsie possible, BUG-014)
    assert "--strategy" in cmd and cmd[cmd.index("--strategy") + 1] == "rsi"
    assert "--symbol" in cmd and cmd[cmd.index("--symbol") + 1] == "BTC/USD"
    assert log_path.name == "paper_ui.log"  # log DEDIE, jamais paper_console.log (BUG-014)
    for token_ in cmd[2:]:
        assert "live" not in str(token_).lower()  # garde-fou paper-only, jamais construit

    pid_path = tmp_path / "run" / "paper.pid"
    assert pid_path.exists()
    assert pid_path.read_text(encoding="ascii").split(":", 1)[0] == "555555"


def test_route_paper_post_start_concurrence_un_seul_spawn(
    server_obj, monkeypatch, tmp_path,
):
    """BUG-016 (P2, meme patron que BUG-015 sur /live/start) : deux POST
    /paper CONCURRENTS (2 threads), action="start", ne doivent produire
    QU'UN SEUL spawn -- le second thread doit trouver "paper deja en cours"
    et etre refuse. SANS le verrou (_paper_start_lock, trading/monitor.py),
    les deux threads peuvent tous deux lire "aucun paper en cours" (via
    _paper_status_view au sommet de _paper_post, puis a nouveau juste avant
    le spawn) avant que l'un des deux ait ecrit run/paper.pid -- meme race
    TOCTOU que BUG-015 (gate independante Lot 8, repere le meme jour,
    docs/audit/GATE_LOT8_LIVE.md FAIL-1). Ce test repete le scenario 10x
    pour prouver le meme determinisme AVEC le fix (une seule execution peut
    "gagner" la course par hasard meme sans verrou).

    `_spawn_paper_detached` est mocke (aucun process reel) et introduit un
    `time.sleep` pour ELARGIR la fenetre TOCTOU (meme recette que le test
    live `test_route_live_start_concurrence_un_seul_spawn_reel`) -- sans ce
    sleep, le GIL peut masquer la race sur une machine rapide sans jamais la
    reproduire. `lancer.is_our_process` est force a True des qu'un pid
    existe : isole precisement la fenetre testee (spawn -> pid file,
    protegee par le verrou) de la mecanique d'identite psutil (BUG-009,
    deja couverte ailleurs) -- un pid fictif de test ne correspond a aucun
    VRAI process OS, donc sans ce patch is_our_process ne confirmerait
    jamais "en cours" et les deux threads spawneraient toujours, quel que
    soit le verrou.
    """
    import time as _time

    url, srv = server_obj
    token = _csrf_token(url)
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, name, ts=None: pid is not None)

    pid_path = tmp_path / "run" / "paper.pid"

    for essai in range(10):
        next_pid = [700000 + essai]
        calls = []

        def fake_spawn(cmd, log_path, cwd):
            _time.sleep(0.05)  # elargit la fenetre TOCTOU (cf. docstring)
            next_pid[0] += 1
            calls.append(next_pid[0])
            return next_pid[0]
        monkeypatch.setattr(mon, "_spawn_paper_detached", fake_spawn)

        results = []

        def _start():
            code, page = _post(url + "/paper", {
                "csrf_token": token, "action": "start", "strategy": "sma",
            })
            results.append((code, page))

        t1 = threading.Thread(target=_start)
        t2 = threading.Thread(target=_start)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert len(results) == 2, f"essai {essai}: une requete n'a pas repondu"
        assert all(code == 200 for code, _ in results)
        assert len(calls) == 1, (
            f"essai {essai}: spawns = {len(calls)} (attendu 1 -- "
            f"BUG-016 : race TOCTOU sur 'un seul paper trading a la fois')"
        )
        # Les deux reponses convergent vers "EN COURS" (le gagnant apres son
        # propre spawn, le perdant apres avoir constate qu'un paper tournait
        # deja) -- aucune des deux ne relance le formulaire "ARRETE".
        assert all("EN COURS" in page for _, page in results)

        # Nettoyage entre essais (equivalent d'un /paper stop) pour que le
        # prochain essai reparte d'un etat "aucun paper en cours".
        pid_path.unlink(missing_ok=True)


def test_route_paper_post_start_refuse_si_deja_en_cours(
    server_obj, monkeypatch, tmp_path,
):
    url, srv = server_obj
    (tmp_path / "run").mkdir(exist_ok=True)
    (tmp_path / "run" / "paper.pid").write_text("424242:1700000000.0", encoding="ascii")
    monkeypatch.setattr(lancer, "is_our_process", lambda pid, name, ts=None: True)

    def boom(*a, **k):
        raise AssertionError("un 2e paper ne doit JAMAIS etre spawn (un seul a la fois)")
    monkeypatch.setattr(mon, "_spawn_paper_detached", boom)

    token = _csrf_token(url)
    code, page = _post(url + "/paper", {
        "csrf_token": token, "action": "start", "strategy": "sma",
    })
    assert code == 200
    assert "deja" in page.lower()
    assert "EN COURS" in page


def test_route_paper_post_start_pid_recycle_traite_comme_arrete(
    server_obj, monkeypatch, tmp_path,
):
    # BUG-009 : un PID vivant-mais-RECYCLE par un process tiers n'est PAS "en
    # cours" -- le demarrage doit rester POSSIBLE et le pid file rance nettoye.
    url, srv = server_obj
    (tmp_path / "run").mkdir(exist_ok=True)
    (tmp_path / "run" / "paper.pid").write_text("999999999:1700000000.0", encoding="ascii")
    monkeypatch.setattr(lancer, "is_our_process", lambda pid, name, ts=None: False)
    monkeypatch.setattr(mon, "_spawn_paper_detached", lambda cmd, log_path, cwd: 777777)

    token = _csrf_token(url)
    code, page = _post(url + "/paper", {
        "csrf_token": token, "action": "start", "strategy": "sma",
    })
    assert code == 200
    assert "EN COURS" in page
    assert "deja" not in page.lower()

    pid_path = tmp_path / "run" / "paper.pid"
    assert pid_path.read_text(encoding="ascii").split(":", 1)[0] == "777777"


def test_route_paper_post_start_echec_spawn_trace_erreur_et_l_affiche(
    server_obj, monkeypatch, tmp_path,
):
    # M9 signaler-pas-masquer : un spawn en echec DOIT laisser une trace ET
    # etre affiche a l'utilisateur, jamais avale silencieusement.
    url, srv = server_obj

    def boom(cmd, log_path, cwd):
        raise OSError("spawn impossible (simule)")
    monkeypatch.setattr(mon, "_spawn_paper_detached", boom)

    token = _csrf_token(url)
    code, page = _post(url + "/paper", {
        "csrf_token": token, "action": "start", "strategy": "sma",
    })
    assert code == 200
    assert "chec du d" in page.lower() or "echec" in page.lower()
    err = tmp_path / "logs" / "paper_ui_error.log"
    assert err.exists()
    assert "demarrage paper ECHEC" in err.read_text(encoding="utf-8")

    pid_path = tmp_path / "run" / "paper.pid"
    assert not pid_path.exists()


def test_route_paper_post_stop_sans_process_en_cours(server_obj):
    url, srv = server_obj
    token = _csrf_token(url)
    code, page = _post(url + "/paper", {"csrf_token": token, "action": "stop"})
    assert code == 200
    assert "aucun paper trading en cours" in page.lower()


def test_route_paper_post_stop_arrete_process_identite_confirmee(
    server_obj, monkeypatch, tmp_path,
):
    url, srv = server_obj
    (tmp_path / "run").mkdir(exist_ok=True)
    (tmp_path / "run" / "paper.pid").write_text("424242:1700000000.0", encoding="ascii")
    monkeypatch.setattr(lancer, "is_our_process", lambda pid, name, ts=None: True)
    terminated = []
    monkeypatch.setattr(lancer, "terminate_pid", lambda pid, timeout=5.0: terminated.append(pid) or True)

    token = _csrf_token(url)
    code, page = _post(url + "/paper", {"csrf_token": token, "action": "stop"})
    assert code == 200
    assert "ARRÊTÉ" in page
    assert "conserve" in page.lower()  # honnete : historique preserve (L3)
    assert terminated == [424242]

    pid_path = tmp_path / "run" / "paper.pid"
    assert not pid_path.exists()


def test_route_paper_post_stop_pid_recycle_ne_termine_jamais(
    server_obj, monkeypatch, tmp_path,
):
    # BUG-009, cas symetrique du start : un PID recycle n'est jamais "arrete"
    # (terminate_pid ne doit JAMAIS etre appele sur une identite non confirmee).
    url, srv = server_obj
    (tmp_path / "run").mkdir(exist_ok=True)
    (tmp_path / "run" / "paper.pid").write_text("999999999:1700000000.0", encoding="ascii")
    monkeypatch.setattr(lancer, "is_our_process", lambda pid, name, ts=None: False)

    def boom(*a, **k):
        raise AssertionError("terminate_pid ne doit PAS etre appele sur un PID recycle")
    monkeypatch.setattr(lancer, "terminate_pid", boom)

    token = _csrf_token(url)
    code, page = _post(url + "/paper", {"csrf_token": token, "action": "stop"})
    assert code == 200
    assert "aucun paper trading en cours" in page.lower()


def test_route_paper_post_action_inconnue(server_obj):
    url, srv = server_obj
    token = _csrf_token(url)
    code, page = _post(url + "/paper", {"csrf_token": token, "action": "n-existe-pas"})
    assert code == 200
    assert "action inconnue" in page.lower()


def test_route_paper_ne_construit_jamais_une_commande_live(
    server_obj, monkeypatch, tmp_path,
):
    # Garde-fou explicite du perimetre (brief) : meme avec des champs
    # adverses, la commande passe par assert_paper_only (RuntimeError si
    # jamais "live" apparaissait) -- ici on verifie le chemin nominal complet.
    url, srv = server_obj
    spawned = []
    monkeypatch.setattr(
        mon, "_spawn_paper_detached",
        lambda cmd, log_path, cwd: spawned.append(cmd) or 111111,
    )
    token = _csrf_token(url)
    _post(url + "/paper", {
        "csrf_token": token, "action": "start",
        "strategy": "macd", "symbol": "ETH/USD", "timeframe": "1h",
        "position_sizing": "vol", "target_vol": "40",
    })
    assert spawned
    for token_ in spawned[0][2:]:
        assert "live" not in str(token_).lower()
    assert "--position-sizing" in spawned[0]
    assert "vol" in spawned[0]
    assert "--target-vol" in spawned[0]


# --------------------------------------------------------------------------- #
#  IYC_DISABLE_PAPER_CONTROL -- deploiement Docker multi-conteneurs (paper et #
#  monitor = 2 conteneurs SEPARES partageant un volume, docs/DEPLOY_DOCKER.md #
#  §7) : le bouton /paper spawnerait un SECOND paper isole du volume, a       #
#  l'interieur du conteneur monitor. Ferme cote SERVEUR (pas seulement en     #
#  HTML) -- un POST forge ne doit RIEN spawner/tuer quand le flag est actif.  #
# --------------------------------------------------------------------------- #
def test_route_paper_get_flag_actif_retire_formulaire_et_affiche_encart(
    server_obj, monkeypatch,
):
    url, srv = server_obj
    monkeypatch.setenv("IYC_DISABLE_PAPER_CONTROL", "1")
    code, page = _get(url + "/paper")
    assert code == 200
    assert "ARRÊTÉ" in page                       # statut reste consultable
    assert "Démarrer le paper trading" not in page
    assert "name='strategy'" not in page
    assert "Pilotage désactivé" in page
    assert "docker compose" in page


def test_route_paper_post_start_flag_actif_ne_spawne_pas(
    server_obj, monkeypatch, tmp_path,
):
    url, srv = server_obj

    def boom(*a, **k):
        raise AssertionError("le spawn ne doit PAS etre appele, flag actif")
    monkeypatch.setattr(mon, "_spawn_paper_detached", boom)

    token = _csrf_token(url)
    monkeypatch.setenv("IYC_DISABLE_PAPER_CONTROL", "1")
    code, page = _post(url + "/paper", {
        "csrf_token": token, "action": "start", "strategy": "sma",
    })
    assert code == 200
    assert "Pilotage désactivé" in page
    # aucun run/paper.pid ne doit avoir ete ecrit (aucun spawn n'a eu lieu) --
    # server_obj force mon.project_root() -> tmp_path.
    assert not (tmp_path / "run" / "paper.pid").exists()


def test_route_paper_post_stop_flag_actif_n_appelle_pas_terminate_pid(
    server_obj, monkeypatch, tmp_path,
):
    url, srv = server_obj
    # Prepare un paper "en cours" (identite confirmee) pour s'assurer que le
    # refus intervient AVANT toute lecture de status/pid -- pas seulement
    # parce qu'il n'y avait "rien a arreter".
    pid_path = tmp_path / "run" / "paper.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("424242:1700000000.0", encoding="ascii")
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, name, ts=None: True)

    def boom(*a, **k):
        raise AssertionError("terminate_pid ne doit PAS etre appele, flag actif")
    monkeypatch.setattr(lancer, "terminate_pid", boom)

    token = _csrf_token(url)
    monkeypatch.setenv("IYC_DISABLE_PAPER_CONTROL", "1")
    code, page = _post(url + "/paper", {"csrf_token": token, "action": "stop"})
    assert code == 200
    assert "Pilotage désactivé" in page
    assert pid_path.exists()  # jamais retire (aucun stop n'a eu lieu)


def test_route_paper_flag_absent_comportement_lot7_strictement_inchange(
    server_obj, monkeypatch,
):
    # Non-regression explicite (M9/L3) : sans la variable d'environnement, le
    # formulaire et le bouton restent presents -- comportement local inchange.
    url, srv = server_obj
    monkeypatch.delenv("IYC_DISABLE_PAPER_CONTROL", raising=False)
    code, page = _get(url + "/paper")
    assert code == 200
    assert "Démarrer le paper trading" in page
    assert "Pilotage désactivé" not in page

    spawned = []
    monkeypatch.setattr(
        mon, "_spawn_paper_detached",
        lambda cmd, log_path, cwd: spawned.append(cmd) or 999999,
    )
    token = _csrf_token(url)
    code, page = _post(url + "/paper", {
        "csrf_token": token, "action": "start", "strategy": "sma",
    })
    assert code == 200
    assert spawned, "le paper aurait du etre spawn (flag absent)"


def test_paper_control_disabled_parsing_variantes(monkeypatch):
    # Complement du test pur (test_paper_page.py) : verifie la meme fonction
    # via le point d'entree reellement utilise par _paper_get/_paper_post
    # (os.environ.get), pas seulement en argument direct.
    import trading.paper_page as pp

    monkeypatch.delenv("IYC_DISABLE_PAPER_CONTROL", raising=False)
    assert pp.paper_control_disabled(os.environ.get("IYC_DISABLE_PAPER_CONTROL", "")) is False

    monkeypatch.setenv("IYC_DISABLE_PAPER_CONTROL", "YES")
    assert pp.paper_control_disabled(os.environ.get("IYC_DISABLE_PAPER_CONTROL", "")) is True


def test_spawn_paper_detached_survit_a_un_log_verrouille(tmp_path, monkeypatch):
    # Meme recette que _spawn_detached_monitor (BUG-014) : repli DEVNULL si
    # le log dedie logs/paper_ui.log est inaccessible en ecriture.
    captured = {}

    class FakeProc:
        pid = 8181

    def fake_popen(cmd, **kw):
        captured["stdout"] = kw.get("stdout")
        return FakeProc()

    monkeypatch.setattr(mon.subprocess, "Popen", fake_popen)
    bad_parent = tmp_path / "pas_un_dossier.txt"
    bad_parent.write_text("x", encoding="ascii")
    locked_log = bad_parent / "paper_ui.log"

    pid = mon._spawn_paper_detached(["python", "-u", "main.py", "paper"], locked_log, tmp_path)
    assert pid == 8181
    assert captured["stdout"] == mon.subprocess.DEVNULL
