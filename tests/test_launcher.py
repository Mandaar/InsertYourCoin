"""
Tests du lanceur double-clic (lancer.py) -- PAPER-ONLY par construction.

AUCUN vrai process n'est lance, AUCUN reseau : on teste les fonctions pures
(construction de commandes, garde-fou paper-only, fichiers pid, dossiers) et
le mode --dry-run avec subprocess/webbrowser neutralises par monkeypatch.
"""
import os
import sys
from pathlib import Path

import pytest

import lancer


# --------------------------------------------------------------------------- #
#  Garde-fou paper-only : les commandes construites ne contiennent JAMAIS      #
#  "live" et passent par main.py paper/monitor/check uniquement.               #
# --------------------------------------------------------------------------- #
def test_paper_command_is_paper_and_never_live(tmp_path):
    cmd = lancer.build_paper_command(tmp_path)
    assert cmd[0] == sys.executable
    assert cmd[1] == str(tmp_path / "main.py")
    assert cmd[2] == "paper"
    for token in cmd[2:]:
        assert "live" not in str(token).lower()


def test_monitor_command_is_monitor_and_never_live(tmp_path):
    cmd = lancer.build_monitor_command(tmp_path)
    assert cmd[2] == "monitor"
    assert str(lancer.MONITOR_PORT) in cmd
    for token in cmd[2:]:
        assert "live" not in str(token).lower()


def test_check_command_is_check_and_never_live(tmp_path):
    cmd = lancer.build_check_command(tmp_path)
    assert cmd[2] == "check"
    for token in cmd[2:]:
        assert "live" not in str(token).lower()


def test_assert_paper_only_blocks_live():
    with pytest.raises(RuntimeError):
        lancer.assert_paper_only([sys.executable, "main.py", "live"])
    with pytest.raises(RuntimeError):
        lancer.assert_paper_only([sys.executable, "main.py", "paper", "--mode", "LIVE"])


def test_assert_paper_only_ignores_interpreter_and_script_paths():
    # Un chemin machine contenant "live" (ex: C:\Users\Oliver) ne doit pas
    # bloquer : seuls les ARGUMENTS construits par le lanceur sont verifies.
    cmd = ["C:\\Users\\Oliver\\python.exe", "C:\\Users\\Oliver\\main.py", "paper"]
    assert lancer.assert_paper_only(cmd) == cmd


# --------------------------------------------------------------------------- #
#  Dossiers run/ et logs/                                                       #
# --------------------------------------------------------------------------- #
def test_ensure_dirs_creates_run_and_logs(tmp_path):
    run_dir, logs_dir = lancer.ensure_dirs(tmp_path)
    assert run_dir == tmp_path / "run" and run_dir.is_dir()
    assert logs_dir == tmp_path / "logs" and logs_dir.is_dir()
    # Idempotent : un 2e appel ne leve pas.
    lancer.ensure_dirs(tmp_path)


# --------------------------------------------------------------------------- #
#  Fichiers PID : ecriture / lecture / nettoyage / orphelin                     #
# --------------------------------------------------------------------------- #
def test_pid_file_roundtrip(tmp_path):
    p = tmp_path / "paper.pid"
    lancer.write_pid_file(p, 12345)
    assert lancer.read_pid_file(p) == 12345
    lancer.remove_pid_file(p)
    assert not p.exists()
    assert lancer.read_pid_file(p) is None       # absent -> None, pas d'exception
    lancer.remove_pid_file(p)                    # idempotent : pas d'exception


def test_read_pid_file_garbage_returns_none(tmp_path):
    p = tmp_path / "paper.pid"
    p.write_text("pas-un-pid", encoding="ascii")
    assert lancer.read_pid_file(p) is None


def test_pid_alive_current_process_and_dead_pid():
    assert lancer.pid_alive(os.getpid()) is True
    assert lancer.pid_alive(None) is False
    # PID enorme : quasi certain de ne correspondre a aucun process.
    assert lancer.pid_alive(99999999) is False


def test_do_stop_cleans_orphan_pid_files(tmp_path, monkeypatch, capsys):
    run_dir, _ = lancer.ensure_dirs(tmp_path)
    (run_dir / "paper.pid").write_text("99999999", encoding="ascii")
    (run_dir / "monitor.pid").write_text("99999998", encoding="ascii")
    monkeypatch.setattr(lancer, "pid_alive", lambda pid: False)

    def boom(*a, **k):
        raise AssertionError("terminate_pid ne doit PAS etre appele sur un orphelin")
    monkeypatch.setattr(lancer, "terminate_pid", boom)

    assert lancer.do_stop(tmp_path) == 0
    assert not (run_dir / "paper.pid").exists()
    assert not (run_dir / "monitor.pid").exists()
    assert "orphelin" in capsys.readouterr().out


