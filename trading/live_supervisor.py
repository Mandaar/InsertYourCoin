"""
Superviseur du live CONTENEURISE (Lot 8B, argent reel).
docs/design/LOT8B_LIVE_CONTENEUR_SPEC.md §2.4 -- ce module est la `command:`
du service `live` (docker-compose.live.yml) : `python -u main.py live-run`.

Role : tant qu'un marqueur d'armement valide existe (trading/live_control.py
armed_marker_path, ecrit UNIQUEMENT par `main.py live-arm`, jamais par ce
module), (re)lancer `main.py live [--execute]` en lui pipant la phrase de
confirmation (§2.4 point 2) ; surveiller un sentinelle d'arret + SIGTERM ;
ne JAMAIS laisser deux enfants confirmes coexister (anti-BUG-015) ; ne
JAMAIS vendre a l'arret (§5 : "arreter n'est pas liquider").

Design testable : `supervisor_tick()` execute UNE iteration PURE cote
decision (les seules I/O sont les fonctions de trading/live_control.py et
lancer.py, toutes monkeypatchables -- meme patron que
tests/test_live_server.py). `run_supervisor()` boucle dessus avec un sleep
interruptible et un handler SIGTERM ; c'est la seule fonction bloquante.

Anti-BUG-015 (P0) : le bloc identite -> spawn -> ecriture pid est protege
par `_spawn_lock`, EXACTEMENT comme `_live_start_lock` de trading/monitor.py.
Un seul thread appelle `supervisor_tick` en usage reel (boucle mono-thread),
mais le verrou documente l'invariant et protege un futur thread annexe
(health-check, admin) sans devoir y repenser plus tard.
"""
import signal
import threading
import time
from pathlib import Path

import lancer
from . import live_control
from .options import keys_configured

CHECK_INTERVAL_SEC = 2.0        # cadence de surveillance marqueur/sentinelle (§2.4)
KEYS_MISSING_BACKOFF_SEC = 30.0  # arme mais cles absentes : n'idle pas au rythme de CHECK (§5)
CRASH_BACKOFF_MAX_SEC = 300.0

_spawn_lock = threading.Lock()


def _console(msg: str) -> None:
    """Log LOUD (M9) sur stdout -- capture par `docker logs` du service
    `live`. Le detail structure vit dans live/status.json (affiche par
    /live) ; ce print est le filet de securite console."""
    print(f"[live-supervisor] {msg}", flush=True)


def _log_supervisor_error(root: Path, exc) -> None:
    """JAMAIS silencieux (M9, BUG-014) -- log DEDIE (comme live_console.log,
    live_error.log du web) : un echec de spawn ne doit jamais disparaitre
    dans un except vide."""
    try:
        logs_dir = Path(root) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "live_supervisor_error.log").write_text(
            f"superviseur : demarrage live ECHEC : {type(exc).__name__}: {exc}\n",
            encoding="utf-8")
    except OSError:
        pass


def _terminate_confirmed_child(root: Path) -> None:
    """
    Termine l'enfant SI ET SEULEMENT SI son identite est confirmee
    (BUG-009 -- `live_identity` nettoie deja tout pid orphelin/recycle et ne
    le traite jamais comme "en cours"). AUCUNE vente ici : ce module ne
    connait aucun ordre de vente, seulement le cycle de vie du process (§5,
    §3.2 point "arreter n'est pas liquider").
    """
    pid, running, _start_ts = live_control.live_identity(root)
    if not running or pid is None:
        return
    lancer.terminate_pid(pid)
    lancer.remove_pid_file(live_control.live_pid_path(root))
    live_control.remove_live_sidecar(live_control.live_sidecar_path(root))


