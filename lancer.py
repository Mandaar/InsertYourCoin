#!/usr/bin/env python3
"""
Lanceur "double-clic et laisse tourner" — PAPER-ONLY PAR CONSTRUCTION.

Demarre le paper trading + le serveur de monitoring en arriere-plan, puis ouvre
le navigateur sur le tableau de suivi. Cross-platform (Windows/macOS/Linux).

GARDE-FOUS (non negociables) :
- Ce lanceur ne sait lancer QUE `paper` et `monitor`. Le mot "live" n'apparait
  dans AUCUNE commande construite (verifie en dur par assert_paper_only + test).
- Aucune cle API requise (paper = donnees publiques). Ne lit JAMAIS .env.
- Le monitor reste sur 127.0.0.1 (jamais expose au reseau).

Usage :
  python lancer.py            demarre paper + monitor + ouvre le navigateur
  python lancer.py --stop     arrete proprement paper + monitor
  python lancer.py --status   montre ce qui tourne
  python lancer.py --dry-run  montre ce qui SERAIT lance, sans rien lancer
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ----------------------------------------------------------------------------- #
#  Parametres du paper — modifiable ici en attendant la page Options.            #
# ----------------------------------------------------------------------------- #
PAPER_STRATEGY = "sma"
PAPER_TIMEFRAME = "5m"
PAPER_STOP_LOSS = "5"        # %
PAPER_TAKE_PROFIT = "10"     # %
PAPER_TRAILING_STOP = "8"    # %
MONITOR_HOST = "127.0.0.1"   # bind local uniquement (securite)
MONITOR_PORT = 8765
MONITOR_URL = f"http://{MONITOR_HOST}:{MONITOR_PORT}"


# ----------------------------------------------------------------------------- #
#  Chemins (fonctions pures, racine injectable pour les tests)                   #
# ----------------------------------------------------------------------------- #
def project_root() -> Path:
    return Path(__file__).resolve().parent


def ensure_dirs(root: Path):
    """Cree run/ (fichiers pid) et logs/ (consoles) si absents. Retourne (run, logs)."""
    run_dir, logs_dir = root / "run", root / "logs"
    run_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, logs_dir


# ----------------------------------------------------------------------------- #
#  Construction des commandes (pures, testables) + garde-fou paper-only          #
# ----------------------------------------------------------------------------- #
def assert_paper_only(cmd):
    """
    Garde-fou EN DUR : aucun argument construit par ce lanceur ne doit contenir
    le mot "live". On verifie tout sauf cmd[0] (chemin de l'interpreteur) et
    cmd[1] (chemin de main.py) : ces chemins sont imposes par la machine (un
    dossier utilisateur peut contenir "live" par hasard), pas par nous.
    """
    for token in cmd[2:]:
        if "live" in str(token).lower():
            raise RuntimeError(
                "Garde-fou paper-only viole : le lanceur a construit une commande "
                f"contenant 'live' ({token!r}). Refus de lancer.")
    return cmd


def _base_cmd(root: Path, python=None):
    return [python or sys.executable, str(root / "main.py")]


def build_check_command(root: Path, python=None):
    return assert_paper_only(_base_cmd(root, python) + ["check"])


def build_paper_command(root: Path, python=None):
    return assert_paper_only(_base_cmd(root, python) + [
        "paper",
        "--strategy", PAPER_STRATEGY,
        "--timeframe", PAPER_TIMEFRAME,
        "--stop-loss", PAPER_STOP_LOSS,
        "--take-profit", PAPER_TAKE_PROFIT,
        "--trailing-stop", PAPER_TRAILING_STOP,
    ])


def build_monitor_command(root: Path, python=None):
    return assert_paper_only(_base_cmd(root, python) + [
        "monitor", "--port", str(MONITOR_PORT)])


def format_cmd(cmd):
    """Commande affichable (guillemets autour des tokens contenant un espace)."""
    return " ".join(f'"{t}"' if " " in str(t) else str(t) for t in cmd)


# ----------------------------------------------------------------------------- #
#  Fichiers PID + detection de process / port                                     #
# ----------------------------------------------------------------------------- #
def read_pid_file(path: Path):
    """PID lu depuis le fichier, None si absent/illisible (jamais d'exception).

    Retro-compat : accepte l'ancien format "pid" (pid seul) ET le nouveau format
    "pid:ts" (pid + timestamp de demarrage, cf. write_pid_file). Seul le pid est
    renvoye ici ; le timestamp se lit via read_pid_start (FIX 1, anti-recyclage).
    """
    try:
        raw = Path(path).read_text(encoding="ascii").strip()
        return int(raw.split(":", 1)[0])
    except (OSError, ValueError):
        return None


def read_pid_start(path: Path):
    """Timestamp de demarrage stocke dans le pid file ("pid:ts"), ou None.

    FIX 1) sert a confirmer l'IDENTITE du process via psutil.create_time() :
    un PID recycle par un autre process aura un create_time different. Ancien
    format (pid seul, sans ":") -> None (pas d'horodatage a comparer)."""
    try:
        raw = Path(path).read_text(encoding="ascii").strip()
        if ":" not in raw:
            return None
        return float(raw.split(":", 1)[1])
    except (OSError, ValueError):
        return None


def write_pid_file(path: Path, pid: int, start_ts=None):
    """Ecrit "pid:ts" (FIX 1, anti-recyclage). `start_ts` = horodatage de
    demarrage ; par defaut l'instant courant (suffisant comme borne basse)."""
    ts = time.time() if start_ts is None else float(start_ts)
    Path(path).write_text(f"{int(pid)}:{ts:.3f}", encoding="ascii")


def remove_pid_file(path: Path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def pid_alive(pid) -> bool:
    """
    Le process existe-t-il encore ? psutil si dispo ; sinon tasklist (Windows)
    ou os.kill(pid, 0) (unix). ATTENTION : ne JAMAIS utiliser os.kill(pid, 0)
    sous Windows — la, tout signal != CTRL_* TUE le process (TerminateProcess).
    """
    if pid is None:
        return False
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except ImportError:
        pass
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10).stdout
            return f'"{int(pid)}"' in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        # EPERM : le process EXISTE mais appartient a un autre utilisateur -- vivant.
        # (Le traiter comme mort ferait croire le service arrete a tort.)
        return True
    except OSError:
        return False


def is_our_process(pid, service, start_ts=None) -> bool:
    """
    FIX 1 (SECURITE) : ce PID est-il BIEN notre `service` (paper/monitor) ?

    Windows recycle les PID : apres un crash/reboot, un pid file peut pointer un
    process TIERS vivant. On REFUSE de tuer tant qu'on n'a pas confirme l'identite.

    Strategie, de la plus fiable a la plus prudente :
      1. psutil dispo -> la cmdline doit contenir "main.py" ET `service`
         ("paper"/"monitor"). Si `start_ts` connu, create_time() doit coincider
         (tolerance quelques secondes) -- defense anti-recyclage supplementaire.
      2. Windows sans psutil -> `tasklist /FI "PID eq N" /FO CSV` : l'image DOIT
         etre python*.exe (sinon ce n'est pas nous : refus).
      3. Unix sans psutil -> /proc/<pid>/cmdline doit contenir "main.py" ET
         `service`. Pas de /proc -> on REFUSE (prudence par defaut).
    En cas de doute on renvoie False : ne jamais tuer un process non confirme.
    """
    if pid is None:
        return False
    try:
        import psutil
        try:
            p = psutil.Process(int(pid))
            cmd = " ".join(p.cmdline()).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return False
        if "main.py" not in cmd or service not in cmd:
            return False
        if start_ts is not None:
            try:
                if abs(p.create_time() - float(start_ts)) > 5.0:
                    return False
            except (psutil.Error, OSError, ValueError):
                pass  # create_time indisponible : la cmdline reste un bon indice
        return True
    except ImportError:
        pass
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        if f'"{int(pid)}"' not in out:
            return False                       # PID absent : rien a tuer
        # 1re colonne CSV = nom de l'image ; doit etre python*.exe (sinon : tiers).
        first = out.strip().splitlines()[0] if out.strip() else ""
        image = first.split('","')[0].lstrip('"').lower() if first else ""
        return image.startswith("python")
    # Unix sans psutil : /proc si dispo, sinon refus prudent.
    proc_cmd = Path(f"/proc/{int(pid)}/cmdline")
    try:
        raw = proc_cmd.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace").lower()
    except OSError:
        return False                           # /proc absent ou illisible : on REFUSE
    return "main.py" in raw and service in raw


def port_in_use(port=MONITOR_PORT, host=MONITOR_HOST) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


# Signature HTML servie par notre monitor (titre de page, cf. trading/monitor.py).
MONITOR_SIGNATURE = "Paper trading - monitoring"


def monitor_signature_present(url=MONITOR_URL) -> bool:
    """
    FIX 4 : le serveur qui repond sur le port est-il BIEN notre monitor ?

    On fait un GET court sur `url` et on cherche la signature de la page du
    monitor (MONITOR_SIGNATURE). Un autre service qui squatte le port ne la
    contient pas -> on ne pretend pas a tort que c'est le monitor.
    Tolerant aux erreurs (timeout, refus) -> False (on ne suppose jamais que
    c'est nous sans preuve).
    """
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            body = resp.read(65536).decode("utf-8", "replace")
        return MONITOR_SIGNATURE in body
    except Exception:
        return False


# ----------------------------------------------------------------------------- #
#  Lancement detache + arret propre                                               #
# ----------------------------------------------------------------------------- #
def spawn_detached(cmd, log_path: Path, cwd: Path) -> int:
    """Popen detache cross-platform, console redirigee vers log_path (append)."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    else:
        kwargs["start_new_session"] = True
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, cwd=str(cwd), **kwargs)
    return proc.pid


def _wait_dead(pid, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    return not pid_alive(pid)


def terminate_pid(pid, timeout=5.0) -> bool:
    """Termine proprement (terminate) puis force (kill) si besoin. True = mort."""
    try:
        import psutil
        try:
            p = psutil.Process(int(pid))
            p.terminate()
            try:
                p.wait(timeout=timeout)
            except psutil.TimeoutExpired:
                p.kill()
                p.wait(timeout=timeout)
        except psutil.NoSuchProcess:
            pass
        return not pid_alive(pid)
    except ImportError:
        pass
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T"], capture_output=True)
        if not _wait_dead(pid, timeout):
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                           capture_output=True)
    else:
        import signal
        try:
            os.kill(int(pid), signal.SIGTERM)
            if not _wait_dead(pid, timeout):
                os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass
    return _wait_dead(pid, timeout=2.0)


# ----------------------------------------------------------------------------- #
#  Actions                                                                        #
# ----------------------------------------------------------------------------- #
_SERVICES = ("paper", "monitor")


def do_dry_run(root: Path) -> int:
    run_dir, logs_dir = ensure_dirs(root)
    print("DRY-RUN : rien n'est lance. Voici ce que `python lancer.py` ferait :\n")
    print("1) Diagnostic :")
    print("   " + format_cmd(build_check_command(root)))
    print("2) Paper trading (detache, console -> logs/paper_console.log) :")
    print("   " + format_cmd(build_paper_command(root)))
    print(f"   PID ecrit dans {run_dir / 'paper.pid'}")
    print("3) Monitoring (detache, console -> logs/monitor_console.log) :")
    print("   " + format_cmd(build_monitor_command(root)))
    print(f"   PID ecrit dans {run_dir / 'monitor.pid'}")
    print(f"4) Ouverture du navigateur sur {MONITOR_URL}")
    print("\nGarde-fou : PAPER-ONLY par construction (le mode reel est "
          "inconstructible par ce lanceur).")
    return 0


def do_status(root: Path) -> int:
    run_dir, _ = ensure_dirs(root)
    for name in _SERVICES:
        pid = read_pid_file(run_dir / f"{name}.pid")
        if pid is None:
            print(f"{name:8s}: pas de fichier pid (non demarre via ce lanceur)")
        elif pid_alive(pid):
            print(f"{name:8s}: EN COURS (PID {pid})")
        else:
            print(f"{name:8s}: ARRETE (pid {pid} orphelin dans run/{name}.pid)")
    etat = "repond" if port_in_use() else "ne repond pas"
    print(f"monitor : le port {MONITOR_PORT} {etat} ({MONITOR_URL})")
    return 0


def do_stop(root: Path) -> int:
    run_dir, _ = ensure_dirs(root)
    code = 0
    for name in _SERVICES:
        pid_path = run_dir / f"{name}.pid"
        pid = read_pid_file(pid_path)
        if pid is None:
            print(f"{name:8s}: rien a arreter (pas de fichier pid).")
            continue
        if not pid_alive(pid):
            remove_pid_file(pid_path)
            print(f"{name:8s}: deja arrete (pid {pid} orphelin, fichier nettoye).")
            continue
        # FIX 1 (SECURITE) : avant TOUT kill, confirmer que ce PID est BIEN notre
        # service. Windows recycle les PID -> un pid file rance peut pointer un
        # process TIERS vivant ; on ne le tue JAMAIS. Identite non confirmee ->
        # on nettoie le fichier et on s'abstient.
        if not is_our_process(pid, name, read_pid_start(pid_path)):
            remove_pid_file(pid_path)
            print(f"{name:8s}: PID {pid} recycle par un autre process "
                  f"(identite non confirmee) -- NON tue, pid file nettoye.")
            continue
        if terminate_pid(pid):
            remove_pid_file(pid_path)
            print(f"{name:8s}: arrete (PID {pid}).")
        else:
            code = 1
            print(f"{name:8s}: ECHEC de l'arret du PID {pid} "
                  f"(arrete-le a la main, puis supprime run/{name}.pid).")
    return code


def _start_service(name, cmd, run_dir: Path, logs_dir: Path, root: Path):
    """Demarre un service detache si pas deja vivant. Retourne le PID ou None."""
    pid_path = run_dir / f"{name}.pid"
    pid = read_pid_file(pid_path)
    if pid is not None and pid_alive(pid):
        print(f"{name:8s}: deja en cours (PID {pid}) -- on ne double pas.")
        return pid
    if pid is not None:
        remove_pid_file(pid_path)  # pid orphelin (process mort) : on nettoie
    log_path = logs_dir / f"{name}_console.log"
    new_pid = spawn_detached(cmd, log_path, cwd=root)
    # FIX 1) on stocke "pid:ts". Si psutil est dispo, on prend le create_time()
    # REEL du process (pour que la comparaison anti-recyclage tombe juste) ;
    # sinon time.time() (borne basse suffisante).
    write_pid_file(pid_path, new_pid, _process_start_ts(new_pid))
    print(f"{name:8s}: demarre (PID {new_pid}, console -> {log_path})")
    return new_pid


def _process_start_ts(pid):
    """create_time() du process si psutil dispo, sinon l'instant courant."""
    try:
        import psutil
        return psutil.Process(int(pid)).create_time()
    except Exception:
        return time.time()


def do_start(root: Path) -> int:
    run_dir, logs_dir = ensure_dirs(root)

    # 1) Diagnostic (la sortie de `main.py check` est deja actionnable).
    print("Etape 1/4 -- diagnostic (main.py check)...")
    rc = subprocess.run(build_check_command(root), cwd=str(root)).returncode
    if rc != 0:
        print("\nLe diagnostic a echoue (voir les messages ci-dessus).")
        print("Corrige le probleme (SETUP.md) puis relance. Rien n'a ete demarre.")
        return 1

    # 2) Paper trading (detache).
    print("Etape 2/4 -- paper trading...")
    _start_service("paper", build_paper_command(root), run_dir, logs_dir, root)

    # 3) Monitoring : si le port repond deja, on ne le reutilise QUE si c'est
    # bien NOTRE monitor (FIX 4 : verif de signature). Un squatteur du port ne
    # doit pas etre confondu avec le monitor.
    print("Etape 3/4 -- monitoring...")
    monitor_ok = False
    if port_in_use():
        if monitor_signature_present():
            print(f"monitor : notre serveur repond deja sur {MONITOR_URL} -- reutilise.")
            monitor_ok = True
        else:
            print(f"monitor : le port {MONITOR_PORT} est OCCUPE par un AUTRE service "
                  f"(signature du monitor absente). Le monitoring n'est PAS demarre ; "
                  f"libere le port ou change MONITOR_PORT.")
    else:
        _start_service("monitor", build_monitor_command(root), run_dir, logs_dir, root)
        monitor_ok = True

    # 4) Navigateur : on n'ouvre que si un monitor est reellement la (le notre,
    # neuf ou reutilise) -- jamais pour pointer un service tiers.
    if monitor_ok:
        print("Etape 4/4 -- ouverture du navigateur...")
        webbrowser.open(MONITOR_URL)
    else:
        print("Etape 4/4 -- navigateur non ouvert (pas de monitor fiable sur le port).")

    print("\n--- Resume ---")
    for name in _SERVICES:
        pid = read_pid_file(run_dir / f"{name}.pid")
        etat = f"PID {pid}" if (pid is not None and pid_alive(pid)) else "non gere par ce lanceur"
        print(f"  {name:8s}: {etat}")
    print(f"  Tableau de bord : {MONITOR_URL}")
    print(f"  Logs            : {logs_dir / 'paper_console.log'} / "
          f"{logs_dir / 'monitor_console.log'}")
    print("  Arret           : arreter.bat (Windows) ou `python lancer.py --stop`")
    print("  Mode            : PAPER uniquement (argent fictif, aucune cle requise).")
    return 0


# ----------------------------------------------------------------------------- #
#  Entree CLI                                                                     #
# ----------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(
        description="Lanceur paper trading + monitoring (PAPER-ONLY, double-clic).")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--stop", action="store_true", help="arrete paper + monitor")
    g.add_argument("--status", action="store_true", help="montre ce qui tourne")
    g.add_argument("--dry-run", action="store_true",
                   help="montre ce qui serait lance, sans rien lancer")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = project_root()
    if args.dry_run:
        return do_dry_run(root)
    if args.status:
        return do_status(root)
    if args.stop:
        return do_stop(root)
    return do_start(root)


if __name__ == "__main__":
    sys.exit(main())
