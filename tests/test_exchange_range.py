"""
Tests de fetch_ohlcv_range SANS reseau : client ccxt FAKE injecte.

Couvre (AUDIT B10/B11) :
- pagination complete au-dela de l'ancien plafond fixe de 20 appels
  (max_calls dynamique calcule depuis since_days + timeframe) ;
- tri + deduplication keep='last' (timestamp re-emis -> barre corrigee gardee) ;
- avertissement explicite quand la couverture reelle < couverture demandee
  (signaler, pas masquer), et silence quand la couverture est complete ;
- B4 cote main : _load_data / _load_basket excluent la bougie EN FORMATION.
"""
import pytest

from trading.exchange import KrakenExchange

HOUR_MS = 3600 * 1000
DAY_MS = 24 * HOUR_MS
NOW_MS = 1_700_000_000_000


class FakeKrakenClient:
    """Simule la pagination OHLCV de ccxt.kraken (max 720 barres par appel)."""

    def __init__(self, rows, now_ms=NOW_MS):
        self.rows = sorted(rows, key=lambda r: r[0])
        self.now_ms = now_ms
        self.rateLimit = 0          # pas d'attente dans les tests
        self.calls = 0

    def milliseconds(self):
        return self.now_ms

    def fetch_ohlcv(self, symbol, timeframe="1d", since=None, limit=720):
        self.calls += 1
        batch = [r for r in self.rows if since is None or r[0] >= since]
        return batch[:limit]


def _bars(n, start_ms, step_ms, price=100.0):
    return [[start_ms + i * step_ms, price, price * 1.01, price * 0.99, price, 1.0]
            for i in range(n)]


def _make_exchange(client):
    # Instanciation SANS __init__ : pas de reseau, pas de cles, pas de config.
    ex = KrakenExchange.__new__(KrakenExchange)
    ex.client = client
    return ex


# --------------------------------------------------------------------------- #
#  B11 : max_calls dynamique -> pagination complete                            #
# --------------------------------------------------------------------------- #
def test_pagination_complete_beyond_old_fixed_cap():
    """720 jours en 1h = 17280 barres = 24 appels : l'ancien plafond fixe (20)
    tronquait silencieusement ; le calcul dynamique recupere TOUT."""
    n_days = 720
    n_bars = n_days * 24
    start = NOW_MS - n_days * DAY_MS
    client = FakeKrakenClient(_bars(n_bars, start, HOUR_MS))
    df = _make_exchange(client).fetch_ohlcv_range("BTC/USD", "1h", since_days=n_days)
    assert len(df) == n_bars                  # rien de tronque
    assert client.calls >= 24                 # > ancien plafond fixe de 20
    assert df.index.is_monotonic_increasing and df.index.is_unique


def test_dynamic_max_calls_capped_at_500_with_warning(capsys):
    """BONUS : une demande extreme (1m sur ~1 an = ~525600 barres -> ~733 appels)
    voit son max_calls dynamique borne a 500 avec un avertissement explicite."""
    MIN_MS = 60 * 1000
    n_days = 365
    start = NOW_MS - n_days * DAY_MS
    # Beaucoup de barres 1m mais on coupe vite via max progression : peu importe,
    # le point teste est le PLAFOND + l'avertissement, calcules AVANT la boucle.
    client = FakeKrakenClient(_bars(720, start, MIN_MS))   # le client s'epuise vite
    _make_exchange(client).fetch_ohlcv_range("BTC/USD", "1m", since_days=n_days)
    out = capsys.readouterr().out
    assert "plafonnee a 500" in out
    # Le client n'a de toute facon pas 500 batchs pleins : on verifie juste le
    # plafond annonce, pas que 500 appels ont eu lieu.


