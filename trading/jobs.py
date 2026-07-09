"""
Gestionnaire de jobs asynchrones EN MEMOIRE (Lot 3), UN SEUL job actif a la
fois -- choix delibere (spec §7.2/§10 : usage solo, pas un service
multi-tenant). Les commandes de recherche potentiellement longues (backtest,
compare, optimize, walkforward, portfolio -- Lots 4-6) tourneront dans un
thread worker separe pour ne JAMAIS bloquer le thread HTTP qui sert une
requete (cf. trading/monitor.py).

Rien n'est ecrit sur disque : un redemarrage du serveur perd tous les jobs
(comportement voulu). Aucune donnee sensible n'est loggee (les futurs
runners restent responsables de ne pas logger de cle/secret).

Contrat pour les runners (Lots 4-6) :

    def mon_runner(progress):
        progress.log("etape 1...")
        if progress.cancelled:
            return None
        progress.set_percent(50)
        ...
        return resultat            # objet quelconque, recupere via result()

    manager = JobManager()
    job_id = manager.submit(mon_runner, label="Backtest SMA")
    manager.status(job_id)         # dict JSON-safe -> GET /job/<id>/status
    manager.cancel(job_id)         # cooperatif (positionne un drapeau)
    manager.result(job_id)         # valeur de retour de `target`, ou None

`submit()` leve `JobBusy` si un job est deja pending/running -- PAS de file
d'attente silencieuse : l'appelant (route HTTP) doit proposer a
l'utilisateur d'attendre/annuler le job en cours.
"""
import threading
import time
import uuid

_TERMINAL_STATES = ("done", "error", "cancelled")


class JobBusy(Exception):
    """Leve par JobManager.submit() quand un job est deja pending/running."""


class JobProgress:
    """
    Passe au `target` d'un job (une instance par job, jamais partagee).
    Permet de logger, avancer un pourcentage optionnel, et observer une
    demande d'annulation cooperative -- le `target` doit lire `cancelled`
    lui-meme et s'arreter ; rien ici ne tue le thread de force.
    """

    def __init__(self, manager, job_id):
        self._manager = manager
        self._job_id = job_id

    def log(self, message):
        self._manager._append_log(self._job_id, message)

    def set_percent(self, value):
        self._manager._set_percent(self._job_id, value)

    @property
    def cancelled(self):
        return self._manager._is_cancelled(self._job_id)


class JobManager:
    """
    Gestionnaire mono-job EN MEMOIRE. Thread-safe : un seul `threading.Lock`
    protege tout l'etat partage (dict des jobs + ordre d'insertion + id du
    job actif). Aucune methode ne leve pendant qu'elle tient le verrou plus
    que le temps d'une lecture/ecriture de dict -- le `target` du job
    s'execute HORS verrou (sinon un `target` qui logge beaucoup bloquerait
    les autres appels).
    """

    def __init__(self, max_history=8, max_log_lines=500):
        self._lock = threading.Lock()
        self._jobs = {}          # job_id -> dict d'etat interne
        self._order = []         # ordre d'insertion (retention des N derniers)
        self._active_id = None   # job pending/running courant (un seul autorise)
        self._max_history = max_history
        self._max_log_lines = max_log_lines

    @property
    def active_id(self):
        """Id du job pending/running courant, ou None. Lecture seule utile aux appelants."""
        with self._lock:
            return self._active_id

    def submit(self, target, label=""):
        """
        Lance `target(progress)` dans un thread worker daemon et retourne le
        job_id (str, uuid4 hex 32 caracteres -- format valide dans une URL).
        Leve `JobBusy` si un job est deja pending/running (pas de file
        d'attente silencieuse).
        """
        with self._lock:
            active = self._jobs.get(self._active_id) if self._active_id else None
            if active is not None and active["state"] not in _TERMINAL_STATES:
                raise JobBusy(f"Un job est deja en cours : {active['label']!r}")
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {
                "id": job_id,
                "label": label or "",
                "state": "pending",
                "log": [],
                "percent": None,
                "result": None,
                "has_result": False,
                "error_message": None,
                "cancelled": False,
                "created": time.time(),
            }
            self._order.append(job_id)
            self._active_id = job_id
            self._trim_history_locked()

        thread = threading.Thread(target=self._run, args=(job_id, target), daemon=True)
        thread.start()
        return job_id

    def _run(self, job_id, target):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return  # deja evince (historique tres court) -- ne peut arriver en pratique
            job["state"] = "running"

        progress = JobProgress(self, job_id)
        try:
            result = target(progress)
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job["state"] = "error"
                    # Message seul (pas de stacktrace : peut contenir des chemins/donnees).
                    job["error_message"] = str(exc) or exc.__class__.__name__
        else:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    if job["cancelled"]:
                        job["state"] = "cancelled"
                    else:
                        job["state"] = "done"
                        job["result"] = result
                        job["has_result"] = result is not None
        finally:
            with self._lock:
                if self._active_id == job_id:
                    self._active_id = None

    def status(self, job_id):
        """
        Dict JSON-safe decrivant l'etat du job, ou None si id inconnu (jamais
        vu ou evince de l'historique). NE contient JAMAIS le resultat lui-meme
        (cf. `result()`) -- seulement `has_result` (booleen) pour que
        l'appelant sache s'il doit aller chercher/rediriger vers le rapport.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                "id": job["id"],
                "label": job["label"],
                "state": job["state"],
                "log": list(job["log"]),
                "percent": job["percent"],
                "has_result": job["has_result"],
                "error_message": job["error_message"],
            }

    def cancel(self, job_id):
        """
        Demande cooperative d'annulation (positionne `cancelled` -- le
        `target` doit l'observer via `progress.cancelled`). Ne tue jamais le
        thread de force. Retourne True si le job existe et etait
        pending/running, False sinon (id inconnu ou job deja termine).
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["state"] in _TERMINAL_STATES:
                return False
            job["cancelled"] = True
            return True

    def result(self, job_id):
        """Valeur de retour de `target` pour ce job, ou None (inconnu / pas termine / pas de resultat)."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job["result"] if job is not None else None

    # -- appeles depuis JobProgress, deja depuis le thread worker ----------

    def _append_log(self, job_id, message):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["log"].append(str(message))
            if len(job["log"]) > self._max_log_lines:
                job["log"] = job["log"][-self._max_log_lines:]

    def _set_percent(self, job_id, value):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["percent"] = value

    def _is_cancelled(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job["cancelled"])

    def _trim_history_locked(self):
        """Appele SOUS verrou : ne garde que les N derniers jobs soumis (libere la RAM)."""
        while len(self._order) > self._max_history:
            old_id = self._order.pop(0)
            if old_id != self._active_id:
                self._jobs.pop(old_id, None)
