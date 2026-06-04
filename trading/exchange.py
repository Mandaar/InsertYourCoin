"""
Connexion a Kraken via la bibliotheque ccxt.

- La recuperation de donnees publiques (prix, historique) ne necessite PAS de cles.
- Les soldes et le passage d'ordres necessitent des cles API (lues depuis .env).

Verification SSL activee par defaut (securite). Ne la desactive que si tu es
derriere un proxy d'entreprise qui intercepte le SSL.
"""
import time
import pandas as pd
import ccxt

import config


class KrakenExchange:
    def __init__(self, api_key: str = None, api_secret: str = None, verify_ssl: bool = None):
        self.client = ccxt.kraken({
            "apiKey": api_key if api_key is not None else config.KRAKEN_API_KEY,
            "secret": api_secret if api_secret is not None else config.KRAKEN_API_SECRET,
            "enableRateLimit": True,  # respecte les limites de l'API
        })
        verify = config.VERIFY_SSL if verify_ssl is None else verify_ssl
        self.client.verify = verify
        if not verify:
            import warnings, urllib3
            warnings.simplefilter("ignore")
            urllib3.disable_warnings()

    # ----------------------------------------------------------------- #
    #  Donnees de marche (publiques, sans cles)                          #
    # ----------------------------------------------------------------- #
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 720) -> pd.DataFrame:
        """
        Recupere les dernieres bougies OHLCV.
        Kraken renvoie au maximum ~720 bougies par appel.
        Retourne un DataFrame indexe par date (UTC).
        """
        raw = self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return self._to_dataframe(raw)

    def fetch_ohlcv_range(self, symbol: str, timeframe: str = "1d",
                          since_days: int = 720, max_calls: int = 20) -> pd.DataFrame:
        """
        Recupere un historique plus long en paginant via le parametre `since`.
        (Utile pour les timeframes courts ou Kraken limite chaque appel.)
        """
        since = self.client.milliseconds() - since_days * 24 * 60 * 60 * 1000
        all_rows, calls = [], 0
        while calls < max_calls:
            batch = self.client.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=720)
            if not batch:
                break
            all_rows += batch
            last_ts = batch[-1][0]
            if last_ts == since:  # plus de progression
                break
            since = last_ts + 1
            calls += 1
            time.sleep(self.client.rateLimit / 1000)
            if last_ts >= self.client.milliseconds() - 60_000:
                break
        df = self._to_dataframe(all_rows)
        return df[~df.index.duplicated(keep="first")]

    def fetch_price(self, symbol: str) -> float:
        """Dernier prix connu (ticker)."""
        return float(self.client.fetch_ticker(symbol)["last"])

    # ----------------------------------------------------------------- #
    #  Compte (necessite des cles API)                                   #
    # ----------------------------------------------------------------- #
    def fetch_balance(self) -> dict:
        """Soldes du compte. Necessite des cles API valides."""
        self._require_keys()
        bal = self.client.fetch_balance()
        return {k: v for k, v in bal.get("total", {}).items() if v and v > 0}

    def create_market_buy(self, symbol: str, amount: float):
        """Achat au marche de `amount` unites de l'actif de base (ex: ETH)."""
        self._require_keys()
        return self.client.create_order(symbol, "market", "buy", amount)

    def create_market_sell(self, symbol: str, amount: float):
        """Vente au marche de `amount` unites de l'actif de base."""
        self._require_keys()
        return self.client.create_order(symbol, "market", "sell", amount)

    # ----------------------------------------------------------------- #
    #  Helpers                                                           #
    # ----------------------------------------------------------------- #
    def _require_keys(self):
        if not self.client.apiKey or not self.client.secret:
            raise RuntimeError(
                "Cles API manquantes. Renseigne KRAKEN_API_KEY et KRAKEN_API_SECRET "
                "dans un fichier .env (voir .env.example)."
            )

    @staticmethod
    def _to_dataframe(raw) -> pd.DataFrame:
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.set_index("date").drop(columns=["ts"])
        return df.astype(float)