def test_explicit_max_calls_still_honoured_and_warns(capsys):
    """Un plafond explicite reste possible, mais la troncature est SIGNALEE."""
    n_days = 720
    start = NOW_MS - n_days * DAY_MS
    client = FakeKrakenClient(_bars(n_days * 24, start, HOUR_MS))
    df = _make_exchange(client).fetch_ohlcv_range("BTC/USD", "1h",
                                                  since_days=n_days, max_calls=2)
    out = capsys.readouterr().out
    assert len(df) == 2 * 720                 # 2 appels x 720 barres
    assert "AVERTISSEMENT" in out and "couverture reelle" in out


# --------------------------------------------------------------------------- #
#  B10 : tri + dedup keep='last' + index strictement croissant                 #
# --------------------------------------------------------------------------- #
def test_dedup_keeps_last_emitted_bar():
    """Un timestamp re-emis (barre corrigee) : la version la plus RECENTE du
    flux fait foi (keep='last'), pas la premiere (ancien comportement)."""
    start = NOW_MS - 10 * DAY_MS
    rows = _bars(10, start, DAY_MS)
    dup_ts = rows[4][0]
    rows.append([dup_ts, 100.0, 101.0, 99.0, 555.0, 2.0])   # re-emission corrigee
    client = FakeKrakenClient(rows)
    df = _make_exchange(client).fetch_ohlcv_range("BTC/USD", "1d", since_days=10)
    assert len(df) == 10                      # plus de doublon
    assert df.index.is_monotonic_increasing and df.index.is_unique
    dup_idx = df.index[4]
    assert df.loc[dup_idx, "close"] == pytest.approx(555.0)


def test_unsorted_batches_are_sorted():
    """Des batchs arrives dans le desordre ressortent tries strictement."""
    start = NOW_MS - 6 * DAY_MS
    rows = _bars(6, start, DAY_MS)
    shuffled = [rows[3], rows[0], rows[5], rows[1], rows[4], rows[2]]

    class UnsortedClient(FakeKrakenClient):
        def __init__(self, rows, now_ms=NOW_MS):
            super().__init__(rows, now_ms)
            self.rows = rows                  # PAS de tri : flux desordonne

    client = UnsortedClient(shuffled)
    df = _make_exchange(client).fetch_ohlcv_range("BTC/USD", "1d", since_days=6,
                                                  max_calls=1)
    assert df.index.is_monotonic_increasing and df.index.is_unique
    assert len(df) == 6


# --------------------------------------------------------------------------- #
#  B11 : couverture reelle vs demandee                                         #
# --------------------------------------------------------------------------- #
def test_warns_when_history_shorter_than_requested(capsys):
    """Actif plus jeune que la demande : couverture reelle 100 j sur 720 -> warn."""
    start = NOW_MS - 100 * DAY_MS
    client = FakeKrakenClient(_bars(100, start, DAY_MS))
    df = _make_exchange(client).fetch_ohlcv_range("SOL/USD", "1d", since_days=720)
    out = capsys.readouterr().out
    assert len(df) == 100
    assert "AVERTISSEMENT" in out and "couverture reelle" in out
    assert "720" in out                        # jours demandes mentionnes


def test_no_warning_when_coverage_complete(capsys):
    start = NOW_MS - 720 * DAY_MS
    client = FakeKrakenClient(_bars(720, start, DAY_MS))
    df = _make_exchange(client).fetch_ohlcv_range("BTC/USD", "1d", since_days=720)
    out = capsys.readouterr().out
    assert len(df) == 720
    assert "AVERTISSEMENT" not in out


def test_warns_when_no_data(capsys):
    client = FakeKrakenClient([])
    df = _make_exchange(client).fetch_ohlcv_range("XXX/USD", "1d", since_days=30)
    out = capsys.readouterr().out
    assert len(df) == 0
    assert "AVERTISSEMENT" in out


