"""
Tests de configuration des deux `docker-compose.yml` -- Mode protection, deux
poches (2026-09-24, cf. docs/DEPLOY_DOCKER.md §14).

PyYAML n'est PAS installe dans ce venv (MESURE : `import yaml` echoue) et n'est
pas une dependance du projet -- ne pas l'ajouter. Ces tests lisent donc les deux
compose en TEXTE BRUT : ils extraient la commande de chaque service `paper`,
`paper-btc` et `monitor`, remplacent chaque `${VAR:-defaut}` par son defaut
(comportement `docker compose` quand la variable est absente/vide), decoupent
la chaine obtenue et la font parser par `main.build_parser()` -- si une option
n'existe pas ou est mal formee, `argparse` leve `SystemExit`, ce que pytest
rapporte comme un echec clair.

Incident vecu (2026-09-02, cf. CLAUDE.md) : un defaut litteral resolu contre le
repertoire courant a fait ecraser le journal d'un paper reellement en train de
tourner -- aucun de ces tests n'ecrit sur le disque (parsing pur), donc rien
n'ecrit sous le repertoire courant ni sous tmp_path ici.
"""
import re
import shlex
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parent.parent
EUNIVERS = ROOT / "docker-compose.eunivers.yml"
DEDIE = ROOT / "docker-compose.yml"

_VAR_RE = re.compile(r"\$\{(\w+):-([^}]*)\}")
_SERVICE_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\n((?:(?!^  [A-Za-z0-9_-]+:).*\n?)*)", re.MULTILINE)


def _services_block(text: str) -> str:
    """Le texte de la section `services:`, coupe avant `networks:`/`volumes:`."""
    marker = "services:\n"
    start = text.index(marker) + len(marker)
    tail = text[start:]
    end = len(tail)
    for key in ("\nnetworks:\n", "\nvolumes:\n"):
        idx = tail.find(key)
        if idx != -1:
            end = min(end, idx)
    return tail[:end]


def _service_bodies(compose_path: Path) -> dict:
    text = compose_path.read_text(encoding="utf-8")
    services_text = _services_block(text)
    return {name: body for name, body in _SERVICE_RE.findall(services_text)}


def _apply_defaults(cmd_text: str) -> str:
    return _VAR_RE.sub(lambda m: m.group(2), cmd_text)


def _command_argv(service_body: str) -> list:
    """Argv (sans `python -u /app/main.py`) de la commande d'un service, apres
    substitution des `${VAR:-defaut}` par leur defaut."""
    lines = service_body.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "command: >":
            indent = len(line) - len(line.lstrip())
            collected = []
            for cont in lines[i + 1:]:
                if not cont.strip():
                    break
                cont_indent = len(cont) - len(cont.lstrip())
                if cont_indent <= indent:
                    break
                collected.append(cont.strip())
            cmd_text = _apply_defaults(" ".join(collected))
            tokens = shlex.split(cmd_text)
            assert tokens[:3] == ["python", "-u", "/app/main.py"], tokens[:3]
            return tokens[3:]
    raise AssertionError(f"aucune commande trouvee dans le service : {service_body[:80]!r}")


def _full_command_text(service_body: str) -> str:
    """Le texte brut (AVANT substitution) de `command: >`, pour comparer bit a
    bit deux services entre les deux fichiers compose."""
    lines = service_body.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "command: >":
            indent = len(line) - len(line.lstrip())
            collected = []
            for cont in lines[i + 1:]:
                if not cont.strip():
                    break
                cont_indent = len(cont) - len(cont.lstrip())
                if cont_indent <= indent:
                    break
                collected.append(cont.strip())
            return " ".join(collected)
    raise AssertionError("aucune commande trouvee")


# ---------------------------------------------------------------------------
# Les deux compose existent et declarent les 3 services attendus
# ---------------------------------------------------------------------------

def test_both_compose_files_exist():
    assert EUNIVERS.is_file()
    assert DEDIE.is_file()


def test_both_compose_declare_paper_paper_btc_and_monitor():
    for path in (EUNIVERS, DEDIE):
        bodies = _service_bodies(path)
        assert "paper" in bodies, path
        assert "paper-btc" in bodies, path
        assert "monitor" in bodies, path


# ---------------------------------------------------------------------------
# Chaque commande `paper`/`paper-btc` (defauts appliques) parse avec main.py
# ---------------------------------------------------------------------------

