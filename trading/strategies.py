"""
Stratégies de trading classiques.

Chaque stratégie implemente `generate_signals(df)` et retourne une Serie de
positions DESIREES :
    1  -> on veut etre investi (long, 100% en ETH)
    0  -> on veut etre hors marche (100% en cash)

(On reste en "long/flat" car le spot Kraken ne permet pas de vendre a decouvert
sans marge. Pas de position -1.)

Le backtester se charge ensuite de decaler ces signaux d'une bougie pour eviter
le biais de "lookahead" (on ne peut pas trader sur une bougie pas encore cloturee).
"""
import pandas as pd
from . import indicators as ind


class Strategy:
    """Classe de base. Toute stratégie en herite."""
    name = "base"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def __str__(self):
        return self.name


def round_trip_cost(fee: float = None) -> float:
    """
    Cout d'un aller-retour en mouvement de prix : ce que le prix doit monter
    pour rembourser les frais des DEUX cotes (etude #6). fee=None -> config.FEE
    du moment : si les frais changent (palier Kraken, passage maker), tous les
    seuils ancres dessus SUIVENT -- c'est une MARGE, pas une constante figee.
      taker 0.80%/cote -> +1.62% ; maker 0.40%/cote -> +0.80%.
    """
    from config import FEE
    f = FEE if fee is None else fee
    return 1.0 / (1.0 - f) ** 2 - 1.0


class SMACrossover(Strategy):
    """
    Croisement de moyennes mobiles (la stratégie de suivi de tendance la plus connue).
    Long quand la MM courte passe au-dessus de la MM longue ("golden cross"),
    flat quand elle repasse en dessous ("death cross").

    `band` (etude #6, anti-churn) : MARGE exprimee en MULTIPLES du cout
    d'aller-retour (round_trip_cost), jamais en valeur absolue -- regle user
    2026-08-20 : "pas des delais dans le marbre mais des marges". band=2.0 avec
    frais taker -> le croisement ne compte que si l'ecart fast/slow depasse
    ~3.24%. A chaque bougie la decision passe un TEST explicite :
      - ACHAT   seulement si fast > slow * (1 + seuil)   (marge franchie)
      - VENTE   seulement si fast < slow * (1 - seuil)
      - entre les deux : on GARDE l'etat courant (hysteresis, pas de churn).
    band=0 (defaut) = comportement historique STRICTEMENT identique.
    Le dernier test evalue est expose dans `self.gate_info` (journal du paper).
    """
    def __init__(self, fast: int = 20, slow: int = 50, band: float = 0.0):
        self.fast, self.slow, self.band = fast, slow, float(band)
        self.name = (f"SMA({fast}/{slow})" if not self.band
                     else f"SMA({fast}/{slow}, marge {band:g}x frais)")
        self.gate_info = None

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast = ind.sma(df["close"], self.fast)
        slow = ind.sma(df["close"], self.slow)
        if not self.band:
            signal = (fast > slow).astype(int)
            return signal.where(slow.notna(), 0)
        seuil = self.band * round_trip_cost()
        haut = (fast > slow * (1.0 + seuil))   # test d'ACHAT franchi
        bas = (fast < slow * (1.0 - seuil))    # test de VENTE franchi
        etat, out = 0, []
        for h, b, ok in zip(haut.tolist(), bas.tolist(), slow.notna().tolist()):
            if not ok:
                etat = 0
            elif h:
                etat = 1
            elif b:
                etat = 0
            # ni h ni b : zone neutre -> on conserve l'etat (hysteresis)
            out.append(etat)
        # Journal de decision (paper) : le TEST de la DERNIERE bougie, chiffre.
        f_last, s_last = fast.iloc[-1], slow.iloc[-1]
        if pd.notna(s_last) and s_last:
            ecart = f_last / s_last - 1.0
            self.gate_info = {
                "ecart_pct": round(100.0 * ecart, 3),
                "seuil_pct": round(100.0 * seuil, 3),
                "verdict": ("ACHAT possible" if ecart > seuil else
                            "VENTE possible" if ecart < -seuil else
                            "zone neutre - marge non atteinte, on garde l etat"),
            }
        return pd.Series(out, index=df.index)


class TSMomentum(Strategy):
    """
    Time-series momentum (momentum de serie temporelle), long/flat.
    Long quand le prix actuel est au-dessus de son niveau d'il y a `lookback`
    bougies (rendement glissant positif), flat sinon. Tant que le decalage
    `shift(lookback)` est NaN (debut de serie, indicateurs pas amorces), on reste
    flat (0). C'est l'anomalie la plus documentee de la finance quant (Moskowitz-
    Ooi-Pedersen 2012). Signal lent -> tres peu d'ordres -> frais negligeables.
    """
    def __init__(self, lookback: int = 365):
        self.lookback = lookback
        self.name = f"TSMOM({lookback}j)"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        past = df["close"].shift(self.lookback)
        signal = (df["close"] > past).astype(int)
        return signal.where(past.notna(), 0)


class RSIStrategy(Strategy):
    """
    Retour a la moyenne via le RSI.
    Achat quand le RSI passe sous le seuil de survente, on conserve jusqu'a
    ce que le RSI depasse le seuil de surachat.
    """
    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        self.period, self.oversold, self.overbought = period, oversold, overbought
        self.name = f"RSI({period}, {oversold:.0f}/{overbought:.0f})"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi = ind.rsi(df["close"], self.period)
        raw = pd.Series(index=df.index, dtype="float64")
        raw[rsi < self.oversold] = 1.0    # signal d'entree
        raw[rsi > self.overbought] = 0.0  # signal de sortie
        return raw.ffill().fillna(0).astype(int)


class MACDStrategy(Strategy):
    """
    Suivi de tendance via le MACD.
    Long quand la ligne MACD est au-dessus de sa ligne de signal, flat sinon.
    """
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast, self.slow, self.signal = fast, slow, signal
        self.name = f"MACD({fast}/{slow}/{signal})"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        macd_line, signal_line, _ = ind.macd(df["close"], self.fast, self.slow, self.signal)
        return (macd_line > signal_line).astype(int)


class BollingerStrategy(Strategy):
    """
    Retour a la moyenne via les bandes de Bollinger.
    Achat quand le prix casse sous la bande basse, sortie quand il revient
    au-dessus de la bande centrale.
    """
    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period, self.num_std = period, num_std
        self.name = f"Bollinger({period}, {num_std:g}σ)"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        upper, middle, lower = ind.bollinger(df["close"], self.period, self.num_std)
        raw = pd.Series(index=df.index, dtype="float64")
        raw[df["close"] < lower] = 1.0
        raw[df["close"] > middle] = 0.0
        return raw.ffill().fillna(0).astype(int)


# Registre pour selectionner une stratégie par son nom court (CLI)
STRATEGIES = {
    "sma": SMACrossover,
    "tsmom": TSMomentum,
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "bollinger": BollingerStrategy,
}


def build_strategy(name: str, params: dict = None) -> Strategy:
    """
    Instancie une stratégie a partir de son nom court. `params` (optionnel) :
    dict k->v passe au constructeur (ex. {"fast": 50, "slow": 200, "band": 2})
    -- meme format que le --fixed du walk-forward, pour que le paper/live
    puissent tourner EXACTEMENT la config que le juge a evaluee.
    """
    name = name.lower()
    if name not in STRATEGIES:
        raise ValueError(f"Stratégie inconnue : {name}. Disponibles : {list(STRATEGIES)}")
    return STRATEGIES[name](**(params or {}))
