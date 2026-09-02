"""
Tests de la strategie PREDICTIVE (etude #8) -- sans reseau ni cles.

Le test central est celui du LOOKAHEAD : c'est l'erreur n.1 de ce domaine, elle
produit des resultats spectaculaires et faux. On le teste de DEUX facons
complementaires :

1. CAUSALITE (test le plus fort) : on modifie les donnees APRES la bougie k et on
   verifie que TOUS les signaux jusqu'a k sont inchanges. Toute fuite d'information
   future, meme indirecte (standardisation, etiquette, moyenne globale), casse ce test.
2. ORACLE : sur une serie alternee ou le futur est trivialement predictible EN
   HINDSIGHT, une strategie qui triche gagne enormement. On verifie d'abord que le
   test SAIT detecter la triche (une strategie volontairement fuyante est prise la
   main dans le sac), puis que la vraie strategie, elle, ne voit rien.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import make_ohlcv
from trading.backtester import Backtester
from trading.predictive import LogisticRegimeStrategy, build_features, FEATURE_NAMES
from trading.strategies import STRATEGIES, Strategy, build_strategy


def _prices(n=1200, seed=7):
    """Marche aleatoire deterministe (graine fixe), sans structure exploitable."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.02, n)
    return list(100.0 * np.exp(np.cumsum(rets)))


@pytest.fixture
def long_df():
    return make_ohlcv(_prices())


# --------------------------------------------------------------------------- #
#  Contrat Strategy / registre                                                #
# --------------------------------------------------------------------------- #
def test_registered_and_buildable():
    assert "predictive" in STRATEGIES
    strat = build_strategy("predictive")
    assert isinstance(strat, Strategy)
    assert strat.horizon == 5 and strat.min_train == 300 and strat.threshold == 0.5


def test_build_strategy_accepts_params():
    strat = build_strategy("predictive", {"horizon": 10})
    assert strat.horizon == 10
    assert "H=10" in strat.name


def test_signal_contract(long_df):
    sig = build_strategy("predictive").generate_signals(long_df)
    assert len(sig) == len(long_df)
    assert sig.index.equals(long_df.index)
    assert not sig.isna().any()
    assert set(sig.unique()).issubset({0, 1})


def test_signal_varies_on_a_long_series(long_df):
    """Sur 1200 bougies, le modele doit reellement decider (pas 0 partout ni 1 partout)."""
    sig = build_strategy("predictive").generate_signals(long_df)
    assert 0 < sig.sum() < len(sig)


# --------------------------------------------------------------------------- #
#  Donnees insuffisantes : hors marche, jamais de plantage                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("n", [1, 5, 50, 200, 304])
def test_flat_when_not_enough_data(n):
    df = make_ohlcv(_prices(n=max(n, 2))[:n] or [100.0])
    sig = LogisticRegimeStrategy().generate_signals(df)
    assert len(sig) == len(df)
    assert (sig == 0).all()      # moins de donnees que la fenetre d'apprentissage


def test_no_crash_on_constant_prices():
    """Prix strictement constants : ecart-type nul partout (division par zero evitee)."""
    df = make_ohlcv([100.0] * 900)
    sig = LogisticRegimeStrategy().generate_signals(df)
    assert not sig.isna().any()
    assert set(sig.unique()).issubset({0, 1})


# --------------------------------------------------------------------------- #
#  Determinisme                                                                #
# --------------------------------------------------------------------------- #
def test_deterministic_same_input_same_output(long_df):
    a = LogisticRegimeStrategy().generate_signals(long_df)
    b = LogisticRegimeStrategy().generate_signals(long_df)
    pd.testing.assert_series_equal(a, b)


def test_deterministic_weights(long_df):
    s1, s2 = LogisticRegimeStrategy(), LogisticRegimeStrategy()
    s1.generate_signals(long_df)
    s2.generate_signals(long_df)
    assert s1.last_weights.keys() == s2.last_weights.keys()
    for k in s1.last_weights:
        assert s1.last_weights[k] == pytest.approx(s2.last_weights[k], rel=0, abs=0)


