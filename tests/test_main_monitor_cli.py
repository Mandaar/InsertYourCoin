"""
Tests de la commande CLI `monitor` (--host) -- Deploiement Docker (2026-08-09).

Avant ce patch, `trading.monitor.run_monitor`/`build_monitor_server` acceptaient
deja un parametre `host` (utilise pour le bind reel du ThreadingHTTPServer),
mais `main.py` ne l'exposait PAS en argument CLI : impossible de faire ecouter
le serveur sur 0.0.0.0 (reseau Docker) sans modifier le code. Ces tests
verifient (a) le defaut reste 127.0.0.1 (aucune regression de l'usage local),
(b) --host est bien parse, (c) cmd_monitor le transmet a run_monitor.
"""
import main


def test_monitor_host_defaults_to_loopback():
    args = main.build_parser().parse_args(["monitor"])
    assert args.host == "127.0.0.1"


def test_monitor_host_overridable():
    args = main.build_parser().parse_args(["monitor", "--host", "0.0.0.0", "--port", "9000"])
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_cmd_monitor_forwards_host_to_run_monitor(monkeypatch):
    captured = {}

    def fake_run_monitor(**kwargs):
        captured.update(kwargs)

    monkeypatch.delenv("IYC_ALLOWED_HOSTS", raising=False)
    monkeypatch.setattr("trading.monitor.run_monitor", fake_run_monitor)
    args = main.build_parser().parse_args(
        ["monitor", "--host", "0.0.0.0", "--port", "8765",
         "--stats", "s.csv", "--log", "l.log", "--state", "st.json"]
    )
    args.func(args)
    assert captured == {
        "port": 8765, "host": "0.0.0.0",
        "stats_path": "s.csv", "log_path": "l.log", "state_path": "st.json",
        "allowed_hosts": (), "live_root": None,
    }
