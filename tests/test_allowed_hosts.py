"""
Tests de l'allowlist Host configurable -- deploiement derriere un reverse-proxy
EXISTANT (SWAG / serveur mutualise, 2026-08-09). Cf. docs/DEPLOY_DOCKER.md
section "reverse-proxy existant".

Contexte : host_allowed() protege contre le DNS-rebinding en n'acceptant que
127.0.0.1/localhost. Derriere SWAG, reecrire le Host cote nginx est interdit
(incident deja vecu -- double proxy_set_header Host). La solution retenue est
une allowlist configurable cote app (extra_hosts / --allowed-host /
IYC_ALLOWED_HOSTS), avec un IMPERATIF : le defaut ne doit JAMAIS bouger pour
qui ne configure rien (usage local Windows existant).
"""
import main
from trading.monitor import host_allowed


# --------------------------------------------------------------------------- #
# host_allowed(host_header, port, extra_hosts=())
# --------------------------------------------------------------------------- #

def test_host_allowed_default_unchanged_without_extra_hosts():
    """Sans extra_hosts (ou extra_hosts=()) : comportement identique a avant
    ce patch -- seuls 127.0.0.1/localhost passent."""
    assert host_allowed("127.0.0.1:8765", 8765) is True
    assert host_allowed("localhost:8765", 8765) is True
    assert host_allowed("evil.example.com", 8765) is False
    assert host_allowed("iyc.eunivers.net", 8765) is False
    assert host_allowed("iyc.eunivers.net", 8765, extra_hosts=()) is False


def test_host_allowed_accepts_configured_extra_host():
    """L'hote configure passe, avec ou sans port (le proxy peut transmettre
    l'un ou l'autre selon sa config)."""
    assert host_allowed("iyc.eunivers.net", 8765, extra_hosts=["iyc.eunivers.net"]) is True
    assert host_allowed("iyc.eunivers.net:8765", 8765, extra_hosts=["iyc.eunivers.net"]) is True


def test_host_allowed_rejects_host_not_in_allowlist():
    """Un hote NON listé reste refuse meme si l'allowlist n'est pas vide --
    l'ajout est additif, pas un carte blanche."""
    assert host_allowed("attacker.example", 8765, extra_hosts=["iyc.eunivers.net"]) is False


def test_host_allowed_extra_hosts_case_and_whitespace_tolerant():
    """Comparaison strip+lower, comme le comportement existant sur le defaut."""
    assert host_allowed("IYC.EUNIVERS.NET", 8765, extra_hosts=[" iyc.eunivers.net "]) is True


def test_host_allowed_loopback_still_works_alongside_extra_hosts():
    """L'ajout d'un hote configure n'exclut pas le defaut -- les deux
    coexistent (utile pour le healthcheck interne 127.0.0.1 du compose)."""
    assert host_allowed("127.0.0.1:8765", 8765, extra_hosts=["iyc.eunivers.net"]) is True


def test_host_allowed_empty_entries_in_extra_hosts_are_ignored():
    assert host_allowed("", 8765, extra_hosts=["", "  ", "iyc.eunivers.net"]) is False
    assert host_allowed("iyc.eunivers.net", 8765, extra_hosts=["", "iyc.eunivers.net"]) is True


# --------------------------------------------------------------------------- #
# main.py : --allowed-host (CLI, repetable) + IYC_ALLOWED_HOSTS (env)
# --------------------------------------------------------------------------- #

def test_monitor_allowed_host_cli_defaults_to_empty():
    args = main.build_parser().parse_args(["monitor"])
    assert args.allowed_host == []


def test_monitor_allowed_host_cli_repeatable():
    args = main.build_parser().parse_args(
        ["monitor", "--allowed-host", "iyc.eunivers.net", "--allowed-host", "other.example"]
    )
    assert args.allowed_host == ["iyc.eunivers.net", "other.example"]


def test_resolve_allowed_hosts_cli_only(monkeypatch):
    monkeypatch.delenv("IYC_ALLOWED_HOSTS", raising=False)
    assert main._resolve_allowed_hosts(["iyc.eunivers.net"]) == ("iyc.eunivers.net",)


def test_resolve_allowed_hosts_env_only(monkeypatch):
    monkeypatch.setenv("IYC_ALLOWED_HOSTS", "iyc.eunivers.net, other.example")
    assert main._resolve_allowed_hosts([]) == ("iyc.eunivers.net", "other.example")


def test_resolve_allowed_hosts_cli_and_env_both_kept(monkeypatch):
    """Les deux sources s'AJOUTENT (spec : jamais de remplacement)."""
    monkeypatch.setenv("IYC_ALLOWED_HOSTS", "from-env.example")
    result = main._resolve_allowed_hosts(["from-cli.example"])
    assert result == ("from-cli.example", "from-env.example")


def test_resolve_allowed_hosts_default_empty_without_config(monkeypatch):
    """Sans --allowed-host ni IYC_ALLOWED_HOSTS : tuple vide -> host_allowed()
    retombe sur son defaut strict. C'est le garde-fou anti-regression usage
    local."""
    monkeypatch.delenv("IYC_ALLOWED_HOSTS", raising=False)
    assert main._resolve_allowed_hosts([]) == ()


def test_resolve_allowed_hosts_env_blank_entries_ignored(monkeypatch):
    monkeypatch.setenv("IYC_ALLOWED_HOSTS", "iyc.eunivers.net,,  ,other.example")
    assert main._resolve_allowed_hosts([]) == ("iyc.eunivers.net", "other.example")


def test_cmd_monitor_forwards_resolved_allowed_hosts(monkeypatch):
    """cmd_monitor doit transmettre allowed_hosts = fusion CLI+env a
    run_monitor -- verifie le cablage bout en bout de la commande monitor."""
    captured = {}

    def fake_run_monitor(**kwargs):
        captured.update(kwargs)

    monkeypatch.setenv("IYC_ALLOWED_HOSTS", "iyc.eunivers.net")
    monkeypatch.setattr("trading.monitor.run_monitor", fake_run_monitor)
    args = main.build_parser().parse_args(
        ["monitor", "--allowed-host", "other.example"]
    )
    args.func(args)
    assert captured["allowed_hosts"] == ("other.example", "iyc.eunivers.net")
