"""
Indicateurs techniques classiques, calcules sur des series pandas.
Aucune dependance a une stratégie : ce sont des briques reutilisables.
"""
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Moyenne mobile simple."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Moyenne mobile exponentielle."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (lissage de Wilder).
    Valeur entre 0 et 100. <30 = survente, >70 = surachat (interpretation classique).
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)  # neutre quand indéfini (debut de serie)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    MACD. Retourne (ligne_macd, ligne_signal, histogramme).
    Croisement ligne_macd au-dessus de signal = signal haussier classique.
    """
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    """
    Bandes de Bollinger. Retourne (bande_haute, bande_centrale, bande_basse).
    """
    middle = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower
