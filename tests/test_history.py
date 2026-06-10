"""
Tests de trading/history.py SANS reseau : client ccxt.binance FAKE injecte
(monkeypatch de _make_binance) + cache disque dans un tmp_path isole.

Couvre :
- pagination complete multi-appels (ex. 2500 bougies en 3 appels), merge, index
  strictement croissant ;
- dedup keep='last' (barre re-emise corrigee fait foi) ;
- mapping symboles (BTC/USD -> BTC/USDT, generique /USD -> /USDT) ;
- cache : 1er appel ecrit le CSV ; 2e appel ne demande QUE le delta depuis la
  derniere bougie du cache et fusionne ; cache corrompu -> retelechargement complet ;
- avertissement de couverture incomplete (B11) + avertissement honnetete USDT/USD.
"""
import pytest

import trading.history as history

DAY_MS = 24 * 3600 * 1000
NOW_MS = 1_700_000_000_000


class FakeBinanceClient:
    """Simule la pagination klines de ccxt.binance (max 1000 barres / appel)."""

    LIMIT = 1000

    def __init__(self, rows, now_ms=NOW_MS):
        self.rows = sorted(rows, key=lambda r: r[0])
        self.now_ms = now_ms
        self.rateLimit = 0          # pas d'attente dans les tests
        self.timeout = None
        self.verify = True
        self.calls = []             # liste des `since` recus (verif delta cache)

    def milliseconds(self):
        return self.now_ms

    def fetch_ohlcv(self, symbol, timeframe="1d", since=None, limit=1000):
        self.calls.append(since)
        batch = [r for r in self.rows if since is None or r[0] >= since]
        return batch[:limit]


def _bars(n, start_ms, step_ms=DAY_MS, price=100.0):
    return [[start_ms + i * step_ms, price, price * 1.01, price * 0.99, price, 1.0]
            for i in range(n)]


