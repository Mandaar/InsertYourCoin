"""Tests de forme des signaux de strategies : valeurs 0/1, pas de NaN, bon index."""
import numpy as np
import pytest

from trading.strategies import STRATEGIES, TSMomentum, build_strategy


def _oscillating_prices(n=520):
    # Tendance + oscillation : croise les MM, fait osciller RSI/Bollinger, et
    # depasse 520 bougies pour que TSMOM (lookback 365 par defaut) ait des deux
    # cotes du seuil close > close.shift(365) -> au moins une entree ET une sortie.
    t = np.arange(n)
    return 100 + 0.3 * t + 12 * np.sin(t / 7.0)


@pytest.fixture
def df(make_df):
    return make_df(_oscillating_prices())


@pytest.mark.parametrize("key", list(STRATEGIES))
def test_signal_shape(df, key):
    sig = build_strategy(key).generate_signals(df)
    assert len(sig) == len(df)
    assert sig.index.equals(df.index)
    assert not sig.isna().any()
    assert set(sig.unique()).issubset({0, 1})


@pytest.mark.parametrize("key", list(STRATEGIES))
def test_signal_has_some_variation(df, key):
    # Sur une serie qui oscille, chaque strategie doit produire des entrees ET des sorties.
    sig = build_strategy(key).generate_signals(df)
    assert sig.sum() > 0          # au moins une periode investie
    assert sig.sum() < len(sig)   # et au moins une periode hors marche


def test_build_strategy_unknown_raises():
    with pytest.raises(ValueError):
        build_strategy("inexistante")


# --------------------------------------------------------------------------- #
#  TSMOM : long si close > close il y a `lookback` bougies, flat sinon         #
# --------------------------------------------------------------------------- #
def test_tsmom_long_on_rising_series(make_df):
    """Serie strictement croissante : 1 partout APRES le lookback, 0 pendant."""
    lookback = 30
    df = make_df(list(100.0 + np.arange(120)))   # croissante
    sig = TSMomentum(lookback=lookback).generate_signals(df)
    # Warm-up : les `lookback` premieres bougies sont flat (shift NaN -> 0).
    assert (sig.iloc[:lookback] == 0).all()
    # Apres le warm-up, close > close.shift(lookback) toujours vrai -> long.
    assert (sig.iloc[lookback:] == 1).all()


def test_tsmom_flat_on_falling_series(make_df):
    """Serie strictement decroissante : flat (0) partout, jamais long."""
    lookback = 30
    df = make_df(list(300.0 - np.arange(120)))   # decroissante (>0)
    sig = TSMomentum(lookback=lookback).generate_signals(df)
    assert (sig == 0).all()


def test_tsmom_warmup_is_flat_and_clean(make_df):
    """Tant que shift(lookback) est NaN (debut de serie), le signal est 0 (pas NaN)."""
    lookback = 50
    df = make_df(_oscillating_prices())
    sig = TSMomentum(lookback=lookback).generate_signals(df)
    assert not sig.isna().any()
    assert set(sig.unique()).issubset({0, 1})
    assert (sig.iloc[:lookback] == 0).all()