def test_do_stop_terminates_then_cleans(tmp_path, monkeypatch, capsys):
    run_dir, _ = lancer.ensure_dirs(tmp_path)
    (run_dir / "paper.pid").write_text("424242", encoding="ascii")
    monkeypatch.setattr(lancer, "pid_alive", lambda pid: True)
    # FIX 1 : identite confirmee -> on autorise le kill (sinon refus de tuer).
    monkeypatch.setattr(lancer, "is_our_process", lambda pid, name, ts=None: True)
    killed = []
    monkeypatch.setattr(lancer, "terminate_pid", lambda pid: killed.append(pid) or True)

    assert lancer.do_stop(tmp_path) == 0
    assert killed == [424242]
    assert not (run_dir / "paper.pid").exists()
    assert "arrete" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
#  FIX 1 (SECURITE) : --stop ne tue JAMAIS un process dont l'identite n'est     #
#  pas confirmee (PID recycle par un tiers apres crash/reboot).                 #
# --------------------------------------------------------------------------- #
def test_do_stop_refuses_to_kill_recycled_pid(tmp_path, monkeypatch, capsys):
    """PID vivant mais identite NON confirmee (recycle par un autre process) :
    aucun terminate, pid file nettoye, message explicite."""
    run_dir, _ = lancer.ensure_dirs(tmp_path)
    (run_dir / "paper.pid").write_text("424242:1700000000.0", encoding="ascii")
    monkeypatch.setattr(lancer, "pid_alive", lambda pid: True)
    monkeypatch.setattr(lancer, "is_our_process", lambda pid, name, ts=None: False)

    def boom(*a, **k):
        raise AssertionError("terminate_pid ne doit PAS tuer un process non confirme")
    monkeypatch.setattr(lancer, "terminate_pid", boom)

    assert lancer.do_stop(tmp_path) == 0
    assert not (run_dir / "paper.pid").exists()          # pid file nettoye
    out = capsys.readouterr().out
    assert "recycle" in out and "NON tue" in out


def test_do_stop_kills_only_when_identity_confirmed(tmp_path, monkeypatch, capsys):
    """Identite confirmee -> terminate appele ; le service `name` est bien
    transmis a is_our_process (paper verifie paper, pas monitor)."""
    run_dir, _ = lancer.ensure_dirs(tmp_path)
    (run_dir / "paper.pid").write_text("424242:1700000000.0", encoding="ascii")
    (run_dir / "monitor.pid").write_text("424243:1700000000.0", encoding="ascii")
    monkeypatch.setattr(lancer, "pid_alive", lambda pid: True)
    checked = []
    monkeypatch.setattr(lancer, "is_our_process",
                        lambda pid, name, ts=None: checked.append((pid, name)) or True)
    killed = []
    monkeypatch.setattr(lancer, "terminate_pid", lambda pid: killed.append(pid) or True)

    assert lancer.do_stop(tmp_path) == 0
    assert (424242, "paper") in checked and (424243, "monitor") in checked
    assert killed == [424242, 424243]


def test_pid_file_new_format_roundtrip_pid_and_ts(tmp_path):
    """write_pid_file ecrit 'pid:ts' ; read_pid_file/read_pid_start relisent les
    deux champs."""
    p = tmp_path / "paper.pid"
    lancer.write_pid_file(p, 7777, start_ts=1700000123.5)
    assert lancer.read_pid_file(p) == 7777
    assert lancer.read_pid_start(p) == pytest.approx(1700000123.5)


def test_read_pid_file_old_format_still_readable(tmp_path):
    """Retro-compat : un ancien pid file (pid seul, sans ':') reste lisible ;
    read_pid_start renvoie None (pas d'horodatage a comparer)."""
    p = tmp_path / "paper.pid"
    p.write_text("12345", encoding="ascii")
    assert lancer.read_pid_file(p) == 12345
    assert lancer.read_pid_start(p) is None


def test_is_our_process_none_pid_is_false():
    assert lancer.is_our_process(None, "paper") is False


