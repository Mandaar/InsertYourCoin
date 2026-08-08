"""
Tests d'INTEGRATION HTTP du Lot 8 (Live verrouille) -- VRAI serveur, port
ephemere, cf. docs/design/LOT8_LIVE_SPEC.md §5.3. AUCUN reseau, AUCUN
process reel : `trading.live_control.spawn_live_detached` est TOUJOURS
monkeypatche par un "enregistreur" qui capture la commande + le stdin pipe
sans jamais lancer de process. `keys_configured`, `run_web_check`,
`lancer.is_our_process`, `lancer.terminate_pid` sont monkeypatches selon le
scenario (patron `tests/test_monitor_server.py`).
"""
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

import config
import lancer
from trading import live_control
from trading import monitor as mon

_ATTEST_ALL = {
    "attest_no_withdraw": "1",
    "attest_paper_done": "1",
    "attest_caps_read": "1",
}


def _teardown_server(srv):
    """Meme garde-fou BUG-012 que tests/test_monitor_server.py (methodes NON
    liees, sur la CLASSE -- ferme le VRAI socket meme si un test a
    monkeypatche shutdown()/server_close() sur l'instance)."""
    try:
        type(srv).shutdown(srv)
    finally:
        type(srv).server_close(srv)


@pytest.fixture()
def live_server(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.options.OPTIONS_PATH",
                        lambda: tmp_path / "options.json")
    # root = project_root() est capture UNE FOIS a la construction du
    # serveur -- monkeypatcher AVANT build_monitor_server (patron
    # `server_obj` de tests/test_monitor_server.py) pour que run/live.pid,
    # run/live.json, logs/live_console.log vivent tous sous tmp_path.
    monkeypatch.setattr(mon, "project_root", lambda: tmp_path)
    srv = mon.build_monitor_server(port=0,
                                   stats_path=tmp_path / "s.csv",
                                   log_path=tmp_path / "l.log",
                                   state_path=tmp_path / "st.json")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    finally:
        _teardown_server(srv)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _post(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _csrf_token(base_url):
    _, page = _get(base_url + "/options")
    return re.search(r"name='csrf_token'[^>]*value='([0-9a-f]+)'", page).group(1)


def _extract_nonce(page):
    m = re.search(r"name='nonce' value='([0-9a-f]+)'", page)
    assert m, "aucun nonce trouve dans la page de recap"
    return m.group(1)


def _set_check_ok(monkeypatch, base, ok=True):
    fake_result = {"ok": ok, "category": None if ok else "network",
                   "message": None, "price": 100.0, "symbol": "ETH/USD",
                   "time": "12:00:00"}
    monkeypatch.setattr(mon, "run_web_check", lambda symbol: fake_result)
    _get(base + "/check?run=1")


def _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True):
    """Force l'etat des 3 pre-requis (A) pour le test courant. `check=None`
    laisse `_last_check` a son etat neutre (jamais verifie cette session)."""
    monkeypatch.setattr(mon, "keys_configured", lambda: keys)
    if check is not None:
        _set_check_ok(monkeypatch, base, ok=check)
    state_file = tmp_path / "st.json"
    if paper:
        state_file.write_text("{}")
    elif state_file.exists():
        state_file.unlink()


def _arm_fields(csrf_token, **extra):
    fields = dict(_ATTEST_ALL, csrf_token=csrf_token, mode="reel",
                 strategy="sma", symbol="ETH/USD", timeframe="1h")
    fields.update(extra)
    return fields


def _record_spawn(monkeypatch):
    calls = []

    def _fake_spawn(cmd, log_path, cwd, stdin_bytes=None):
        calls.append({"cmd": cmd, "stdin_bytes": stdin_bytes})
        return 999999

    monkeypatch.setattr(live_control, "spawn_live_detached", _fake_spawn)
    return calls


# --------------------------------------------------------------------------- #
#  GET /live -- le mur (spec §1.1) + absence de la nav principale (N7)        #
# --------------------------------------------------------------------------- #
def test_route_live_get_mur(live_server):
    base, _ = live_server
    code, page = _get(base + "/live")
    assert code == 200
    assert "ARGENT RÉEL" in page
    assert f"{config.MAX_TRADE_VALUE_USD:g}" in page
    assert f"{config.MAX_POSITION_VALUE_USD:g}" in page
    assert "name='mode_display' value='dry' checked" in page
    assert "Local 127.0.0.1" in page  # pill hote -- meme coquille que tout le reste


def test_route_live_absente_de_la_nav_principale(live_server):
    base, _ = live_server
    _, page = _get(base + "/live")
    nav_part = page.split("<div class='iyc-page'>", 1)[0]
    assert "href='/live'" not in nav_part
    assert "class='tab active'" not in nav_part