def test_timeframe_seconds():
    assert KrakenExchange._timeframe_seconds("1m") == 60
    assert KrakenExchange._timeframe_seconds("15m") == 900
    assert KrakenExchange._timeframe_seconds("1h") == 3600
    assert KrakenExchange._timeframe_seconds("4h") == 14400
    assert KrakenExchange._timeframe_seconds("1d") == 86400
    assert KrakenExchange._timeframe_seconds("1w") == 604800
    with pytest.raises(ValueError):
        KrakenExchange._timeframe_seconds("2x")


# --------------------------------------------------------------------------- #
#  B4 : bougie EN FORMATION exclue par _load_data / _load_basket (main.py)     #
# --------------------------------------------------------------------------- #
class _FakeEx:
    """Exchange factice : renvoie le df fourni, sans reseau."""

    def __init__(self, df):
        self.df = df

    def fetch_ohlcv(self, symbol, timeframe, limit=720):
        return self.df

    def fetch_ohlcv_range(self, symbol, timeframe, since_days=720):
        return self.df


def test_load_data_excludes_forming_candle(make_df):
    import main
    df = make_df([100.0 + i for i in range(10)])
    out = main._load_data(_FakeEx(df), "BTC/USD", "1d", 10)
    assert len(out) == 9                      # derniere bougie (en formation) retiree
    assert out.index[-1] == df.index[-2]


def test_load_data_excludes_forming_candle_on_range_path(make_df):
    import main
    df = make_df([100.0 + i for i in range(1000)])
    out = main._load_data(_FakeEx(df), "BTC/USD", "1d", 1000)   # > 720 -> range
    assert len(out) == 999
    assert out.index[-1] == df.index[-2]


def test_load_basket_inherits_forming_candle_exclusion(make_df):
    import main
    df = make_df([100.0 + i for i in range(10)])
    data = main._load_basket(_FakeEx(df), ["BTC/USD", "ETH/USD"], "1d", 10)
    assert set(data) == {"BTC/USD", "ETH/USD"}
    for d in data.values():
        assert len(d) == 9
        assert d.index[-1] == df.index[-2]


# --------------------------------------------------------------------------- #
#  FIX 2 : routage par BARRES ATTENDUES (pas par jours) -> pas de troncature   #
#  silencieuse en intraday quand days <= 720 mais bougies attendues > 720.     #
# --------------------------------------------------------------------------- #
class _RouteRecordingEx:
    """Exchange factice qui enregistre QUELLE methode de fetch a ete appelee."""

    def __init__(self, df):
        self.df = df
        self.route = None

    def fetch_ohlcv(self, symbol, timeframe, limit=720):
        self.route = "simple"
        return self.df

    def fetch_ohlcv_range(self, symbol, timeframe, since_days=720):
        self.route = "range"
        return self.df


def test_load_data_intraday_700d_uses_range_path(make_df):
    """--timeframe 1h --days 700 = 16800 barres attendues (> 720) : on PAGINE,
    sinon fetch_ohlcv(limit=720) ne rendrait que ~30 jours (troncature B11)."""
    import main
    df = make_df([100.0 + i for i in range(50)])
    ex = _RouteRecordingEx(df)
    main._load_data(ex, "BTC/USD", "1h", 700)
    assert ex.route == "range"                 # 700j * 24 = 16800 barres > 720


def test_load_data_daily_300d_stays_on_simple_fetch(make_df):
    """--timeframe 1d --days 300 = 300 barres attendues (<= 720) : fetch simple."""
    import main
    df = make_df([100.0 + i for i in range(50)])
    ex = _RouteRecordingEx(df)
    main._load_data(ex, "BTC/USD", "1d", 300)
    assert ex.route == "simple"


def test_load_data_daily_1000d_uses_range_path(make_df):
    """--timeframe 1d --days 1000 = 1000 barres (> 720) : pagination (inchange)."""
    import main
    df = make_df([100.0 + i for i in range(50)])
    ex = _RouteRecordingEx(df)
    main._load_data(ex, "BTC/USD", "1d", 1000)
    assert ex.route == "range"
