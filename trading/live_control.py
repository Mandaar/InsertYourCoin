"""
Controle SERVEUR du live (Lot 8, argent reel) -- nonce d'armement, identite
PID, spawn detache, sidecar d'etat. Cf. docs/design/LOT8_LIVE_SPEC.md.

Design (voir spec) :
- Le process live est un PROCESS DETACHE (patron paper/lancer.py), PAS un
  thread du serveur web ni un job JobManager (spec §3.1 : la boucle du
  trader est un `while True` infini que JobManager ne sait pas annuler
  proprement).
- Ce module est le SEUL chemin autorise a construire "main.py live
  [--execute]" -- `lancer.py` NE construit JAMAIS de commande live
  (assert_paper_only, garde N7) : on reutilise ses helpers d'identite/PID
  (is_our_process, read_pid_file/write_pid_file, terminate_pid -- BUG-009)
  mais on NE PASSE JAMAIS par ses `build_*_command` paper-only.
- Aucune cle API ne transite JAMAIS par argument ni variable d'environnement
  du subprocess : le process live relit lui-meme .env via config.py a son
  propre demarrage (§3.3). Le sidecar run/live.json ne contient AUCUNE cle.
- Spawn dedouble en local (comme monitor.py._spawn_paper_detached /
  _spawn_detached_monitor) plutot qu'importe de lancer.py -- meme raison :
  pas de dependance croisee root <-> package pour cette mecanique bas niveau.
"""
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import lancer

# Phrase EXACTE de confirmation (source de verite, main.py:276). Le serveur la
# compare apres .strip(), a l'identique de la CLI (N5).
PHRASE_CONFIRMATION = "OUI JE CONFIRME"

# Nonce d'armement : usage unique, TTL court, plafond de tentatives de phrase
# (spec §2.2/§7.2, valeurs recommandees).
ARM_TOKEN_TTL_SEC = 120
ARM_TOKEN_MAX_ATTEMPTS = 3

# Les 3 attestations utilisateur (famille B, spec §1.2 points 4-6). Cases a
# cocher : PAS des preuves verifiables, une reconnaissance exigee avant tout
# armement reel.
ATTESTATION_FIELDS = ("attest_no_withdraw", "attest_paper_done", "attest_caps_read")


# --------------------------------------------------------------------------- #
#  Pre-requis VERIFIABLES par le serveur (famille A, spec §1.2) --            #
#  re-testes a CHAQUE round-trip (arm ET start), jamais mis en cache (N10).   #
# --------------------------------------------------------------------------- #
def check_prerequisites_a(keys_ok: bool, check_ok: bool, paper_ever_started: bool) -> dict:
    """Fonction PURE : {"ok": bool, "missing": [codes]}. `missing` liste les
    pre-requis fautifs parmi "keys"/"check"/"paper" (jamais plus d'un
    booleen agrege -- le mur doit surligner CHAQUE pre-requis, spec §1.1)."""
    missing = []
    if not keys_ok:
        missing.append("keys")
    if not check_ok:
        missing.append("check")
    if not paper_ever_started:
        missing.append("paper")
    return {"ok": not missing, "missing": missing}


def attestations_ok(form: dict) -> bool:
    """Les 3 attestations (famille B) sont-elles TOUTES presentes ET cochees
    ('1') dans le POST ? Fonction PURE."""
    return all(form.get(name) == "1" for name in ATTESTATION_FIELDS)


def resolve_execute(form: dict) -> bool:
    """True SSI form["mode"] == "reel" (exactement). Absent/"dry"/toute autre
    valeur -> False -- fail-safe (N3) : un `mode` ambigu ne demarre JAMAIS le
    reel. Fonction PURE."""
    return (form.get("mode") or "").strip().lower() == "reel"


def phrase_ok(phrase) -> bool:
    """Vrai SSI phrase.strip() == PHRASE_CONFIRMATION EXACTEMENT -- identique
    a `input(...).strip() != "OUI JE CONFIRME"` (main.py:276). Casse
    sensible, pas de `startswith`, pas de tolerance (N5). Fonction PURE."""
    if phrase is None:
        return False
    return str(phrase).strip() == PHRASE_CONFIRMATION


