"""
Source d'historique LONGUE pour la RECHERCHE (backtest / walk-forward / optimize).

Probleme : l'API OHLC de Kraken ne sert que ~720 bougies par timeframe (~2 ans en
daily) -- insuffisant pour juger une strategie sur un cycle de marche complet.

Solution : Binance via ccxt (deja dans nos deps, AUCUNE cle requise) sert du daily
depuis 2017-08 (BTC/USDT, ETH/USDT) et 2020-08 (SOL/USDT), 1000 bougies/appel,
paginable. On l'utilise UNIQUEMENT pour la recherche.

HONNETETE (garde-fou n.1) : la recherche se fait sur Binance en USDT, l'execution
reelle sur Kraken en USD. Ecarts minimes en daily mais REELS (frais, slippage,
liquidite, prime stablecoin). On l'affiche une fois, on ne le masque pas. Le
paper/live restent 100% Kraken.

Conventions ALIGNEES sur trading/exchange.py :
- index date UTC, colonnes open/high/low/close/volume, valeurs float ;
- B10) tri stable + dedup keep='last' + verif index strictement croissant ;
- B11) avertissement si couverture reelle < demandee (signaler, pas masquer).
"""
import os

import pandas as pd
import ccxt

import config  # importe en premier : declenche l'injection truststore (politique SSL) avant tout appel reseau


# Repertoire de cache (CSV re-telechargeables ; ignore par git via data/).
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "history")

# 1000 = limite par appel de l'API klines de Binance.
_LIMIT = 1000

# Secondes par unite de timeframe (pagination dynamique, cf. exchange.py).
_TF_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}

# Avertissement d'honnetete USDT vs USD : affiche UNE SEULE FOIS par process.
_usd_usdt_warned = False


def _timeframe_seconds(timeframe: str) -> int:
    """Duree d'une bougie en secondes ('1m','15m','1h','4h','1d','1w')."""
    unit = timeframe[-1]
    if unit not in _TF_SECONDS or not timeframe[:-1].isdigit():
        raise ValueError(f"Timeframe inconnu : {timeframe}")
    return int(timeframe[:-1]) * _TF_SECONDS[unit]


def map_symbol(symbol: str) -> str:
    """
    Mappe une paire de recherche vers le marche Binance (USDT).

    La recherche se fait en USDT (Binance n'a pas de paires USD spot pour les
    majors). Generique : remplace /USD par /USDT. Une paire deja en USDT (ou tout
    autre quote) passe inchangee.

    BTC/USD -> BTC/USDT, ETH/USD -> ETH/USDT, SOL/USD -> SOL/USDT.
    """
    if symbol.endswith("/USD"):
        return symbol[:-len("/USD")] + "/USDT"
    return symbol


def _warn_usd_usdt_once():
    global _usd_usdt_warned
    if not _usd_usdt_warned:
        _usd_usdt_warned = True
        print("AVERTISSEMENT : source de recherche Binance (USDT) ; execution reelle "
              "sur Kraken (USD) -- ecarts minimes en daily mais reels.")


def _to_dataframe(raw) -> pd.DataFrame:
    """Identique a KrakenExchange._to_dataframe : OHLCV ccxt -> DataFrame UTC float."""
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("date").drop(columns=["ts"])
    return df.astype(float)


def _cache_path(exchange: str, symbol: str, timeframe: str) -> str:
    """Chemin du CSV de cache (symbole sanitize : / -> rien)."""
    safe = symbol.replace("/", "")
    return os.path.join(CACHE_DIR, f"{exchange}_{safe}_{timeframe}.csv")


def _read_cache(path: str):
    """
    Lit un CSV de cache -> DataFrame OHLCV (ou None si absent/illisible/corrompu).

    Un cache corrompu ne doit jamais bloquer : on retourne None et l'appelant
    retelecharge proprement depuis le debut.
    """
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty or list(df.columns) != ["open", "high", "low", "close", "volume"]:
            return None
        df.index = pd.to_datetime(df.index, utc=True)
        df = df.astype(float)
        if not (df.index.is_unique and df.index.is_monotonic_increasing):
            return None
        return df
    except Exception:  # noqa: BLE001 -- cache illisible = on retelecharge, on ne crashe pas
        return None


def _write_cache(path: str, df: pd.DataFrame):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path)


def _make_binance():
    """Client ccxt.binance (sans cles, rate-limit respecte, timeout 30s)."""
    client = ccxt.binance({"enableRateLimit": True})
    client.verify = config.VERIFY_SSL
    client.timeout = 30000
    return client


def _paginate(client, market_symbol: str, timeframe: str, since_ms: int) -> list:
    """
    Pagine fetch_ohlcv depuis `since_ms` jusqu'a aujourd'hui (limit=1000/appel).
    Retourne la liste brute des barres ccxt (non dedupliquee, non triee).
    Erreurs reseau -> exception claire (pas de retry infini).
    """
    import time

    tf_sec = _timeframe_seconds(timeframe)
    step_ms = tf_sec * 1000
    now_ms = client.milliseconds()
    rows = []
    since = since_ms
    while True:
        try:
            batch = client.fetch_ohlcv(market_symbol, timeframe=timeframe,
                                       since=since, limit=_LIMIT)
        except Exception as e:  # noqa: BLE001 -- on remonte une erreur claire
            raise RuntimeError(
                f"Echec de telechargement Binance pour {market_symbol} ({timeframe}) : {e}"
            ) from e
        if not batch:
            break
        rows += batch
        last_ts = batch[-1][0]
        if last_ts <= since - step_ms:  # plus de progression
            break
        since = last_ts + step_ms
        if since >= now_ms:
            break
        if len(batch) < _LIMIT:  # dernier batch partiel = on a rattrape le present
            break
        if client.rateLimit:
            time.sleep(client.rateLimit / 1000)
    return rows