# --------------------------------------------------------------------------- #
#  1. LOOKAHEAD -- causalite (le test le plus fort)                            #
# --------------------------------------------------------------------------- #
def test_features_use_only_the_past():
    closes = _prices(600)
    f_full = build_features(pd.Series(closes))
    f_cut = build_features(pd.Series(closes[:500]))
    for name in FEATURE_NAMES:
        a = f_full[name].iloc[:500].to_numpy()
        b = f_cut[name].to_numpy()
        assert np.allclose(a, b, equal_nan=True), f"{name} depend du futur"


def test_signals_unchanged_when_the_future_is_rewritten():
    """
    Meme passe, futurs radicalement differents -> les signaux jusqu'a k doivent
    etre IDENTIQUES. Toute fuite d'information posterieure a k casse ce test.
    """
    k = 800
    base = _prices(1100, seed=3)
    up = base[:k] + list(np.array(base[k:]) * np.linspace(1.0, 4.0, len(base) - k))
    down = base[:k] + list(np.array(base[k:]) * np.linspace(1.0, 0.25, len(base) - k))
    s_up = LogisticRegimeStrategy().generate_signals(make_ohlcv(up))
    s_down = LogisticRegimeStrategy().generate_signals(make_ohlcv(down))
    assert (s_up.iloc[:k].to_numpy() == s_down.iloc[:k].to_numpy()).all()


# --------------------------------------------------------------------------- #
#  2. LOOKAHEAD -- oracle : le test sait-il detecter une triche ?              #
# --------------------------------------------------------------------------- #
class _LeakyStrategy(Strategy):
    """Strategie VOLONTAIREMENT tricheuse : elle regarde la cloture suivante.

    Elle n'existe que pour prouver que le test ci-dessous est SENSIBLE : un controle
    qu'aucune triche ne fait echouer ne controle rien.
    """
    name = "TRICHE (voit close[t+1])"

    def generate_signals(self, df):
        return (df["close"].shift(-1) > df["close"]).astype(int)


def _coin_flip_series(n=1200, seed=11):
    """
    Signes de rendement TIRES AU SORT (graine fixe) : le futur est trivialement
    predictible pour qui le regarde, et RIEN dans le passe ne le predit -- ni
    momentum, ni volatilite, ni drawdown (aucune periodicite exploitable).

    Piege evite ici (mesure sur une premiere version de ce test) : une serie
    ALTERNEE +5/-5 % est, elle, parfaitement apprenable SANS tricher (la parite est
    encodee dans les caracteristiques) ; la strategie y gagnait x1800 en toute
    legalite. Un « ca gagne enormement » n'aurait donc rien prouve.
    """
    rng = np.random.default_rng(seed)
    signs = rng.choice([1.0, -1.0], size=n)
    closes, p = [], 100.0
    for s in signs:
        p *= (1.05 if s > 0 else 1.0 / 1.05)
        closes.append(p)
    return closes


def test_leak_detector_catches_a_cheating_strategy():
    """Le controle est SENSIBLE : la strategie qui voit close[t+1] fait fortune."""
    df = make_ohlcv(_coin_flip_series())
    res = Backtester(fee=0.0, slippage=0.0).run(df, _LeakyStrategy())
    assert res.metrics["total_return"] > 5.0     # +500 % : la triche est enorme et visible


def test_predictive_does_not_exploit_the_trivially_predictable_future():
    """La vraie strategie, elle, ne voit rien : le futur tire au sort reste ferme."""
    df = make_ohlcv(_coin_flip_series())
    res = Backtester(fee=0.0, slippage=0.0).run(df, LogisticRegimeStrategy())
    assert res.metrics["total_return"] < 1.0     # ordre de grandeur : le hasard, pas l'oracle


# --------------------------------------------------------------------------- #
#  Marge d'amorcage declaree (consommee par walk_forward / holdout_check)      #
# --------------------------------------------------------------------------- #
def test_declared_warmup_is_consistent():
    from trading.optimizer import _declared_warmup, WARMUP
    from trading.strategies import SMACrossover

    strat = LogisticRegimeStrategy(horizon=5, min_train=300)
    assert strat.warmup_bars == 200 + 300 + 5
    assert _declared_warmup(LogisticRegimeStrategy, {"horizon": 5}) == strat.warmup_bars
    # Neutralite : les strategies classiques ne declarent rien -> comportement inchange.
    assert _declared_warmup(SMACrossover, {"fast": 20, "slow": 50}) == 0
    assert WARMUP == 250
