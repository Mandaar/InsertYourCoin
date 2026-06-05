"""
Tests de la commande `check` (healthcheck).

Aucun reseau, aucune cle API : on injecte un faux exchange dont fetch_price
retourne un prix ou leve une exception, et on appelle directement les briques
pures `diagnose_error` et `run_check`.
"""
import main


class FakePriceExchange:
    """Exchange factice minimal : fetch_price retourne un prix fixe."""
    def __init__(self, price):
        self._price = price

    def fetch_price(self, symbol):
        return self._price


class FakeFailingExchange:
    """Exchange factice : fetch_price leve toujours l'exception fournie."""
    def __init__(self, exc):
        self._exc = exc

    def fetch_price(self, symbol):
        raise self._exc


# --------------------------------------------------------------------------- #
#  diagnose_error : fonction pure de classification                            #
# --------------------------------------------------------------------------- #
def test_diagnose_error_ssl_category():
    cat, msg = main.diagnose_error(
        Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed (_ssl.c:1006)"))
    assert cat == "ssl"
    low = msg.lower()
    assert "antivirus" in low
    assert "setup" in low
    assert "verify_ssl" in low  # rappel de ne pas la desactiver


def test_diagnose_error_ssl_case_insensitive():
    cat, _ = main.diagnose_error(Exception("ssl error: certificate verify failed"))
    assert cat == "ssl"


def test_diagnose_error_network_category():
    cat, msg = main.diagnose_error(Exception("Connection timed out"))
    assert cat == "network"
    assert "Connection timed out" in msg


# --------------------------------------------------------------------------- #
#  run_check : avec exchange injecte (aucun reseau)                            #
# --------------------------------------------------------------------------- #
def test_run_check_ok_when_price_returned():
    ok, lines = main.run_check(FakePriceExchange(1234.5), "ETH/USD")
    assert ok is True
    blob = "\n".join(lines)
    assert "1234.5" in blob
    assert "OK" in blob
    assert "ETH/USD" in blob


def test_run_check_fails_on_ssl_error():
    exc = Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    ok, lines = main.run_check(FakeFailingExchange(exc), "ETH/USD")
    assert ok is False
    low = "\n".join(lines).lower()
    assert "ssl" in low
    assert "antivirus" in low
    assert "setup" in low


def test_run_check_fails_on_network_error():
    ok, lines = main.run_check(FakeFailingExchange(Exception("Connection timed out")), "ETH/USD")
    assert ok is False
    blob = "\n".join(lines)
    assert "network" in blob
    assert "Connection timed out" in blob


def test_run_check_reports_versions():
    ok, lines = main.run_check(FakePriceExchange(100.0), "BTC/USD")
    blob = "\n".join(lines)
    assert "Python" in blob
    assert "ccxt" in blob
    assert "truststore" in blob
