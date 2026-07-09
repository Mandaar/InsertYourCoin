"""
Tests du gestionnaire de jobs asynchrones (Lot 3) : trading/jobs.py.

Aucun reseau, aucun disque -- uniquement des threads. Les points de
synchronisation utilisent des `threading.Event` (jamais de sleep pour
"esperer" un etat : on attend explicitement le signal, avec un timeout de
securite pour ne jamais bloquer indefiniment un run pytest).
"""
import threading
import time

import pytest

from trading.jobs import JobBusy, JobManager


def _wait_terminal(mgr, job_id, timeout=2.0):
    """Poll borne (timeout) jusqu'a un etat terminal -- pas de sleep aveugle."""
    deadline = time.time() + timeout
    st = mgr.status(job_id)
    while st and st["state"] not in ("done", "error", "cancelled") and time.time() < deadline:
        time.sleep(0.01)
        st = mgr.status(job_id)
    return st


# --------------------------------------------------------------------------- #
#  Cycle de vie : pending -> running -> done + resultat                       #
# --------------------------------------------------------------------------- #
def test_job_lifecycle_done_with_result():
    mgr = JobManager()
    started = threading.Event()
    release = threading.Event()

    def target(progress):
        started.set()
        assert release.wait(timeout=2)
        progress.log("etape 1")
        progress.set_percent(50)
        progress.log("etape 2")
        return {"ok": True}

    job_id = mgr.submit(target, label="mon job")
    assert started.wait(timeout=2)
    assert mgr.status(job_id)["state"] == "running"

    release.set()
    st = _wait_terminal(mgr, job_id)
    assert st["state"] == "done"
    assert st["label"] == "mon job"
    assert st["log"] == ["etape 1", "etape 2"]
    assert st["percent"] == 50
    assert st["has_result"] is True
    assert st["error_message"] is None
    assert mgr.result(job_id) == {"ok": True}


def test_job_status_unknown_id_returns_none():
    mgr = JobManager()
    assert mgr.status("id-inconnu") is None
    assert mgr.result("id-inconnu") is None


def test_job_status_never_leaks_result_value():
    # `status()` ne doit JAMAIS embarquer le resultat lui-meme (seulement
    # has_result) -- c'est result() qui le porte, pour ne pas gonfler le
    # payload JSON de /job/<id>/status a chaque poll.
    mgr = JobManager()
    job_id = mgr.submit(lambda p: {"secret": "valeur-sensible"})
    st = _wait_terminal(mgr, job_id)
    assert st["state"] == "done"
    assert "result" not in st
    assert "secret-not-in-status" not in str(st)


# --------------------------------------------------------------------------- #
#  Capture d'erreur                                                           #
# --------------------------------------------------------------------------- #
def test_job_lifecycle_error_captured():
    mgr = JobManager()

    def target(progress):
        progress.log("avant l'echec")
        raise ValueError("kaboom")

    job_id = mgr.submit(target)
    st = _wait_terminal(mgr, job_id)
    assert st["state"] == "error"
    assert "kaboom" in st["error_message"]
    assert st["has_result"] is False
    assert mgr.result(job_id) is None


# --------------------------------------------------------------------------- #
#  Annulation cooperative                                                     #
# --------------------------------------------------------------------------- #
def test_job_cancellation_cooperative():
    mgr = JobManager()
    started = threading.Event()

    def target(progress):
        started.set()
        while not progress.cancelled:
            time.sleep(0.01)
        return None

    job_id = mgr.submit(target)
    assert started.wait(timeout=2)
    assert mgr.cancel(job_id) is True

    st = _wait_terminal(mgr, job_id)
    assert st["state"] == "cancelled"


def test_cancel_unknown_job_returns_false():
    mgr = JobManager()
    assert mgr.cancel("id-inconnu") is False


def test_cancel_already_terminal_job_returns_false():
    mgr = JobManager()
    job_id = mgr.submit(lambda p: None)
    _wait_terminal(mgr, job_id)
    assert mgr.cancel(job_id) is False


# --------------------------------------------------------------------------- #
#  Un seul job actif a la fois                                                #
# --------------------------------------------------------------------------- #
def test_submit_refuses_second_job_while_one_running():
    mgr = JobManager()
    started = threading.Event()
    release = threading.Event()

    def blocking(progress):
        started.set()
        release.wait(timeout=2)
        return None

    job_id = mgr.submit(blocking, label="premier")
    assert started.wait(timeout=2)

    with pytest.raises(JobBusy):
        mgr.submit(lambda p: None, label="second")

    release.set()
    _wait_terminal(mgr, job_id)

    # Une fois le premier termine, un nouveau submit redevient possible.
    job_id_2 = mgr.submit(lambda p: "ok")
    st = _wait_terminal(mgr, job_id_2)
    assert st["state"] == "done"


# --------------------------------------------------------------------------- #
#  Retention des N derniers jobs (liberation memoire)                         #
# --------------------------------------------------------------------------- #
def test_retention_keeps_only_last_n_jobs():
    mgr = JobManager(max_history=3)
    ids = []
    for i in range(5):
        job_id = mgr.submit(lambda p: None, label=f"job{i}")
        _wait_terminal(mgr, job_id)
        ids.append(job_id)

    assert mgr.status(ids[0]) is None
    assert mgr.status(ids[1]) is None
    assert mgr.status(ids[2]) is not None
    assert mgr.status(ids[3]) is not None
    assert mgr.status(ids[4]) is not None


# --------------------------------------------------------------------------- #
#  Thread-safety de surface (pas de crash sous acces concurrents)             #
# --------------------------------------------------------------------------- #
def test_concurrent_status_polling_does_not_crash():
    mgr = JobManager()
    started = threading.Event()
    release = threading.Event()

    def target(progress):
        started.set()
        for i in range(20):
            progress.log(f"ligne {i}")
            progress.set_percent(i * 5)
        release.wait(timeout=2)
        return "fini"

    job_id = mgr.submit(target)
    assert started.wait(timeout=2)

    errors = []

    def poller():
        try:
            for _ in range(50):
                mgr.status(job_id)
        except Exception as exc:  # ne doit jamais arriver
            errors.append(exc)

    threads = [threading.Thread(target=poller) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    release.set()
    _wait_terminal(mgr, job_id)
    assert not errors
