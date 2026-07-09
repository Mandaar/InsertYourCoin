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
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from trading import monitor as mon
from trading.options import read_options
from trading.stats import StatsRecorder
from trading.strategies import STRATEGIES


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
        srv.shutdown()


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
    assert "Strategie inconnue" in page
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
    assert "deja en cours" in page
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
    assert "Strategie inconnue" in page
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
    assert "Test (hors-echantillon)" in report


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
    assert "Correlation moyenne" in report


def test_route_research_subnav_links_all_four_screens(server):
    code, page = _get(server + "/research/backtest")
    assert code == 200
    for href in ("/research/backtest", "/research/compare",
                "/research/optimize", "/research/portfolio"):
        assert f"href='{href}'" in page


@pytest.mark.parametrize("path,fields", [
    ("/research/compare", {}),
    ("/research/optimize", {"strategy": "sma"}),
    ("/research/portfolio", {"strategy": "sma"}),
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
    assert "deja en cours" in page
    assert "class='job-panel'" in page

    release.set()
