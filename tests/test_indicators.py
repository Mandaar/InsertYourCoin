"""Tests des indicateurs techniques sur des series connues."""
import numpy as np
import pandas as pd

from trading import indicators as ind


def test_sma_known_values():
    s = pd.Series([1, 2, 3, 4, 5], dtype="float64")
    out = ind.sma(s, 3)
    assert out.iloc[:2].isna().all()        # pas assez de points au debut
    assert out.iloc[2] == 2.0               # (1+2+3)/3
    assert out.iloc[3] == 3.0               # (2+3+4)/3
    assert out.iloc[4] == 4.0               # (3+4+5)/3


def test_ema_constant_series_is_constant():
    s = pd.Series([7.0] * 10)
    out = ind.ema(s, 4)
    assert np.allclose(out.values, 7.0)


def test_ema_reacts_and_no_nan():
    s = pd.Series(np.arange(1, 21, dtype="float64"))
    out = ind.ema(s, 5)
    assert not out.isna().any()
    assert out.iloc[-1] < s.iloc[-1]        # l'EMA retarde sur une tendance
    assert out.iloc[-1] > out.iloc[0]       # mais suit bien la hausse


def test_rsi_bounds_and_neutral_fill():
    # Serie trop courte pour la fenetre -> valeur neutre 50, jamais de NaN.
    short = pd.Series([1, 2, 3, 4, 5], dtype="float64")
    out = ind.rsi(short, 14)
    assert (out == 50).all()
    assert not out.isna().any()


def test_rsi_trend_direction():
    # Hausse bruitee -> RSI > 50 ; baisse bruitee -> RSI < 50 ; borne [0, 100].
    up = pd.Series([10, 11, 10.5, 12, 11.5, 13, 12.5, 14, 13.5, 15,
                    14.5, 16, 15.5, 17, 16.5, 18, 17.5, 19, 18.5, 20])
    down = up.iloc[::-1].reset_index(drop=True)
    ru, rd = ind.rsi(up, 14), ind.rsi(down, 14)
    assert ru.iloc[-1] > 50
    assert rd.iloc[-1] < 50
    for r in (ru, rd):
        assert (r >= 0).all() and (r <= 100).all()


def test_macd_constant_is_zero_and_hist_relation():
    s = pd.Series([100.0] * 40)
    macd_line, signal_line, hist = ind.macd(s)
    assert np.allclose(macd_line.values, 0.0)
    assert np.allclose(signal_line.values, 0.0)
    assert np.allclose(hist.values, 0.0)


def test_macd_uptrend_positive_and_hist_consistent():
    s = pd.Series(np.arange(1, 61, dtype="float64"))
    macd_line, signal_line, hist = ind.macd(s)
    assert macd_line.iloc[-1] > 0            # EMA rapide au-dessus de la lente
    assert np.allclose((macd_line - signal_line).values, hist.values)


def test_bollinger_constant_series_bands_collapse():
    s = pd.Series([50.0] * 30)
    upper, middle, lower = ind.bollinger(s, 20, 2.0)
    defined = middle.notna()
    assert np.allclose(upper[defined].values, middle[defined].values)
    assert np.allclose(lower[defined].values, middle[defined].values)


def test_bollinger_width_equals_four_std():
    s = pd.Series(np.linspace(10, 50, 40))
    upper, middle, lower = ind.bollinger(s, 20, 2.0)
    std = s.rolling(20, min_periods=20).std()
    width = (upper - lower).dropna()
    assert np.allclose(width.values, (4.0 * std).dropna().values)
    assert np.allclose(middle.dropna().values, ind.sma(s, 20).dropna().values)
