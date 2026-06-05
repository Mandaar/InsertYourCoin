"""
Tests de la resilience reseau du paper/live : classification des erreurs,
backoff exponentiel plafonne, et trace fichier.

Aucun reseau, aucune cle API : faux exchange minimal, pas d'appel a run().
"""
import ccxt

from trading.paper_trader import describe_error, backoff_seconds, PaperTrader
from trading.strategies import build_strategy


class FakeExchange:
    """Exchange factice minimal : aucun appel reseau."""
    def fetch_ohlcv(self, symbol, timeframe, limit=200):
        return None

    def fetch_price(self, symbol):
        return 100.0

    def fetch_balance(self):
        return {}


# --------------------------------------------------------------------------- #
#  describe_error : classification                                             #
# --------------------------------------------------------------------------- #
def test_describe_error_ddos_is_kraken_refus():
    assert describe_error(ccxt.DDoSProtection("rate limit"))["category"] == "kraken_refus"


def test_describe_error_timeout():
    assert describe_error(ccxt.RequestTimeout("kraken GET ..."))["category"] == "timeout"


def test_describe_error_not_available():
    assert describe_error(ccxt.ExchangeNotAvailable("maintenance"))["category"] == "indisponible"


def test_describe_error_network():
    assert describe_error(ccxt.NetworkError("conn reset"))["category"] == "reseau"


def test_describe_error_other():
    assert describe_error(ValueError("x"))["category"] == "autre"


def test_describe_error_rate_limit_text_is_kraken_refus():
    # Meme une exception generique : si le message parle de rate limit -> refus.
    assert describe_error(Exception("... Rate Limit Exceeded ..."))["category"] == "kraken_refus"


def test_describe_error_detail_includes_type_and_truncates():
    info = describe_error(ValueError("z" * 500))
    assert info["detail"].startswith("ValueError: ")
    assert len(info["detail"]) <= len("ValueError: ") + 300


# --------------------------------------------------------------------------- #
#  backoff_seconds : croissance, plafond, refus plus long                      #
# --------------------------------------------------------------------------- #
def test_backoff_grows_with_failures():
    a = backoff_seconds(1, "reseau", 3600)
    b = backoff_seconds(2, "reseau", 3600)
    c = backoff_seconds(3, "reseau", 3600)
    assert a < b < c


def test_backoff_caps_default_at_600():
    assert backoff_seconds(99, "reseau", 3600) == 600


def test_backoff_caps_refus_at_900():
    assert backoff_seconds(99, "kraken_refus", 3600) == 900


def test_backoff_refus_at_least_other_for_same_n():
    for n in range(1, 8):
        assert backoff_seconds(n, "kraken_refus", 3600) >= backoff_seconds(n, "reseau", 3600)


# --------------------------------------------------------------------------- #
#  _trace : ecriture fichier                                                   #
# --------------------------------------------------------------------------- #
def test_trace_writes_to_log_file(tmp_path):
    log = tmp_path / "p.log"
    pt = PaperTrader(FakeExchange(), build_strategy("sma"),
                     state_file=str(tmp_path / "state.json"),
                     stats_file=str(tmp_path / "stats.csv"),
                     log_file=str(log))
    pt._trace("hello")
    assert "hello" in log.read_text(encoding="utf-8")