# --------------------------------------------------------------------------- #
#  --dry-run : ne lance RIEN (ni Popen, ni run, ni navigateur)                  #
# --------------------------------------------------------------------------- #
def test_dry_run_spawns_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(lancer, "project_root", lambda: tmp_path)

    def boom(*a, **k):
        raise AssertionError("--dry-run ne doit lancer AUCUN process")
    monkeypatch.setattr(lancer.subprocess, "Popen", boom)
    monkeypatch.setattr(lancer.subprocess, "run", boom)
    monkeypatch.setattr(lancer.webbrowser, "open", boom)

    assert lancer.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "paper" in out and "monitor" in out and "check" in out
    assert "live" not in out.lower()             # garde-fou visible jusque dans l'affichage
    assert (tmp_path / "run").is_dir() and (tmp_path / "logs").is_dir()


# --------------------------------------------------------------------------- #
#  FIX 4 : le port 8765 n'est "reutilise" QUE si c'est NOTRE monitor (signature)#
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_monitor_signature_present_true_when_signature_in_body(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=2.0: _FakeResp(
                            "<title>Paper trading - monitoring</title>"))
    assert lancer.monitor_signature_present() is True


def test_monitor_signature_absent_when_other_service(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=2.0: _FakeResp("<title>autre service</title>"))
    assert lancer.monitor_signature_present() is False


def test_monitor_signature_false_on_connection_error(monkeypatch):
    import urllib.request

    def boom(url, timeout=2.0):
        raise OSError("connexion refusee")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert lancer.monitor_signature_present() is False


def _stub_start_environment(monkeypatch, tmp_path):
    """Neutralise le diagnostic (rc=0) et le demarrage du paper pour isoler la
    logique du monitor dans do_start."""
    monkeypatch.setattr(lancer.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0})())
    monkeypatch.setattr(lancer, "_start_service",
                        lambda name, cmd, run_dir, logs_dir, root: 111)
    monkeypatch.setattr(lancer, "read_pid_file", lambda p: None)
    monkeypatch.setattr(lancer, "pid_alive", lambda pid: True)


def test_do_start_reuses_monitor_when_signature_present(tmp_path, monkeypatch, capsys):
    _stub_start_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(lancer, "port_in_use", lambda: True)
    monkeypatch.setattr(lancer, "monitor_signature_present", lambda: True)
    opened = []
    monkeypatch.setattr(lancer.webbrowser, "open", lambda url: opened.append(url))

    assert lancer.do_start(tmp_path) == 0
    out = capsys.readouterr().out
    assert "reutilise" in out
    assert opened == [lancer.MONITOR_URL]            # navigateur ouvert (c'est nous)


def test_do_start_warns_and_no_browser_when_port_squatted(tmp_path, monkeypatch, capsys):
    """Port occupe SANS signature : on AVERTIT et on n'ouvre PAS le navigateur
    en pretendant a tort que c'est le monitor."""
    _stub_start_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(lancer, "port_in_use", lambda: True)
    monkeypatch.setattr(lancer, "monitor_signature_present", lambda: False)

    def boom(url):
        raise AssertionError("le navigateur ne doit PAS s'ouvrir sur un service tiers")
    monkeypatch.setattr(lancer.webbrowser, "open", boom)

    assert lancer.do_start(tmp_path) == 0
    out = capsys.readouterr().out
    assert "OCCUPE par un AUTRE service" in out
    assert "non ouvert" in out


def test_start_service_does_not_double_a_running_service(tmp_path, monkeypatch, capsys):
    run_dir, logs_dir = lancer.ensure_dirs(tmp_path)
    (run_dir / "paper.pid").write_text(str(os.getpid()), encoding="ascii")
    monkeypatch.setattr(lancer, "pid_alive", lambda pid: True)

    def boom(*a, **k):
        raise AssertionError("un service deja vivant ne doit PAS etre relance")
    monkeypatch.setattr(lancer, "spawn_detached", boom)

    pid = lancer._start_service("paper", ["x", "y", "paper"], run_dir, logs_dir, tmp_path)
    assert pid == os.getpid()
    assert "deja en cours" in capsys.readouterr().out


def test_start_service_replaces_orphan_pid(tmp_path, monkeypatch):
    run_dir, logs_dir = lancer.ensure_dirs(tmp_path)
    (run_dir / "paper.pid").write_text("99999999", encoding="ascii")
    monkeypatch.setattr(lancer, "pid_alive", lambda pid: False)
    monkeypatch.setattr(lancer, "spawn_detached", lambda cmd, log, cwd: 555)

    pid = lancer._start_service("paper", ["x", "y", "paper"], run_dir, logs_dir, tmp_path)
    assert pid == 555
    assert lancer.read_pid_file(run_dir / "paper.pid") == 555
