"""
Tests du superviseur live conteneurise (Lot 8B, argent reel).
docs/design/LOT8B_LIVE_CONTENEUR_SPEC.md §2.4/§7 -- AUCUN reseau, AUCUN
process reel : `trading.live_control.spawn_live_detached` est TOUJOURS
monkeypatche par un "enregistreur" (patron `tests/test_live_server.py`
`_record_spawn`). `lancer.is_our_process`/`lancer.terminate_pid` sont
monkeypatches pour simuler un enfant "confirme en cours" sans vrai OS pid.

Couvre : les fonctions PURES de trading/live_control.py ajoutees pour Lot 8B
(marqueur d'armement, sentinelle d'arret, statut du superviseur),
trading/live_supervisor.py (supervisor_tick, next_wait_seconds, le handler
SIGTERM, run_supervisor avec max_ticks) et le cablage CLI
(main.py live-arm/live-disarm/live-run).
"""
import io
import signal
import sys
import threading

import pytest

import config
import lancer
import main
from trading import live_control
from trading import live_supervisor


# --------------------------------------------------------------------------- #
#  trading/live_control.py -- fonctions PURES ajoutees pour Lot 8B            #
# --------------------------------------------------------------------------- #
def test_armed_marker_roundtrip(tmp_path):
    params = {"strategy": "sma", "symbol": "ETH/USD", "timeframe": "1h",
             "stop_loss": 5, "take_profit": 10, "trailing_stop": 8,
             "position_sizing": "none", "target_vol": None}
    live_control.write_armed_marker(tmp_path, params, mode="reel",
                                    armed_via="cli-interactive")
    marker = live_control.read_armed_marker(tmp_path)
    assert marker["mode"] == "reel"
    assert marker["strategy"] == "sma"
    assert marker["symbol"] == "ETH/USD"
    assert marker["stop_loss"] == 5
    assert marker["armed_via"] == "cli-interactive"
    assert "armed_at" in marker
    # Grille FIGEE (§2.2) : AUCUNE cle, AUCUNE phrase dans le fichier.
    raw = live_control.armed_marker_path(tmp_path).read_text(encoding="utf-8")
    assert "KRAKEN" not in raw.upper()
    assert "OUI JE CONFIRME" not in raw


def test_armed_marker_ecriture_atomique_tmp_absent_apres(tmp_path):
    live_control.write_armed_marker(
        tmp_path, {"strategy": "sma", "symbol": "ETH/USD", "timeframe": "1h"},
        mode="dry", armed_via="cli-interactive-dry")
    path = live_control.armed_marker_path(tmp_path)
    tmp = path.with_name(path.name + ".tmp")
    assert path.exists()
    assert not tmp.exists()  # os.replace a consomme le fichier temporaire


def test_armed_marker_mode_invalide_refuse(tmp_path):
    with pytest.raises(ValueError):
        live_control.write_armed_marker(
            tmp_path, {"strategy": "sma"}, mode="bogus", armed_via="test")


def test_read_armed_marker_absent_ou_invalide(tmp_path):
    assert live_control.read_armed_marker(tmp_path) is None
    # Un JSON avec un mode hors {reel,dry} n'est PAS un armement valide (C4).
    p = live_control.armed_marker_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"mode": "n\'importe-quoi"}', encoding="utf-8")
    assert live_control.read_armed_marker(tmp_path) is None


def test_remove_armed_marker_idempotent(tmp_path):
    live_control.write_armed_marker(
        tmp_path, {"strategy": "sma"}, mode="dry", armed_via="test")
    live_control.remove_armed_marker(tmp_path)
    assert live_control.read_armed_marker(tmp_path) is None
    live_control.remove_armed_marker(tmp_path)  # 2e appel : pas d'exception


def test_stop_request_roundtrip(tmp_path):
    assert live_control.stop_requested(tmp_path) is False
    live_control.write_stop_request(tmp_path)
    assert live_control.stop_requested(tmp_path) is True
    live_control.clear_stop_request(tmp_path)
    assert live_control.stop_requested(tmp_path) is False
    live_control.clear_stop_request(tmp_path)  # idempotent


def test_live_status_roundtrip(tmp_path):
    assert live_control.read_live_status(tmp_path) is None
    live_control.write_live_status(tmp_path, "en_cours", "pid 123")
    status = live_control.read_live_status(tmp_path)
    assert status["status"] == "en_cours"
    assert status["detail"] == "pid 123"
    assert "updated_ts" in status


