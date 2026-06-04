"""
Configuration pytest : rend `config` et le paquet `trading` importables depuis
la racine du depot, et expose des fabriques de donnees OHLCV synthetiques.

Aucun test ne touche au reseau ni a des cles API.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def make_ohlcv(closes, freq="1D", start="2022-01-01",
               highs=None, lows=None, opens=None):
    """
    Construit un DataFrame OHLCV indexe par date (UTC) a partir d'une liste de
    cloture. Par defaut : open = cloture precedente, high/low = +/-1% autour de
    la cloture. Chaque colonne OHLC peut etre fournie explicitement (tests de
    stop/trailing/take-profit ou le profil intra-bougie compte).
    """
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz="UTC")
    close = pd.Series([float(c) for c in closes], index=idx)
    if opens is None:
        opens = close.shift(1).fillna(close.iloc[0])
    else:
        opens = pd.Series([float(o) for o in opens], index=idx)
    if highs is None:
        highs = pd.concat([close, opens], axis=1).max(axis=1) * 1.01
    else:
        highs = pd.Series([float(h) for h in highs], index=idx)
    if lows is None:
        lows = pd.concat([close, opens], axis=1).min(axis=1) * 0.99
    else:
        lows = pd.Series([float(l) for l in lows], index=idx)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": close, "volume": 1.0}, index=idx)


@pytest.fixture
def make_df():
    """Fabrique de DataFrame OHLCV synthetique (voir make_ohlcv)."""
    return make_ohlcv