# --------------------------------------------------------------------------- #
#  POST /live/arm -- round-trip 1 (spec §1.3)                                 #
# --------------------------------------------------------------------------- #
def test_route_live_arm_sans_csrf_403(live_server):
    base, _ = live_server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(base + "/live/arm", {"mode": "reel"})
    assert exc.value.code == 403


def test_route_live_arm_prerequis_cles_manquantes_refuse(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=False, check=True, paper=True)
    calls = _record_spawn(monkeypatch)
    token = _csrf_token(base)
    code, page = _post(base + "/live/arm", _arm_fields(token))
    assert code == 200
    assert "name='nonce'" not in page
    assert "Clés API manquantes" in page
    assert calls == []


def test_route_live_arm_check_non_ok_refuse(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=False, paper=True)
    calls = _record_spawn(monkeypatch)
    token = _csrf_token(base)
    code, page = _post(base + "/live/arm", _arm_fields(token))
    assert code == 200
    assert "name='nonce'" not in page
    assert calls == []


def test_route_live_arm_paper_jamais_lance_refuse(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=False)
    calls = _record_spawn(monkeypatch)
    token = _csrf_token(base)
    code, page = _post(base + "/live/arm", _arm_fields(token))
    assert code == 200
    assert "name='nonce'" not in page
    assert calls == []