# --------------------------------------------------------------------------- #
#  supervisor_tick -- table de decision (§2.4)                                #
# --------------------------------------------------------------------------- #
def _record_spawn(monkeypatch, pid=424242):
    calls = []

    def _fake_spawn(cmd, log_path, cwd, stdin_bytes=None):
        calls.append({"cmd": cmd, "stdin_bytes": stdin_bytes})
        return pid

    monkeypatch.setattr(live_control, "spawn_live_detached", _fake_spawn)
    return calls


def _arm(tmp_path, mode="reel", **extra):
    params = dict(strategy="sma", symbol="ETH/USD", timeframe="1h",
                 stop_loss=5, take_profit=10, trailing_stop=8,
                 position_sizing="none", target_vol=None)
    params.update(extra)
    live_control.write_armed_marker(tmp_path, params, mode=mode,
                                    armed_via="cli-interactive")


def test_tick_desarme_aucun_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    calls = _record_spawn(monkeypatch)
    state = live_supervisor.supervisor_tick(tmp_path, {})
    assert calls == []
    assert state["status"] == "desarme"
    assert live_control.read_live_status(tmp_path)["status"] == "desarme"


def test_tick_arme_reel_spawn_execute_et_pipe_phrase(tmp_path, monkeypatch):
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    _arm(tmp_path, mode="reel")
    calls = _record_spawn(monkeypatch)
    state = live_supervisor.supervisor_tick(tmp_path, {})
    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert "live" in cmd
    assert "--execute" in cmd
    assert calls[0]["stdin_bytes"] == b"OUI JE CONFIRME\n"
    assert state["status"] == "en_cours"
    assert state["ever_spawned"] is True


def test_tick_arme_dry_spawn_sans_execute_ni_phrase(tmp_path, monkeypatch):
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    _arm(tmp_path, mode="dry")
    calls = _record_spawn(monkeypatch)
    state = live_supervisor.supervisor_tick(tmp_path, {})
    assert len(calls) == 1
    assert "--execute" not in calls[0]["cmd"]
    assert calls[0]["stdin_bytes"] is None
    assert state["status"] == "en_cours"


def test_tick_un_seul_enfant_anti_toctou(tmp_path, monkeypatch):
    """BUG-015 : un enfant DEJA confirme en cours (is_our_process True) ->
    AUCUN 2e spawn, la sequence identite->spawn->pid est verrouillee."""
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    _arm(tmp_path, mode="reel")
    pid_path = live_control.live_pid_path(tmp_path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("555555:1000.0")
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: True)
    calls = _record_spawn(monkeypatch)
    state = live_supervisor.supervisor_tick(tmp_path, {})
    assert calls == []  # aucun spawn : l'enfant confirme suffit
    assert state["status"] == "en_cours"
    assert state["consec_failures"] == 0


def test_tick_ne_tue_pas_pid_non_confirme(tmp_path, monkeypatch):
    """BUG-009 : un pid rance (is_our_process False) n'est jamais tue --
    live_identity() le nettoie et le traite comme ARRETE, jamais 'a tuer'."""
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    pid_path = live_control.live_pid_path(tmp_path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("777777:1000.0")
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: False)
    terminated = []
    monkeypatch.setattr(lancer, "terminate_pid",
                        lambda pid, timeout=5.0: terminated.append(pid) or True)
    live_control.write_stop_request(tmp_path)  # branche "arret" -> tente de terminer
    live_supervisor.supervisor_tick(tmp_path, {})
    assert terminated == []


def test_tick_sentinelle_termine_enfant_et_desarme(tmp_path, monkeypatch):
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    _arm(tmp_path, mode="reel")
    pid_path = live_control.live_pid_path(tmp_path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("888888:1000.0")
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: True)
    terminated = []
    monkeypatch.setattr(lancer, "terminate_pid",
                        lambda pid, timeout=5.0: terminated.append(pid) or True)
    live_control.write_stop_request(tmp_path)

    state = live_supervisor.supervisor_tick(tmp_path, {})

    assert terminated == [888888]                    # enfant termine
    assert live_control.read_armed_marker(tmp_path) is None  # desarme (§3.2 point 2)
    assert live_control.stop_requested(tmp_path) is False    # sentinelle efface
    assert state["status"] == "arret_demande"