def _finalize(rows, demanded_days, symbol, timeframe) -> pd.DataFrame:
    """
    Met en forme + applique le garde-fou B10 (memes regles qu'exchange.py).
    `demanded_days` est conserve pour parite de signature (la verif de couverture
    B11 est faite par _warn_coverage sur la profondeur complete, apres merge cache).
    """
    df = _to_dataframe(rows)
    # B10) tri STABLE puis dedup keep='last' : la re-emission la plus recente fait foi.
    df = df.sort_index(kind="stable")
    df = df[~df.index.duplicated(keep="last")]
    if len(df) and not (df.index.is_unique and df.index.is_monotonic_increasing):
        raise RuntimeError("fetch_long_ohlcv : index temporel non strictement "
                           "croissant apres tri/dedup (donnees corrompues).")
    return df


def _warn_coverage(full: pd.DataFrame, demanded_days: int, symbol, timeframe):
    """
    B11) couverture reelle vs demandee : avertir, jamais tronquer en silence.
    Compare la profondeur TOTALE disponible (cache complet) a la fenetre demandee.
    """
    if not len(full) or not demanded_days:
        return
    tf_sec = _timeframe_seconds(timeframe)
    covered_days = (full.index[-1] - full.index[0]).total_seconds() / 86400.0
    if covered_days + 2 * tf_sec / 86400.0 < demanded_days * 0.98:
        print(f"AVERTISSEMENT : couverture reelle {covered_days:.0f} jours "
              f"sur {demanded_days} demandes ({symbol} {timeframe}) -- "
              f"historique plus court que la demande (actif plus jeune que la periode).")


def fetch_long_ohlcv(symbol: str, timeframe: str = "1d",
                     since_days: int = None, exchange: str = "binance",
                     use_cache: bool = True) -> pd.DataFrame:
    """
    Recupere l'historique OHLCV LONG via Binance (pagination, AUCUNE cle requise).

    - `symbol` : paire de recherche (ex. "BTC/USD"). Mappee en USDT pour Binance.
    - `since_days` : profondeur demandee en jours ; None = tout l'historique depuis
      le debut du listing.
    - Cache disque `data/history/{exchange}_{symbol}_{timeframe}.csv` : si present,
      ne telecharge QUE le delta depuis la derniere bougie du cache (la derniere
      bougie est re-telechargee -- elle pouvait etre en formation -- et dedupliquee
      keep='last'). Pas de cache -> telechargement complet depuis le listing.

    Conventions exchange.py : index UTC, OHLCV float, B10 tri/dedup, B11 avertissement
    de couverture. Erreurs reseau -> exception claire.
    """
    _warn_usd_usdt_once()
    market_symbol = map_symbol(symbol)
    client = _make_binance()

    path = _cache_path(exchange, symbol, timeframe)
    cached = _read_cache(path) if use_cache else None

    # On telecharge et on CACHE TOUJOURS la profondeur maximale (depuis le debut du
    # listing, since=0) : `since_days` ne borne QUE la fenetre renvoyee, pas le
    # cache. Ainsi une recherche ulterieure plus longue reutilise le cache au lieu
    # de tout retelecharger.
    if cached is not None and len(cached):
        # Delta seulement : on repart de la DERNIERE bougie du cache (incluse, car
        # elle pouvait etre en formation au moment du cache) -> dedup keep='last'.
        last_ts = cached.index[-1]
        last_ms = int(last_ts.value // 1_000_000)  # ns -> ms
        new_rows = _paginate(client, market_symbol, timeframe, last_ms)
        # Reconstruit des barres brutes [ts, o, h, l, c, v] depuis le cache pour
        # fusionner uniformement avec les nouvelles, puis B10/B11 via _finalize.
        cache_rows = [[int(ts.value // 1_000_000),
                       row.open, row.high, row.low, row.close, row.volume]
                      for ts, row in cached.iterrows()]
        full = _finalize(cache_rows + new_rows, None, symbol, timeframe)
        added = len(full) - len(cached)
        print(f"Cache utilise ({path}) : {len(cached)} bougies en cache, "
              f"{max(added, 0)} ajoutees (delta depuis {last_ts.date()}).")
    else:
        rows = _paginate(client, market_symbol, timeframe, 0)
        full = _finalize(rows, None, symbol, timeframe)
        if not len(full):
            print(f"Aucune donnee telechargee pour {symbol} ({timeframe}).")
        else:
            print(f"Telechargement complet ({market_symbol}, {timeframe}) : "
                  f"{len(full)} bougies depuis {full.index[0].date()}.")

    if use_cache and len(full):
        _write_cache(path, full)

    # Fenetre demandee : on ne renvoie que les `since_days` derniers jours (le cache
    # complet reste sur disque). B11 : avertir si la profondeur reelle est inferieure.
    if since_days is not None and len(full):
        start_ms = client.milliseconds() - since_days * 86400 * 1000
        df = full[full.index >= pd.Timestamp(start_ms, unit="ms", tz="UTC")]
        _warn_coverage(full, since_days, symbol, timeframe)
    else:
        df = full
    return df


class HistorySource:
    """Wrapper objet (parite avec KrakenExchange) -- delegue a fetch_long_ohlcv."""

    def __init__(self, exchange: str = "binance"):
        self.exchange = exchange

    def fetch_long_ohlcv(self, symbol: str, timeframe: str = "1d",
                         since_days: int = None, use_cache: bool = True) -> pd.DataFrame:
        return fetch_long_ohlcv(symbol, timeframe, since_days=since_days,
                                exchange=self.exchange, use_cache=use_cache)
