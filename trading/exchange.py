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

import config  # importe en premier : declenche l'injection truststore (politique SSL) avant tout appel reseau


class KrakenExchange:
    def __init__(self, api_key: str = None, api_secret: str = None, verify_ssl: bool = None):
        self.client = ccxt.kraken({
            "apiKey": api_key if api_key is not None else config.KRAKEN_API_KEY,
            "secret": api_secret if api_secret is not None else config.KRAKEN_API_SECRET,
            "enableRateLimit": True,  # respecte les limites de l'API
        })
        verify = config.VERIFY_SSL if verify_ssl is None else verify_ssl
        self.client.verify = verify
        self.client.timeout = 30000  # 30s (defaut 10s trop court sur reseau lent)
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

    # Secondes par unite de timeframe (pagination dynamique, AUDIT B11).
    _TF_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}

    @classmethod
    def _timeframe_seconds(cls, timeframe: str) -> int:
        """Duree d'une bougie en secondes ('1m','15m','1h','4h','1d','1w')."""
        unit = timeframe[-1]
        if unit not in cls._TF_SECONDS or not timeframe[:-1].isdigit():
            raise ValueError(f"Timeframe inconnu : {timeframe}")
        return int(timeframe[:-1]) * cls._TF_SECONDS[unit]

    def fetch_ohlcv_range(self, symbol: str, timeframe: str = "1d",
                          since_days: int = 720, max_calls: int = None) -> pd.DataFrame:
        """
        Recupere un historique plus long en paginant via le parametre `since`.
        (Utile pour les timeframes courts ou Kraken limite chaque appel.)

        B11) `max_calls` est calcule DYNAMIQUEMENT depuis la couverture demandee
        (barres attendues / 720 par appel + marge) au lieu d'un plafond fixe (20)
        qui tronquait silencieusement l'historique intraday. Si la couverture
        reelle reste inferieure a la demande (historique plus court que demande,
        ou plafond explicite atteint), un AVERTISSEMENT est affiche -- signaler,
        pas masquer.
        B10) tri stable + deduplication keep='last' (un timestamp re-emis = barre
        corrigee, on garde la plus recente) + verification d'index strictement
        croissant.
        """
        tf_sec = self._timeframe_seconds(timeframe)
        if max_calls is None:
            expected_bars = since_days * 86400 / tf_sec
            max_calls = int(expected_bars // 720) + 3  # marge (arrondis, batchs partiels)
            # BONUS) plafond de securite : une demande extreme (ex. 1m sur des
            # annees) calculerait des milliers d'appels. On borne a 500 et on
            # AVERTIT explicitement quand cette borne tronque la couverture
            # (signaler, pas masquer ; cf. AVERTISSEMENT de couverture B11 plus bas).
            if max_calls > 500:
                print(f"AVERTISSEMENT : pagination plafonnee a 500 appels "
                      f"(au lieu de {max_calls}) pour {symbol} ({timeframe}) -- "
                      f"l'historique recupere sera plus court que les {since_days} jours demandes.")
                max_calls = 500
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
        # B10) tri STABLE (preserve l'ordre d'arrivee a timestamp egal) puis
        # dedup keep='last' : la re-emission la plus recente fait foi.
        df = df.sort_index(kind="stable")
        df = df[~df.index.duplicated(keep="last")]
        if len(df) and not (df.index.is_unique and df.index.is_monotonic_increasing):
            raise RuntimeError("fetch_ohlcv_range : index temporel non strictement "
                               "croissant apres tri/dedup (donnees corrompues).")
        # B11) couverture reelle vs demandee : avertir, jamais tronquer en silence.
        if not len(df):
            print(f"AVERTISSEMENT : aucune donnee recuperee pour {symbol} ({timeframe}).")
        else:
            covered_days = (df.index[-1] - df.index[0]).total_seconds() / 86400.0
            # tolerance : 2 bougies + 2% (bougie en cours, arrondis d'horloge)
            if covered_days + 2 * tf_sec / 86400.0 < since_days * 0.98:
                print(f"AVERTISSEMENT : couverture reelle {covered_days:.0f} jours "
                      f"sur {since_days} demandes ({symbol} {timeframe}) -- "
                      f"historique plus court que la demande ou pagination interrompue.")
        return df

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