@pytest.fixture(autouse=True)
def _reset_warn_flag():
    # L'avertissement honnetete USDT/USD est "une fois par process" : on le reset
    # entre tests pour pouvoir l'observer de facon deterministe.
    history._usd_usdt_warned = False
    yield
    history._usd_usdt_warned = False


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Isole le cache disque dans un repertoire temporaire."""
    monkeypatch.setattr(history, "CACHE_DIR", str(tmp_path / "history"))
    return tmp_path / "history"


def _inject(monkeypatch, client):
    monkeypatch.setattr(history, "_make_binance", lambda: client)
    return client


# --------------------------------------------------------------------------- #
#  Pagination multi-appels + merge + index strictement croissant               #
# --------------------------------------------------------------------------- #
def test_pagination_multi_calls_merges_2500_bars(monkeypatch, cache_dir):
    """2500 bougies daily : >2 appels (limit=1000) -> merge complet, index strict."""
    n = 2500
    start = NOW_MS - n * DAY_MS
    client = _inject(monkeypatch, FakeBinanceClient(_bars(n, start)))
    df = history.fetch_long_ohlcv("BTC/USD", "1d")
    assert len(df) == n
    assert len(client.calls) >= 3                 # 1000 + 1000 + 500 = 3 appels
    assert df.index.is_monotonic_increasing and df.index.is_unique


def test_pagination_full_listing_without_since_days(monkeypatch, cache_dir):
    """since_days=None : on telecharge tout depuis le debut (since initial = 0)."""
    n = 1200
    start = NOW_MS - n * DAY_MS
    client = _inject(monkeypatch, FakeBinanceClient(_bars(n, start)))
    df = history.fetch_long_ohlcv("ETH/USD", "1d")
    assert len(df) == n
    assert client.calls[0] == 0                   # depart au debut du listing


# --------------------------------------------------------------------------- #
#  Dedup keep='last'                                                            #
# --------------------------------------------------------------------------- #
def test_dedup_keeps_last_emitted_bar(monkeypatch, cache_dir):
    """Un timestamp re-emis (barre corrigee) : la version la plus RECENTE fait foi."""
    n = 10
    start = NOW_MS - n * DAY_MS
    rows = _bars(n, start)
    dup_ts = rows[4][0]
    rows.append([dup_ts, 100.0, 101.0, 99.0, 555.0, 2.0])   # re-emission corrigee
    client = _inject(monkeypatch, FakeBinanceClient(rows))
    df = history.fetch_long_ohlcv("BTC/USD", "1d")
    assert len(df) == n                            # plus de doublon
    assert df.index.is_monotonic_increasing and df.index.is_unique
    assert df.iloc[4]["close"] == pytest.approx(555.0)


# --------------------------------------------------------------------------- #
#  Mapping symboles                                                            #
# --------------------------------------------------------------------------- #
def test_map_symbol_usd_to_usdt():
    assert history.map_symbol("BTC/USD") == "BTC/USDT"
    assert history.map_symbol("ETH/USD") == "ETH/USDT"
    assert history.map_symbol("SOL/USD") == "SOL/USDT"


def test_map_symbol_passthrough_non_usd():
    assert history.map_symbol("BTC/USDT") == "BTC/USDT"
    assert history.map_symbol("ETH/BTC") == "ETH/BTC"


def test_fetch_uses_mapped_symbol(monkeypatch, cache_dir):
    """Le symbole transmis a ccxt doit etre la paire USDT, pas USD."""
    seen = {}

    class RecordingClient(FakeBinanceClient):
        def fetch_ohlcv(self, symbol, timeframe="1d", since=None, limit=1000):
            seen["symbol"] = symbol
            return super().fetch_ohlcv(symbol, timeframe, since, limit)

    start = NOW_MS - 5 * DAY_MS
    _inject(monkeypatch, RecordingClient(_bars(5, start)))
    history.fetch_long_ohlcv("BTC/USD", "1d")
    assert seen["symbol"] == "BTC/USDT"


def test_honesty_warning_emitted_once(monkeypatch, cache_dir, capsys):
    start = NOW_MS - 5 * DAY_MS
    _inject(monkeypatch, FakeBinanceClient(_bars(5, start)))
    history.fetch_long_ohlcv("BTC/USD", "1d")
    out = capsys.readouterr().out
    assert "Binance (USDT)" in out and "Kraken (USD)" in out


# --------------------------------------------------------------------------- #
#  Cache : ecriture 1er appel, delta seul au 2e appel                          #
# --------------------------------------------------------------------------- #
def test_cache_written_then_delta_only(monkeypatch, cache_dir, capsys):
    n = 100
    start = NOW_MS - n * DAY_MS
    rows = _bars(n, start)

    # 1er appel : telechargement complet, ecrit le CSV.
    client1 = _inject(monkeypatch, FakeBinanceClient(rows))
    df1 = history.fetch_long_ohlcv("BTC/USD", "1d")
    assert len(df1) == n
    path = history._cache_path("binance", "BTC/USD", "1d")
    import os
    assert os.path.exists(path)
    out1 = capsys.readouterr().out
    assert "Telechargement complet" in out1

    # On ajoute 5 nouvelles bougies cote source ; 2e appel = DELTA seul.
    new_rows = _bars(5, start + n * DAY_MS)
    client2 = _inject(monkeypatch, FakeBinanceClient(rows + new_rows))
    df2 = history.fetch_long_ohlcv("BTC/USD", "1d")
    assert len(df2) == n + 5
    # Le client ne doit recevoir QUE des demandes depuis la derniere bougie du
    # cache (pas un since=0 / telechargement complet).
    last_cached_ms = int(df1.index[-1].value // 1_000_000)
    assert client2.calls and all(s is not None and s >= last_cached_ms
                                 for s in client2.calls)
    out2 = capsys.readouterr().out
    assert "Cache utilise" in out2
    assert df2.index.is_monotonic_increasing and df2.index.is_unique


def test_cache_refreshes_last_bar(monkeypatch, cache_dir):
    """La derniere bougie du cache (peut-etre en formation) est re-telechargee et
    dedupliquee keep='last' : une correction de cette barre est prise en compte."""
    n = 20
    start = NOW_MS - n * DAY_MS
    rows = _bars(n, start)
    _inject(monkeypatch, FakeBinanceClient(rows))
    df1 = history.fetch_long_ohlcv("BTC/USD", "1d")
    last_ts = rows[-1][0]

    # Source corrige la valeur de la derniere barre (close 100 -> 999).
    corrected = list(rows)
    corrected[-1] = [last_ts, 100.0, 101.0, 99.0, 999.0, 3.0]
    _inject(monkeypatch, FakeBinanceClient(corrected))
    df2 = history.fetch_long_ohlcv("BTC/USD", "1d")
    assert len(df2) == n                           # pas de doublon
    assert df2.iloc[-1]["close"] == pytest.approx(999.0)


def test_corrupted_cache_triggers_full_redownload(monkeypatch, cache_dir):
    """Un CSV de cache corrompu ne crashe pas : retelechargement complet propre."""
    import os
    os.makedirs(str(cache_dir), exist_ok=True)
    path = history._cache_path("binance", "BTC/USD", "1d")
    with open(path, "w", encoding="utf-8") as f:
        f.write("ceci n'est pas un csv ohlcv valide\n\x00\x00garbage")

    n = 30
    start = NOW_MS - n * DAY_MS
    client = _inject(monkeypatch, FakeBinanceClient(_bars(n, start)))
    df = history.fetch_long_ohlcv("BTC/USD", "1d")
    assert len(df) == n
    # Telechargement complet (since initial = 0 ou borne since_days), pas un delta
    # depuis une bougie de cache inexistante.
    assert client.calls and client.calls[0] is not None
    assert df.index.is_monotonic_increasing and df.index.is_unique


def test_read_cache_rejects_wrong_columns(monkeypatch, cache_dir):
    """_read_cache refuse un CSV aux mauvaises colonnes (retourne None)."""
    import os
    os.makedirs(str(cache_dir), exist_ok=True)
    path = history._cache_path("binance", "BTC/USD", "1d")
    with open(path, "w", encoding="utf-8") as f:
        f.write("date,foo,bar\n2022-01-01,1,2\n")
    assert history._read_cache(path) is None


# --------------------------------------------------------------------------- #
#  Couverture incomplete (B11)                                                 #
# --------------------------------------------------------------------------- #
def test_warns_when_history_shorter_than_requested(monkeypatch, cache_dir, capsys):
    """Actif plus jeune que la demande : couverture reelle 100 j sur 720 -> warn."""
    n = 100
    start = NOW_MS - n * DAY_MS
    _inject(monkeypatch, FakeBinanceClient(_bars(n, start)))
    df = history.fetch_long_ohlcv("SOL/USD", "1d", since_days=720)
    out = capsys.readouterr().out
    assert len(df) == n
    assert "AVERTISSEMENT" in out and "couverture reelle" in out
    assert "720" in out


def test_no_warning_when_coverage_complete(monkeypatch, cache_dir, capsys):
    n = 720
    start = NOW_MS - n * DAY_MS
    _inject(monkeypatch, FakeBinanceClient(_bars(n, start)))
    df = history.fetch_long_ohlcv("BTC/USD", "1d", since_days=720)
    out = capsys.readouterr().out
    assert len(df) == n
    assert "couverture reelle" not in out


def test_empty_source_warns(monkeypatch, cache_dir, capsys):
    _inject(monkeypatch, FakeBinanceClient([]))
    df = history.fetch_long_ohlcv("XXX/USD", "1d", since_days=30)
    out = capsys.readouterr().out
    assert len(df) == 0
    assert "Aucune donnee" in out


def test_since_days_window_trims_deeper_cache(monkeypatch, cache_dir):
    """Cache plus profond que la fenetre demandee : on ne renvoie que la fenetre,
    mais le cache complet reste sur disque."""
    n = 800
    start = NOW_MS - n * DAY_MS
    _inject(monkeypatch, FakeBinanceClient(_bars(n, start)))
    df = history.fetch_long_ohlcv("BTC/USD", "1d", since_days=200)
    # ~200 bougies renvoyees (tolerance sur la borne), pas 800.
    assert 190 <= len(df) <= 205
    # Le cache disque, lui, contient bien la profondeur complete.
    cached = history._read_cache(history._cache_path("binance", "BTC/USD", "1d"))
    assert cached is not None and len(cached) == n


# --------------------------------------------------------------------------- #
#  Robustesse reseau : erreur claire, pas de retry infini                      #
# --------------------------------------------------------------------------- #
def test_network_error_raises_clear_message(monkeypatch, cache_dir):
    class FailingClient(FakeBinanceClient):
        def fetch_ohlcv(self, symbol, timeframe="1d", since=None, limit=1000):
            raise ConnectionError("boom reseau")

    _inject(monkeypatch, FailingClient([]))
    with pytest.raises(RuntimeError) as exc:
        history.fetch_long_ohlcv("BTC/USD", "1d")
    assert "Binance" in str(exc.value)


# --------------------------------------------------------------------------- #
#  HistorySource (wrapper objet)                                               #
# --------------------------------------------------------------------------- #
def test_history_source_wrapper(monkeypatch, cache_dir):
    n = 50
    start = NOW_MS - n * DAY_MS
    _inject(monkeypatch, FakeBinanceClient(_bars(n, start)))
    df = history.HistorySource().fetch_long_ohlcv("BTC/USD", "1d")
    assert len(df) == n


# --------------------------------------------------------------------------- #
#  main._load_data routage source=binance + exclusion B4                       #
# --------------------------------------------------------------------------- #
def test_load_data_binance_route_excludes_forming_candle(monkeypatch, cache_dir):
    """source='binance' -> fetch_long_ohlcv, et la derniere bougie (formation)
    est exclue comme sur le chemin Kraken (B4)."""
    import main
    n = 60
    start = NOW_MS - n * DAY_MS
    _inject(monkeypatch, FakeBinanceClient(_bars(n, start)))
    out = main._load_data(None, "BTC/USD", "1d", None, source="binance")
    assert len(out) == n - 1                       # bougie en formation retiree