# --------------------------------------------------------------------------- #
#  Nonce d'armement -- store EN MEMOIRE (spec §2.2/§7.2)                      #
# --------------------------------------------------------------------------- #
class ArmTokenStore:
    """
    Store de nonces d'armement, EN MEMOIRE serveur (jamais persiste -- un
    redemarrage du serveur invalide tout armement en cours, friction
    assumee). Un nonce est :
      - USAGE UNIQUE : `consume()` le retire definitivement, un 2e appel
        echoue toujours (test_nonce_usage_unique) ;
      - a TTL COURT (defaut 120 s) : expire silencieusement, `peek_params`/
        `consume` renvoient None au-dela (test_nonce_expire_apres_ttl) ;
      - LIE AUX PARAMETRES valides au moment de l'armement : `consume()`
        renvoie TOUJOURS les params figes a la creation, jamais des params
        resoumis au start (test_nonce_lie_aux_parametres) ;
      - a PLAFOND DE TENTATIVES de phrase : `register_failed_phrase()`
        invalide le nonce des que le plafond est atteint, MAIS ne le
        consomme pas sur un echec (le nonce reste utilisable pour un retry
        tant que le plafond n'est pas atteint -- spec §1.4.5).
    """

    def __init__(self, ttl_seconds=ARM_TOKEN_TTL_SEC, max_attempts=ARM_TOKEN_MAX_ATTEMPTS):
        self._tokens = {}
        self.ttl_seconds = ttl_seconds
        self.max_attempts = max_attempts

    def create(self, params: dict, now=None) -> str:
        """Genere un nonce `secrets.token_hex` (patron monitor.py csrf_token),
        y attache une COPIE des params (immutabilite -- resoumettre d'autres
        valeurs au start ne les change jamais)."""
        ts = time.time() if now is None else now
        nonce = secrets.token_hex(32)
        self._tokens[nonce] = {
            "params": dict(params),
            "created": ts,
            "attempts": 0,
            "consumed": False,
        }
        return nonce

    def _valid_entry(self, nonce, now=None):
        """Entree si CONNUE, NON consommee et NON expiree ; sinon None (et
        l'entree expiree est nettoyee -- ne fuit pas la memoire)."""
        if not nonce:
            return None
        entry = self._tokens.get(nonce)
        if entry is None or entry["consumed"]:
            return None
        ts = time.time() if now is None else now
        if ts - entry["created"] > self.ttl_seconds:
            self._tokens.pop(nonce, None)
            return None
        return entry

    def peek_params(self, nonce, now=None):
        """Params lies au nonce SI valide (non consomme/expire), SANS
        consommer ni compter de tentative -- sert a re-verifier a chaque
        etape (mode, pre-requis) AVANT de statuer sur la phrase."""
        entry = self._valid_entry(nonce, now)
        return dict(entry["params"]) if entry else None

    def register_failed_phrase(self, nonce, now=None) -> bool:
        """Phrase fausse soumise pour ce nonce : incremente le compteur de
        tentatives. Retourne False (et INVALIDE/retire le nonce) des que le
        plafond `max_attempts` est atteint ; True si le nonce reste
        utilisable pour un nouvel essai. Nonce deja invalide -> False."""
        entry = self._valid_entry(nonce, now)
        if entry is None:
            return False
        entry["attempts"] += 1
        if entry["attempts"] >= self.max_attempts:
            self._tokens.pop(nonce, None)
            return False
        return True

    def consume(self, nonce, now=None):
        """Consomme le nonce (USAGE UNIQUE) SI valide et retourne une copie
        de ses params ; sinon None. Toujours appele APRES verification de la
        phrase -- un echec de phrase ne consomme JAMAIS le nonce (cf.
        register_failed_phrase)."""
        entry = self._valid_entry(nonce, now)
        if entry is None:
            return None
        params = dict(entry["params"])
        self._tokens.pop(nonce, None)
        return params


# --------------------------------------------------------------------------- #
#  Construction de la commande live -- SEUL chemin autorise (N7)              #
# --------------------------------------------------------------------------- #
def build_live_command(root: Path, params: dict, execute: bool, python=None):
    """
    Construit `main.py live [--execute] ...` depuis les PARAMETRES valides.
    JAMAIS depuis lancer.py (assert_paper_only y bloquerait "live" -- ce
    module est le SEUL chemin autorise a construire cette commande).

    JAMAIS de plafond en argument (N4) : MAX_TRADE_VALUE_USD/
    MAX_POSITION_VALUE_USD/MIN_TRADE_INTERVAL_SEC restent lus de config.py
    par le process live lui-meme (trading/live_trader.py._rebalance) -- rien
    ici ne peut les surcharger, il n'existe d'ailleurs aucun flag CLI pour
    ca (main.py, parser `live`). JAMAIS de `--source` (live = 100% Kraken).
    JAMAIS de cle API en argument (N6) -- le subprocess lit son .env lui-meme.
    """
    python = python or sys.executable
    cmd = [python, "-u", str(root / "main.py"), "live",
          "--strategy", str(params.get("strategy") or "sma"),
          "--symbol", str(params.get("symbol") or ""),
          "--timeframe", str(params.get("timeframe") or "1d")]
    if params.get("stop_loss") is not None:
        cmd += ["--stop-loss", str(params["stop_loss"])]
    if params.get("take_profit") is not None:
        cmd += ["--take-profit", str(params["take_profit"])]
    if params.get("trailing_stop") is not None:
        cmd += ["--trailing-stop", str(params["trailing_stop"])]
    position_sizing = params.get("position_sizing")
    if position_sizing and position_sizing != "none":
        cmd += ["--position-sizing", str(position_sizing)]
        if params.get("target_vol") is not None:
            cmd += ["--target-vol", str(params["target_vol"])]
    if execute:
        cmd.append("--execute")
    return cmd