def test_paper_commands_parse_on_both_compose():
    for path in (EUNIVERS, DEDIE):
        bodies = _service_bodies(path)
        for service in ("paper", "paper-btc"):
            argv = _command_argv(bodies[service])
            args = main.build_parser().parse_args(argv)
            assert args.command == "paper", (path, service, argv)


def test_monitor_command_parses_on_both_compose():
    for path in (EUNIVERS, DEDIE):
        bodies = _service_bodies(path)
        argv = _command_argv(bodies["monitor"])
        args = main.build_parser().parse_args(argv)
        assert args.command == "monitor", (path, argv)


# ---------------------------------------------------------------------------
# Aucun --reset dans aucune commande de service (rejoue par un redemarrage
# automatique sous `restart: unless-stopped`)
# ---------------------------------------------------------------------------

def test_no_reset_flag_in_any_service_command():
    for path in (EUNIVERS, DEDIE):
        bodies = _service_bodies(path)
        for service, body in bodies.items():
            if "command: >" not in body:
                continue
            argv = _command_argv(body)
            assert "--reset" not in argv, (path, service, argv)


# ---------------------------------------------------------------------------
# Les deux poches ont des chemins d'etat / stats / journal distincts, sous
# /data/poches/, et distincts de l'ancien historique a la racine de /data
# ---------------------------------------------------------------------------

def test_two_pockets_have_distinct_state_and_stats_paths():
    for path in (EUNIVERS, DEDIE):
        bodies = _service_bodies(path)
        eth_argv = _command_argv(bodies["paper"])
        btc_argv = _command_argv(bodies["paper-btc"])

        def _opt(argv, flag):
            return argv[argv.index(flag) + 1]

        eth_state, eth_stats = _opt(eth_argv, "--state"), _opt(eth_argv, "--stats")
        btc_state, btc_stats = _opt(btc_argv, "--state"), _opt(btc_argv, "--stats")

        assert eth_state != btc_state, path
        assert eth_stats != btc_stats, path
        assert eth_state.startswith("/data/poches/"), (path, eth_state)
        assert btc_state.startswith("/data/poches/"), (path, btc_state)
        # jamais l'ancien chemin historique a la racine de /data
        assert eth_state != "/data/paper_state.json"
        assert btc_state != "/data/paper_state.json"


def test_monitor_points_to_eth_pocket_files_on_both_compose():
    for path in (EUNIVERS, DEDIE):
        bodies = _service_bodies(path)
        argv = _command_argv(bodies["monitor"])

        def _opt(flag):
            return argv[argv.index(flag) + 1]

        assert _opt("--state") == "/data/poches/eth_state.json", path
        assert _opt("--stats") == "/data/poches/eth_stats.csv", path
        assert _opt("--log") == "/data/poches/eth_trades.log", path


# ---------------------------------------------------------------------------
# Les defauts (variable absente) sont la cible decidee le 2026-09-24
# ---------------------------------------------------------------------------

def test_paper_defaults_are_the_decided_target_on_both_compose():
    for path in (EUNIVERS, DEDIE):
        bodies = _service_bodies(path)
        for service, expected_symbol in (("paper", "ETH/USD"), ("paper-btc", "BTC/USD")):
            args = main.build_parser().parse_args(_command_argv(bodies[service]))
            assert args.strategy == "tsmom", (path, service)
            assert args.timeframe == "1d", (path, service)
            assert args.params == "lookback=365", (path, service)
            assert args.order_type == "limit", (path, service)
            assert args.stop_loss == 0.0, (path, service)
            assert args.take_profit == 0.0, (path, service)
            assert args.trailing_stop == 0.0, (path, service)
            assert args.symbol == expected_symbol, (path, service)


# ---------------------------------------------------------------------------
# Les deux compose portent la meme commande paper / paper-btc (texte brut,
# AVANT substitution -- le service doit rester identique bit pour bit)
# ---------------------------------------------------------------------------

def test_paper_command_text_identical_across_both_compose_files():
    eunivers_bodies = _service_bodies(EUNIVERS)
    dedie_bodies = _service_bodies(DEDIE)
    for service in ("paper", "paper-btc"):
        assert _full_command_text(eunivers_bodies[service]) == _full_command_text(dedie_bodies[service]), service
