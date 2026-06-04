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


class SMACrossover(Strategy):
    """
    Croisement de moyennes mobiles (la stratégie de suivi de tendance la plus connue).
    Long quand la MM courte passe au-dessus de la MM longue ("golden cross"),
    flat quand elle repasse en dessous ("death cross").
    """
    def __init__(self, fast: int = 20, slow: int = 50):
        self.fast, self.slow = fast, slow
        self.name = f"SMA({fast}/{slow})"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast = ind.sma(df["close"], self.fast)
        slow = ind.sma(df["close"], self.slow)
        signal = (fast > slow).astype(int)
        return signal.where(slow.notna(), 0)


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
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "bollinger": BollingerStrategy,
}


def build_strategy(name: str) -> Strategy:
    """Instancie une stratégie a partir de son nom court avec ses parametres par defaut."""
    name = name.lower()
    if name not in STRATEGIES:
        raise ValueError(f"Stratégie inconnue : {name}. Disponibles : {list(STRATEGIES)}")
    return STRATEGIES[name]()