def supervisor_tick(root: Path, state: dict) -> dict:
    """
    UNE iteration de la boucle superviseur (§2.4). `state` est un dict
    MUTABLE, persiste par l'appelant d'un tick a l'autre (cle "ever_spawned"
    : un enfant a-t-il deja ete confirme depuis le dernier (re)armement ? --
    sert a distinguer "1er demarrage" de "crash suivi d'une relance", §5).
    Retourne `state` (mute en place ET retourne, pour un usage direct en
    test comme en boucle).

    Table de decision (§2.4) :
      - sentinelle d'arret present, OU marqueur absent/invalide -> AUCUN
        enfant vivant, AUCUNE vente ; desarme + efface le sentinelle si
        c'etait un arret demande (§3.2 points 1-2).
      - marqueur valide mais cles absentes -> AUCUN spawn, statut ERREUR
        explicite (jamais silencieux, M9), aucun martelement (§5).
      - marqueur valide + cles OK -> sequence identite -> spawn -> pid
        VERROUILLEE (anti-BUG-015/BUG-009) ; un enfant deja confirme =
        AUCUN 2e spawn.
    """
    root = Path(root)
    marker = live_control.read_armed_marker(root)
    stop = live_control.stop_requested(root)

    if stop or marker is None:
        _terminate_confirmed_child(root)
        if stop:
            live_control.remove_armed_marker(root)
            live_control.clear_stop_request(root)
            live_control.write_live_status(
                root, "arret_demande", "Arret demande -- superviseur idle, aucune vente.")
            _console("arret demande : enfant termine (si present), desarme.")
            state["status"] = "arret_demande"
        else:
            live_control.write_live_status(
                root, "desarme", "Aucun marqueur d'armement valide.")
            state["status"] = "desarme"
        state["ever_spawned"] = False
        state["consec_failures"] = 0
        return state

    if not keys_configured():
        live_control.write_live_status(
            root, "erreur_cles",
            "Arme mais cles API absentes -- impossible de demarrer. "
            "Renseigne .env (voir .env.example).")
        _console("ERREUR : arme mais cles API absentes -- idle avec backoff.")
        state["status"] = "erreur_cles"
        return state

    with _spawn_lock:
        pid, running, _start_ts = live_control.live_identity(root)
        if running:
            live_control.write_live_status(root, "en_cours", f"pid {pid}")
            state["status"] = "en_cours"
            state["consec_failures"] = 0
            return state

        crashed = bool(state.get("ever_spawned"))
        execute = marker.get("mode") == "reel"
        try:
            new_pid, _start_ts = live_control.start_live_process(
                root, marker, execute=execute)
        except OSError as exc:
            _log_supervisor_error(root, exc)
            live_control.write_live_status(root, "erreur_spawn", str(exc))
            _console(f"ERREUR de spawn : {exc}")
            state["status"] = "erreur_spawn"
            state["consec_failures"] = state.get("consec_failures", 0) + 1
            return state

    mode_txt = "reel" if execute else "dry"
    live_control.write_live_status(root, "en_cours", f"pid {new_pid} ({mode_txt})")
    _console(f"{'relance' if crashed else 'demarrage'} de l'enfant live "
             f"(pid {new_pid}, mode {mode_txt}).")
    state["status"] = "en_cours"
    state["ever_spawned"] = True
    state["consec_failures"] = (state.get("consec_failures", 0) + 1) if crashed else 0
    return state


def next_wait_seconds(state: dict, check_interval: float = CHECK_INTERVAL_SEC) -> float:
    """
    Duree d'attente AVANT le prochain tick (fonction PURE). Cles absentes :
    backoff fixe (§5, "ne pas idle au rythme de CHECK -- ni marteler Kraken").
    Echecs consecutifs (crash-loop) : backoff exponentiel plafonne (meme
    forme que paper_trader.backoff_seconds, base differente -- ici la
    cadence de surveillance, pas un cycle de trading).
    """
    if state.get("status") == "erreur_cles":
        return KEYS_MISSING_BACKOFF_SEC
    failures = state.get("consec_failures", 0)
    if failures:
        return min(check_interval * 2 ** failures, CRASH_BACKOFF_MAX_SEC)
    return check_interval


def _make_sigterm_handler(stop_event: threading.Event):
    """Fabrique le handler SIGTERM -- isole pour rester appelable DIRECTEMENT
    par un test (un vrai signal ne se delivre de maniere fiable qu'au thread
    principal en CPython ; le handler lui-meme, en revanche, est une
    fonction ordinaire testable sans passer par os.kill)."""
    def _handler(signum, frame):
        stop_event.set()
    return _handler


def run_supervisor(root=None, check_interval: float = CHECK_INTERVAL_SEC,
                   max_ticks=None) -> int:
    """
    Boucle superviseur BLOQUANTE (§2.4) -- c'est la `command:` du service
    `live`. `root` = racine des donnees (defaut `Path.cwd()` : le service
    `live` fixe `working_dir: /data`, §4 -- meme convention que
    PaperTrader/LiveTrader qui ecrivent deja des chemins relatifs au cwd).
    `max_ticks` (TEST UNIQUEMENT) : nombre de tours avant arret automatique
    (None = infini, arrete seulement par SIGTERM).

    A la sortie (SIGTERM ou max_ticks atteint) : termine l'enfant confirme
    SANS vendre (§5) -- meme geste qu'un tick "arret demande", pour qu'un
    `docker compose stop live` (kill de derniere instance, §2.5) ne laisse
    jamais un enfant orphelin.
    """
    root = Path(root) if root else Path.cwd()
    stop_event = threading.Event()
    try:
        signal.signal(signal.SIGTERM, _make_sigterm_handler(stop_event))
    except ValueError:
        # "signal only works in main thread" (tests qui lancent la boucle
        # dans un thread annexe) -- best-effort, Docker garde `docker stop`
        # comme filet de derniere instance (§2.5) meme sans ce handler.
        pass

    state = {"ever_spawned": False, "consec_failures": 0}
    _console(f"demarrage -- racine des donnees : {root}")
    ticks = 0
    while not stop_event.is_set():
        supervisor_tick(root, state)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        stop_event.wait(next_wait_seconds(state, check_interval))

    _terminate_confirmed_child(root)
    live_control.write_live_status(root, "arrete", "Superviseur arrete (SIGTERM/arret).")
    _console("arrete.")
    return 0
