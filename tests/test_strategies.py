"""Tests de forme des signaux de strategies : valeurs 0/1, pas de NaN, bon index."""
import numpy as np
import pytest

from trading.strategies import STRATEGIES, build_strategy


def _oscillating_prices(n=160):
    # Tendance + oscillation : croise les MM, fait osciller RSI/Bollinger.
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