def test_tick_sigterm_meme_geste_que_sentinelle(tmp_path, monkeypatch):
    """L'exit de run_supervisor (SIGTERM) termine l'enfant SANS aucun ordre
    de vente -- ce module n'a aucun chemin de code qui vend quoi que ce
    soit, la garantie tient par absence de mecanisme, pas par un if."""
    pid_path = live_control.live_pid_path(tmp_path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("999999:1000.0")
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: True)
    terminated = []
    monkeypatch.setattr(lancer, "terminate_pid",
                        lambda pid, timeout=5.0: terminated.append(pid) or True)

    live_supervisor._terminate_confirmed_child(tmp_path)

    assert terminated == [999999]
    assert not pid_path.exists()


def test_tick_cles_absentes_erreur_explicite_pas_de_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: False)
    _arm(tmp_path, mode="reel")
    calls = _record_spawn(monkeypatch)
    state = live_supervisor.supervisor_tick(tmp_path, {})
    assert calls == []
    assert state["status"] == "erreur_cles"
    status = live_control.read_live_status(tmp_path)
    assert status["status"] == "erreur_cles"
    assert "cle" in status["detail"].lower() or "clé" in status["detail"].lower()


def test_tick_enfant_crash_relance_si_arme(tmp_path, monkeypatch):
    """1er tick : spawn initial (pas un crash, ever_spawned passe a True).
    2e tick, MEME marqueur, mais plus aucun enfant confirme (crash simule
    par is_our_process=False) -> RELANCE, et consec_failures s'incremente
    (backoff, §5) -- sans jamais depasser 1 spawn par tick (toujours protege
    par le verrou)."""
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    _arm(tmp_path, mode="reel")
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: False)
    calls = _record_spawn(monkeypatch)

    state = {}
    state = live_supervisor.supervisor_tick(tmp_path, state)
    assert len(calls) == 1
    assert state["consec_failures"] == 0  # 1er demarrage : pas un crash

    state = live_supervisor.supervisor_tick(tmp_path, state)
    assert len(calls) == 2  # relance
    assert state["consec_failures"] == 1  # l'enfant precedent avait disparu -> crash compte


def test_next_wait_seconds_erreur_cles_backoff_fixe():
    wait = live_supervisor.next_wait_seconds({"status": "erreur_cles"})
    assert wait == live_supervisor.KEYS_MISSING_BACKOFF_SEC


def test_next_wait_seconds_echecs_backoff_exponentiel_plafonne():
    w1 = live_supervisor.next_wait_seconds({"consec_failures": 1}, check_interval=2.0)
    w2 = live_supervisor.next_wait_seconds({"consec_failures": 2}, check_interval=2.0)
    assert w1 < w2
    w_big = live_supervisor.next_wait_seconds({"consec_failures": 30}, check_interval=2.0)
    assert w_big == live_supervisor.CRASH_BACKOFF_MAX_SEC


def test_next_wait_seconds_nominal_check_interval():
    assert live_supervisor.next_wait_seconds({}, check_interval=2.0) == 2.0


# --------------------------------------------------------------------------- #
#  Handler SIGTERM (appelable directement, cf. docstring _make_sigterm_handler)
# --------------------------------------------------------------------------- #
def test_sigterm_handler_sets_stop_event():
    ev = threading.Event()
    handler = live_supervisor._make_sigterm_handler(ev)
    assert not ev.is_set()
    handler(signal.SIGTERM, None)
    assert ev.is_set()


# --------------------------------------------------------------------------- #
#  run_supervisor -- boucle bloquante bornee par max_ticks (test uniquement) #
# --------------------------------------------------------------------------- #
def test_run_supervisor_max_ticks_spawn_puis_termine_a_la_sortie(tmp_path, monkeypatch):
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    _arm(tmp_path, mode="dry")
    calls = _record_spawn(monkeypatch)
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, service, start_ts=None: True)
    terminated = []
    monkeypatch.setattr(lancer, "terminate_pid",
                        lambda pid, timeout=5.0: terminated.append(pid) or True)

    rc = live_supervisor.run_supervisor(root=tmp_path, check_interval=0.01, max_ticks=1)

    assert rc == 0
    assert len(calls) == 1                     # un seul spawn (1 tick)
    assert terminated == [calls_pid(calls)]    # l'enfant est termine a la SORTIE (SIGTERM/max_ticks)
    assert live_control.read_live_status(tmp_path)["status"] == "arrete"


def calls_pid(calls):
    # `_record_spawn` renvoie toujours le meme pid fictif (424242, cf. fixture) --
    # helper pour ne pas dupliquer la constante dans le test.
    return 424242