# --------------------------------------------------------------------------- #
#  Fichiers d'etat live (run/live.pid + run/live.json) -- spec §3.5/§7.3      #
# --------------------------------------------------------------------------- #
def live_pid_path(root: Path) -> Path:
    return root / "run" / "live.pid"


def live_sidecar_path(root: Path) -> Path:
    return root / "run" / "live.json"


def live_identity(root: Path):
    """
    Lit run/live.pid et confirme l'IDENTITE du process (BUG-009 : Windows
    RECYCLE les PID). Retourne (pid, running, start_ts) -- meme patron que
    monitor.py._paper_identity. Un pid file orphelin/recycle est NETTOYE ici
    et jamais traite comme "en cours" par la suite.
    """
    pid_path = live_pid_path(root)
    pid = lancer.read_pid_file(pid_path)
    if pid is None:
        return None, False, None
    start_ts = lancer.read_pid_start(pid_path)
    if lancer.is_our_process(pid, "live", start_ts):
        return pid, True, start_ts
    lancer.remove_pid_file(pid_path)  # orphelin/recycle : nettoye, traite ARRETE
    return None, False, None


def write_live_sidecar(path: Path, data: dict) -> None:
    """Ecrit run/live.json (autorite serveur, §3.5) -- SANS AUCUNE CLE, au
    moment du spawn, jamais depuis le client. Laisse OSError remonter (M9) :
    l'appelant journalise (meme patron que paper_ui_error.log)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")


def read_live_sidecar(path) -> dict | None:
    """Lit run/live.json. None si absent/illisible (jamais d'exception)."""
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def remove_live_sidecar(path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- #
#  Spawn detache du process live (§3.4)                                       #
# --------------------------------------------------------------------------- #
def spawn_live_detached(cmd, log_path: Path, cwd: Path, stdin_bytes: bytes = None) -> int:
    """
    Lance `main.py live [--execute]` DETACHE -- meme recette robuste que
    monitor.py._spawn_paper_detached/_spawn_detached_monitor (DETACHED_
    PROCESS|CREATE_NO_WINDOW sous Windows : zero fenetre console ; repli
    DEVNULL si le log est verrouille, BUG-014), dupliquee en local pour la
    meme raison (pas de dependance croisee).

    `stdin_bytes` (mode REEL uniquement, §3.4) : la phrase de confirmation
    est ECRITE dans le stdin du subprocess PUIS FERMEE -- `cmd_live`
    (main.py) reste INCHANGE, son `input().strip()` lit CETTE phrase et
    RE-VALIDE au niveau process (3e rempart). None (dry-run) -> stdin=DEVNULL
    (aucune confirmation necessaire, aucun ordre de toute facon).

    Ne fait JAMAIS `wait()` -- le process reste detache (survit au serveur
    web, spec §3.6).
    """
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    else:
        kwargs["start_new_session"] = True
    try:
        log = open(log_path, "ab")
    except OSError:
        log = None
    stdin_target = subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            cmd, stdin=stdin_target,
            stdout=(log if log is not None else subprocess.DEVNULL),
            stderr=(log if log is not None else subprocess.DEVNULL),
            cwd=str(cwd), **kwargs)
    finally:
        if log is not None:
            log.close()
    if stdin_bytes is not None:
        try:
            proc.stdin.write(stdin_bytes)
            proc.stdin.flush()
        finally:
            proc.stdin.close()
    return proc.pid


def start_live_process(root: Path, params: dict, execute: bool):
    """
    Orchestre le demarrage du live : construit la commande (build_live_
    command), spawn detache (spawn_live_detached -- MONKEYPATCHABLE par les
    tests, aucun reseau/process reel en test), ecrit le pid file (patron
    BUG-009 "pid:ts") + le sidecar (§3.5, sans cle). Retourne (pid, start_ts).

    Leve OSError si le spawn echoue -- JAMAIS avale silencieusement (M9,
    meme patron que monitor.py._start_paper_from_params).
    """
    cmd = build_live_command(root, params, execute)
    run_dir, logs_dir = lancer.ensure_dirs(root)
    log_path = logs_dir / "live_console.log"  # BUG-014 : log DEDIE au live
    stdin_bytes = (PHRASE_CONFIRMATION + "\n").encode("utf-8") if execute else None
    new_pid = spawn_live_detached(cmd, log_path, root, stdin_bytes=stdin_bytes)
    start_ts = lancer._process_start_ts(new_pid)
    lancer.write_pid_file(live_pid_path(root), new_pid, start_ts)
    write_live_sidecar(live_sidecar_path(root), {
        "mode": "reel" if execute else "dry",
        "strategy": params.get("strategy"),
        "symbol": params.get("symbol"),
        "timeframe": params.get("timeframe"),
        "pid": new_pid,
        "start_ts": start_ts,
    })
    return new_pid, start_ts