def test_route_live_arm_attestation_manquante_refuse(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    calls = _record_spawn(monkeypatch)
    token = _csrf_token(base)
    fields = _arm_fields(token)
    del fields["attest_caps_read"]  # une seule case manquante suffit a refuser
    code, page = _post(base + "/live/arm", fields)
    assert code == 200
    assert "name='nonce'" not in page
    assert "attestation" in page.lower()
    assert calls == []


def test_route_live_arm_tout_ok_emet_nonce_et_recap(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    token = _csrf_token(base)
    code, page = _post(base + "/live/arm", _arm_fields(token))
    assert code == 200
    assert "Confirmer le RÉEL" in page
    assert "name='nonce' value='" in page
    assert "name='phrase'" in page
    assert f"{config.MAX_TRADE_VALUE_USD:g}" in page


# --------------------------------------------------------------------------- #
#  POST /live/start -- round-trip 2 reel (spec §1.4) + dry-run (spec §1.5)    #
# --------------------------------------------------------------------------- #
def test_route_live_start_sans_csrf_403(live_server):
    base, _ = live_server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(base + "/live/start", {"mode": "dry"})
    assert exc.value.code == 403


def test_route_live_start_sans_nonce_refuse_sans_spawn(live_server, monkeypatch):
    base, _ = live_server
    calls = _record_spawn(monkeypatch)
    token = _csrf_token(base)
    code, page = _post(base + "/live/start", {
        "csrf_token": token, "mode": "reel", "phrase": "OUI JE CONFIRME",
    })
    assert code == 200
    assert calls == []


def test_route_live_start_phrase_incorrecte_refuse_sans_spawn(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    token = _csrf_token(base)
    _, arm_page = _post(base + "/live/arm", _arm_fields(token))
    nonce = _extract_nonce(arm_page)
    calls = _record_spawn(monkeypatch)
    code, page = _post(base + "/live/start", {
        "csrf_token": token, "mode": "reel", "nonce": nonce, "phrase": "oui",
    })
    assert code == 200
    assert calls == []
    assert "Refusé" in page or "Phrase incorrecte" in page


def test_route_live_start_nonce_consomme_pas_de_rejeu(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    token = _csrf_token(base)
    _, arm_page = _post(base + "/live/arm", _arm_fields(token))
    nonce = _extract_nonce(arm_page)
    calls = _record_spawn(monkeypatch)

    start_fields = {"csrf_token": token, "mode": "reel", "nonce": nonce,
                    "phrase": "OUI JE CONFIRME"}
    code1, _ = _post(base + "/live/start", start_fields)
    assert code1 == 200
    assert len(calls) == 1

    code2, _ = _post(base + "/live/start", start_fields)  # rejeu du meme POST
    assert code2 == 200
    assert len(calls) == 1  # spawn NON rappele


def test_route_live_start_mode_absent_ne_demarre_rien(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    calls = _record_spawn(monkeypatch)
    token = _csrf_token(base)
    code, page = _post(base + "/live/start", {"csrf_token": token})
    assert code == 200
    assert calls == []


def test_route_live_start_reel_spawn_detache_execute_et_pipe_phrase(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    token = _csrf_token(base)
    _, arm_page = _post(base + "/live/arm", _arm_fields(token))
    nonce = _extract_nonce(arm_page)
    calls = _record_spawn(monkeypatch)

    code, page = _post(base + "/live/start", {
        "csrf_token": token, "mode": "reel", "nonce": nonce,
        "phrase": "OUI JE CONFIRME",
    })
    assert code == 200
    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert "live" in cmd
    assert "--execute" in cmd
    assert calls[0]["stdin_bytes"] == b"OUI JE CONFIRME\n"


def test_route_live_start_reel_refuse_si_cles_disparues_au_start(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    token = _csrf_token(base)
    _, arm_page = _post(base + "/live/arm", _arm_fields(token))
    nonce = _extract_nonce(arm_page)
    calls = _record_spawn(monkeypatch)

    # Les cles "disparaissent" ENTRE l'armement et le start (re-validation N10).
    monkeypatch.setattr(mon, "keys_configured", lambda: False)
    code, page = _post(base + "/live/start", {
        "csrf_token": token, "mode": "reel", "nonce": nonce,
        "phrase": "OUI JE CONFIRME",
    })
    assert code == 200
    assert calls == []


def test_route_live_un_seul_live(live_server, monkeypatch):
    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    token = _csrf_token(base)
    _, arm_page = _post(base + "/live/arm", _arm_fields(token))
    nonce = _extract_nonce(arm_page)
    calls = _record_spawn(monkeypatch)
    monkeypatch.setattr(live_control, "live_identity",
                        lambda root: (123456, True, 1000.0))

    code, page = _post(base + "/live/start", {
        "csrf_token": token, "mode": "reel", "nonce": nonce,
        "phrase": "OUI JE CONFIRME",
    })
    assert code == 200
    assert calls == []


def test_route_live_start_concurrence_un_seul_spawn_reel(live_server, monkeypatch):
    """BUG-015 (P0, gate independante Lot 8 -- docs/audit/GATE_LOT8_LIVE.md
    FAIL-1) : deux POST /live/start CONCURRENTS (2 threads), chacun porteur
    d'un nonce DISTINCT et INDIVIDUELLEMENT VALIDE (deux armements legitimes,
    ex. deux onglets), ne doivent produire QU'UN SEUL spawn reel -- le second
    thread doit trouver 'live deja en cours' et etre refuse. SANS le verrou
    (_live_start_lock, trading/monitor.py), la gate independante a mesure
    2 spawns 10/10 -- ce test repete le scenario 10x pour prouver le meme
    determinisme AVEC le fix.

    `spawn_live_detached` est mocke (aucun process reel, patron
    `_record_spawn` ci-dessus) et introduit un `time.sleep` pour ELARGIR la
    fenetre TOCTOU (comme le PoC de la gate) -- sans ce sleep, le GIL peut
    masquer la race sur une machine rapide sans jamais la reproduire.

    `lancer.is_our_process` est force a True des qu'un pid existe (meme
    patron que `test_route_live_bandeau_lit_mode_du_sidecar` ci-dessus) :
    isole precisement la fenetre testee (spawn -> pid file, protegee par le
    verrou) de la mecanique d'identite psutil (deja couverte par ailleurs,
    BUG-009/N9) -- un pid fictif de test ne correspond a aucun VRAI process
    OS, donc sans ce patch `live_identity` ne confirmerait jamais "en cours"
    et les deux threads spawneraient toujours, quel que soit le verrou.
    """
    import time as _time

    base, tmp_path = live_server
    _set_prereqs(monkeypatch, base, tmp_path, keys=True, check=True, paper=True)
    token = _csrf_token(base)
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: pid is not None)

    pid_path = tmp_path / "run" / "live.pid"
    sidecar_path = tmp_path / "run" / "live.json"

    for essai in range(10):
        next_pid = [900000 + essai]
        calls = []

        def _recording_spawn(cmd, log_path, cwd, stdin_bytes=None):
            _time.sleep(0.05)  # elargit la fenetre TOCTOU (cf. docstring)
            next_pid[0] += 1
            calls.append(next_pid[0])
            return next_pid[0]

        monkeypatch.setattr(live_control, "spawn_live_detached", _recording_spawn)

        # Deux armements legitimes -> deux nonces DISTINCTS (deux onglets).
        _, arm_page_1 = _post(base + "/live/arm", _arm_fields(token))
        nonce_1 = _extract_nonce(arm_page_1)
        _, arm_page_2 = _post(base + "/live/arm", _arm_fields(token))
        nonce_2 = _extract_nonce(arm_page_2)
        assert nonce_1 != nonce_2

        results = []

        def _start(nonce):
            code, page = _post(base + "/live/start", {
                "csrf_token": token, "mode": "reel", "nonce": nonce,
                "phrase": "OUI JE CONFIRME",
            })
            results.append((code, page))

        t1 = threading.Thread(target=_start, args=(nonce_1,))
        t2 = threading.Thread(target=_start, args=(nonce_2,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert len(results) == 2, f"essai {essai}: une requete n'a pas repondu"
        assert all(code == 200 for code, _ in results)
        assert len(calls) == 1, (
            f"essai {essai}: spawns reels = {len(calls)} (attendu 1 -- "
            f"BUG-015 : race TOCTOU sur 'un seul live a la fois')"
        )
        # Les deux reponses convergent vers la meme vue "En cours" (le
        # gagnant apres son propre spawn, le perdant apres avoir constate
        # qu'un live tournait deja) -- aucune des deux ne relance le mur.
        assert all("En cours" in page for _, page in results)

        # Nettoyage entre essais (equivalent d'un /live/stop) pour que le
        # prochain essai reparte d'un etat "aucun live en cours".
        pid_path.unlink(missing_ok=True)
        sidecar_path.unlink(missing_ok=True)


def test_route_live_start_dry_run_exige_cles_pas_de_phrase(live_server, monkeypatch):
    base, tmp_path = live_server
    token = _csrf_token(base)
    calls = _record_spawn(monkeypatch)

    monkeypatch.setattr(mon, "keys_configured", lambda: False)
    code, page = _post(base + "/live/start", {
        "csrf_token": token, "mode": "dry", "strategy": "sma",
        "symbol": "ETH/USD", "timeframe": "1h",
    })
    assert code == 200
    assert calls == []

    monkeypatch.setattr(mon, "keys_configured", lambda: True)
    code2, page2 = _post(base + "/live/start", {
        "csrf_token": token, "mode": "dry", "strategy": "sma",
        "symbol": "ETH/USD", "timeframe": "1h",
    })
    assert code2 == 200
    assert len(calls) == 1
    assert "--execute" not in calls[0]["cmd"]
    assert calls[0]["stdin_bytes"] is None


# --------------------------------------------------------------------------- #
#  POST /live/stop (spec §1.7)                                                #
# --------------------------------------------------------------------------- #
def test_route_live_stop_sans_csrf_403(live_server):
    base, _ = live_server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(base + "/live/stop", {})
    assert exc.value.code == 403


def test_route_live_stop_termine_pid_confirme(live_server, monkeypatch):
    base, tmp_path = live_server
    pid_path = tmp_path / "run" / "live.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("123456:1000.0")
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: True)
    terminated = []
    monkeypatch.setattr(lancer, "terminate_pid",
                        lambda pid, timeout=5.0: terminated.append(pid) or True)
    token = _csrf_token(base)
    code, page = _post(base + "/live/stop", {"csrf_token": token})
    assert code == 200
    assert terminated == [123456]
    assert not pid_path.exists()


def test_route_live_stop_refuse_pid_non_confirme(live_server, monkeypatch):
    base, tmp_path = live_server
    pid_path = tmp_path / "run" / "live.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("654321:1000.0")
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: False)
    terminated = []
    monkeypatch.setattr(lancer, "terminate_pid",
                        lambda pid, timeout=5.0: terminated.append(pid) or True)
    token = _csrf_token(base)
    code, page = _post(base + "/live/stop", {"csrf_token": token})
    assert code == 200
    assert terminated == []  # PID non confirme (BUG-009) -- jamais tue
    assert not pid_path.exists()  # nettoye par live_identity (meme patron paper)


# --------------------------------------------------------------------------- #
#  Live EN COURS -- bandeau + journal (spec §1.6/§4)                          #
# --------------------------------------------------------------------------- #
def _mark_live_running(tmp_path, mode="dry"):
    pid_path = tmp_path / "run" / "live.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("111222:1000.0")
    (tmp_path / "run" / "live.json").write_text(json.dumps({
        "mode": mode, "strategy": "sma", "symbol": "ETH/USD",
        "timeframe": "1h", "pid": 111222, "start_ts": 1000.0,
    }))


def test_route_live_bandeau_lit_mode_du_sidecar(live_server, monkeypatch):
    base, tmp_path = live_server
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: True)

    _mark_live_running(tmp_path, mode="reel")
    _, page_reel = _get(base + "/live")
    assert "mode-banner reel" in page_reel
    assert "ARGENT RÉEL" in page_reel

    _mark_live_running(tmp_path, mode="dry")
    _, page_dry = _get(base + "/live")
    assert "mode-banner dry" in page_dry
    assert "SIMULATION" in page_dry


def test_route_live_journal_lit_live_log_lecture_seule(live_server, monkeypatch):
    base, tmp_path = live_server
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: True)
    _mark_live_running(tmp_path, mode="dry")
    log_path = tmp_path / "live_trades.log"
    log_path.write_text(
        "[2026-08-08 10:00:00] [DRY-RUN] ACHAT prevu : 0.01 ETH @ 100.00\n"
        "[2026-08-08 10:05:00] LiveTrader initialise en mode DRY-RUN\n"
    )
    _, page = _get(base + "/live")
    assert "[DRY-RUN] ACHAT prevu" in page

    before = log_path.read_text()
    _get(base + "/live")  # un 2e GET ne doit RIEN ecrire (lecture seule)
    after = log_path.read_text()
    assert before == after