def test_run_supervisor_racine_par_defaut_est_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live_supervisor, "keys_configured", lambda: True)
    calls = _record_spawn(monkeypatch)
    rc = live_supervisor.run_supervisor(check_interval=0.01, max_ticks=1)
    assert rc == 0
    assert calls == []  # desarme (aucun marqueur) -- confirme juste que root == cwd
    assert live_control.read_live_status(tmp_path)["status"] in ("desarme", "arrete")


# --------------------------------------------------------------------------- #
#  Cablage CLI -- main.py live-arm / live-disarm / live-run                   #
# --------------------------------------------------------------------------- #
def test_cli_live_arm_dry_ecrit_marqueur_sans_phrase(tmp_path, monkeypatch, capsys):
    args = main.build_parser().parse_args([
        "live-arm", "--dry", "--root", str(tmp_path),
        "--strategy", "sma", "--symbol", "ETH/USD", "--timeframe", "1h",
    ])
    args.func(args)
    marker = live_control.read_armed_marker(tmp_path)
    assert marker["mode"] == "dry"
    assert marker["armed_via"] == "cli-interactive-dry"


def test_cli_live_arm_reel_phrase_correcte_ecrit_marqueur(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.options.keys_configured", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("OUI JE CONFIRME\n"))
    args = main.build_parser().parse_args([
        "live-arm", "--root", str(tmp_path),
        "--strategy", "sma", "--symbol", "ETH/USD", "--timeframe", "1h",
        "--stop-loss", "5", "--take-profit", "10",
    ])
    args.func(args)
    marker = live_control.read_armed_marker(tmp_path)
    assert marker["mode"] == "reel"
    assert marker["armed_via"] == "cli-interactive"
    assert marker["stop_loss"] == 5.0


def test_cli_live_arm_reel_phrase_fausse_aucun_marqueur(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.options.keys_configured", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("non merci\n"))
    args = main.build_parser().parse_args([
        "live-arm", "--root", str(tmp_path),
        "--strategy", "sma", "--symbol", "ETH/USD", "--timeframe", "1h",
    ])
    with pytest.raises(SystemExit):
        args.func(args)
    assert live_control.read_armed_marker(tmp_path) is None


def test_cli_live_arm_sans_tty_eof_aucun_marqueur(tmp_path, monkeypatch):
    """C3 (NO-GO spec §8) : `docker compose run --rm` sans TTY -> stdin ferme
    -> input() leve EOFError (non intercepte, MEME comportement que
    cmd_live -- abort bruyant), donc AUCUN marqueur reel n'est jamais ecrit
    par accident (§2.3)."""
    monkeypatch.setattr("trading.options.keys_configured", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # EOF immediat
    args = main.build_parser().parse_args([
        "live-arm", "--root", str(tmp_path),
        "--strategy", "sma", "--symbol", "ETH/USD", "--timeframe", "1h",
    ])
    with pytest.raises(EOFError):
        args.func(args)
    assert live_control.read_armed_marker(tmp_path) is None


def test_cli_live_arm_reel_cles_absentes_refuse_sans_marqueur(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.options.keys_configured", lambda: False)
    args = main.build_parser().parse_args([
        "live-arm", "--root", str(tmp_path),
        "--strategy", "sma", "--symbol", "ETH/USD", "--timeframe", "1h",
    ])
    with pytest.raises(SystemExit):
        args.func(args)
    assert live_control.read_armed_marker(tmp_path) is None


def test_cli_live_disarm_supprime_marqueur(tmp_path):
    live_control.write_armed_marker(
        tmp_path, {"strategy": "sma", "symbol": "ETH/USD", "timeframe": "1h"},
        mode="reel", armed_via="cli-interactive")
    args = main.build_parser().parse_args(["live-disarm", "--root", str(tmp_path)])
    args.func(args)
    assert live_control.read_armed_marker(tmp_path) is None


def test_cli_live_run_forwards_root_and_check_interval(tmp_path, monkeypatch):
    captured = {}

    def fake_run_supervisor(root=None, **kwargs):
        captured["root"] = root
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("trading.live_supervisor.run_supervisor", fake_run_supervisor)
    args = main.build_parser().parse_args([
        "live-run", "--root", str(tmp_path), "--check-interval", "5",
    ])
    with pytest.raises(SystemExit) as exc:
        args.func(args)
    assert exc.value.code == 0
    assert str(captured["root"]) == str(tmp_path)
    assert captured["check_interval"] == 5.0
