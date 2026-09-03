"""
Tests du detecteur de REGIME par VOTE (etude #11, etage 1) -- sans reseau ni cles.

Trois choses doivent etre prouvees ici, pas supposees :

1. CAUSALITE : reecrire les donnees APRES la bougie k ne change AUCUN signal <= k.
   C'est le critere R0 gele (docs/ETUDE_11_REGIME.md §0.4) : s'il tombe, tous les
   chiffres de l'etude sont nuls et non avenus.
2. LE VOTE EST BIEN UN VOTE : sur des series fabriquees ou le compte de voix est
   connu a l'avance, la majorite decide -- et rien d'autre.
3. NON-REGRESSION : ajouter cette strategie au registre ne change strictement rien
   au comportement des strategies existantes (les etudes #4/#5/#7/#8 restent valides).
"""
import inspect

import numpy as np
import pandas as pd
import pytest

from conftest import make_ohlcv
from trading.optimizer import (DEFAULT_GRIDS, _declared_warmup, _params_warmup,
                               walk_forward)
from trading.regime import (DEFAULT_LOOKBACKS, RISK_OFF, RISK_ON, WARMUP_EXTRA,
                            RegimeVoteStrategy, ensure_optimizer_grid)
from trading.strategies import (STRATEGIES, BollingerStrategy, MACDStrategy,
                                RSIStrategy, SMACrossover, Strategy, TSMomentum,
                                build_strategy)


def _prices(n=1200, seed=11):
    """Marche aleatoire deterministe (graine fixe), sans structure exploitable."""
    rng = np.random.default_rng(seed)
    return list(100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n))))


@pytest.fixture
def long_df():
    return make_ohlcv(_prices())


# --------------------------------------------------------------------------- #
#  Contrat Strategy / registre                                                #
# --------------------------------------------------------------------------- #
def test_registered_and_buildable():
    assert "regime" in STRATEGIES
    strat = build_strategy("regime")
    assert isinstance(strat, Strategy)
    assert isinstance(strat, RegimeVoteStrategy)
    assert strat.lookbacks == DEFAULT_LOOKBACKS == (180, 270, 365, 450, 540)
    assert strat.min_votes == 3


def test_signal_contract(long_df):
    sig = build_strategy("regime").generate_signals(long_df)
    assert len(sig) == len(long_df)
    assert sig.index.equals(long_df.index)
    assert not sig.isna().any()
    assert set(sig.unique()).issubset({0, 1})


def test_build_strategy_accepts_lookbacks():
    strat = build_strategy("regime", {"lookbacks": (10, 20, 30)})
    assert strat.lookbacks == (10, 20, 30)
    assert strat.min_votes == 2
    assert "10/20/30" in strat.name


def test_lookbacks_from_string_and_int():
    # Le CLI passe des chaines (--params "lookbacks=10,20,30").
    assert build_strategy("regime", {"lookbacks": "10,20,30"}).lookbacks == (10, 20, 30)
    assert build_strategy("regime", {"lookbacks": 7}).lookbacks == (7,)


def test_invalid_lookbacks_raise():
    with pytest.raises(ValueError):
        RegimeVoteStrategy(lookbacks=[])
    with pytest.raises(ValueError):
        RegimeVoteStrategy(lookbacks=(10, 0))


def test_majority_is_computed_not_a_tunable_parameter():
    """Aucun seuil de vote reglable : la majorite se DEDUIT du nombre d'horizons."""
    params = inspect.signature(RegimeVoteStrategy.__init__).parameters
    assert set(params) == {"self", "lookbacks"}
    assert RegimeVoteStrategy(lookbacks=(1, 2, 3)).min_votes == 2
    assert RegimeVoteStrategy(lookbacks=(1, 2, 3, 4)).min_votes == 3   # majorite STRICTE
    assert RegimeVoteStrategy(lookbacks=(1, 2, 3, 4, 5)).min_votes == 3


# --------------------------------------------------------------------------- #
#  R0 -- causalite (le critere qui annule tout s'il tombe)                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("facteur", [4.0, 0.25])
def test_causalite_le_futur_ne_change_aucun_signal_passe(long_df, facteur):
    k = 800
    ref = build_strategy("regime").generate_signals(long_df)
    trafique = long_df.copy()
    trafique.iloc[k + 1:] = trafique.iloc[k + 1:] * facteur
    autre = build_strategy("regime").generate_signals(trafique)
    pd.testing.assert_series_equal(ref.iloc[:k + 1], autre.iloc[:k + 1])


def test_causalite_le_test_sait_mordre(long_df):
    """Le test ci-dessus ne vaut que s'il DETECTE une vraie fuite : on en fabrique une."""
    class Tricheuse(Strategy):
        name = "tricheuse"

        def generate_signals(self, df):
            futur = df["close"].shift(-1)
            return (futur > df["close"]).fillna(False).astype(int)

    k = 800
    ref = Tricheuse().generate_signals(long_df)
    vues = []
    for facteur in (4.0, 0.25):
        trafique = long_df.copy()
        trafique.iloc[k + 1:] = trafique.iloc[k + 1:] * facteur
        autre = Tricheuse().generate_signals(trafique)
        vues.append(not ref.iloc[:k + 1].equals(autre.iloc[:k + 1]))
    assert any(vues)          # la fuite est vue (le signal en k depend de k+1)


def test_determinisme(long_df):
    a = build_strategy("regime").generate_signals(long_df)
    b = build_strategy("regime").generate_signals(long_df)
    c = build_strategy("regime").generate_signals(long_df.copy())
    pd.testing.assert_series_equal(a, b)
    pd.testing.assert_series_equal(a, c)


# --------------------------------------------------------------------------- #
#  Le vote est bien un vote -- cas construits a la main                       #
# --------------------------------------------------------------------------- #
def _df(closes):
    return make_ohlcv(closes)


def test_vote_3_haussiers_2_baissiers_donne_risk_on():
    # lookbacks 1..5 ; a la derniere bougie (80) :
    #   L1 80>70 oui | L2 80>60 oui | L3 80>50 oui | L4 80>99 non | L5 80>100 non  -> 3/5
    df = _df([100, 99, 50, 60, 70, 80])
    strat = RegimeVoteStrategy(lookbacks=(1, 2, 3, 4, 5))
    sig = strat.generate_signals(df)
    assert strat.vote_counts(df).iloc[-1] == 3
    assert sig.iloc[-1] == 1
    assert strat.gate_info["regime"] == RISK_ON
    assert strat.gate_info["voix_pour"] == 3 and strat.gate_info["majorite_requise"] == 3


def test_vote_2_haussiers_3_baissiers_donne_risk_off():
    #   L1 80>70 oui | L2 80>60 oui | L3 80>90 non | L4 80>99 non | L5 80>100 non -> 2/5
    df = _df([100, 99, 90, 60, 70, 80])
    strat = RegimeVoteStrategy(lookbacks=(1, 2, 3, 4, 5))
    sig = strat.generate_signals(df)
    assert strat.vote_counts(df).iloc[-1] == 2
    assert sig.iloc[-1] == 0
    assert strat.gate_info["regime"] == RISK_OFF


def test_vote_unanime_dans_les_deux_sens():
    hausse = _df([10, 20, 30, 40, 50, 60])
    baisse = _df([60, 50, 40, 30, 20, 10])
    strat = RegimeVoteStrategy(lookbacks=(1, 2, 3, 4, 5))
    assert strat.generate_signals(hausse).iloc[-1] == 1
    assert strat.vote_counts(hausse).iloc[-1] == 5
    assert strat.generate_signals(baisse).iloc[-1] == 0
    assert strat.vote_counts(baisse).iloc[-1] == 0


def test_chaque_voix_est_exactement_un_tsmom(long_df):
    """Les membres du vote sont la brique validee de l'etude #5, pas une variante."""
    strat = build_strategy("regime")
    votes = strat.votes(long_df)
    for L in DEFAULT_LOOKBACKS:
        attendu = TSMomentum(L).generate_signals(long_df)
        pd.testing.assert_series_equal(votes[f"L{L}"], attendu, check_names=False)


def test_signal_egale_majorite_des_voix(long_df):
    strat = build_strategy("regime")
    sig = strat.generate_signals(long_df)
    counts = strat.vote_counts(long_df)
    pd.testing.assert_series_equal(sig, (counts >= 3).astype(int), check_names=False)


def test_regime_labels(long_df):
    strat = build_strategy("regime")
    labels = strat.regime_labels(long_df)
    sig = strat.generate_signals(long_df)
    assert set(labels.unique()).issubset({RISK_ON, RISK_OFF})
    assert (labels == RISK_ON).astype(int).equals(sig)


# --------------------------------------------------------------------------- #
#  Donnees insuffisantes : cash, et surtout aucun plantage                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("n", [0, 1, 2, 50, 179])
def test_donnees_insuffisantes_reste_en_cash(n):
    df = make_ohlcv(_prices(n)) if n else make_ohlcv([100.0]).iloc[0:0]
    sig = build_strategy("regime").generate_signals(df)
    assert len(sig) == n
    assert sig.sum() == 0                       # aucun horizon ne peut voter -> cash


def test_moins_de_365_bougies_ne_peut_jamais_atteindre_la_majorite():
    # Serie strictement croissante de 300 bougies : seuls 180 et 270 peuvent voter
    # -> 2 voix au maximum, la majorite (3) est hors d'atteinte -> cash tout du long.
    df = make_ohlcv([100 + i for i in range(300)])
    strat = build_strategy("regime")
    assert strat.vote_counts(df).max() == 2
    assert strat.generate_signals(df).sum() == 0


def test_horizon_non_amorce_vote_zero():
    """Convention TSMomentum : tant qu'on ne SAIT pas, on est hors marche."""
    df = make_ohlcv([100 + i for i in range(10)])
    strat = RegimeVoteStrategy(lookbacks=(1, 2, 3, 4, 5))
    votes = strat.votes(df)
    assert votes.iloc[0].sum() == 0             # aucun decalage disponible
    assert votes.iloc[-1].sum() == 5            # tous amorces, tous haussiers


# --------------------------------------------------------------------------- #
#  Amorcage declare + branchement walk-forward                                #
# --------------------------------------------------------------------------- #
def test_warmup_declare_couvre_le_plus_long_horizon():
    strat = build_strategy("regime")
    assert strat.warmup_bars == max(DEFAULT_LOOKBACKS) + WARMUP_EXTRA == 600
    params = {"lookbacks": DEFAULT_LOOKBACKS}
    assert _declared_warmup(RegimeVoteStrategy, params) == 600
    # _params_warmup seul (qui ne lit que les entiers) sous-estimerait : d'ou le besoin.
    assert _params_warmup(params) < 600


def test_walk_forward_accepte_le_regime():
    ensure_optimizer_grid()
    assert "regime" in DEFAULT_GRIDS
    df = make_ohlcv(_prices(1400))
    res = walk_forward(df, "regime", n_windows=4, train_frac=0.5,
                       fixed_params={"lookbacks": DEFAULT_LOOKBACKS})
    assert res["n_trials"] == 1                 # aucune optimisation, rien a data-miner
    assert len(res["windows"]) == 4
    assert np.isfinite(res["oos_total_return"])


def test_ensure_optimizer_grid_est_idempotent():
    a = ensure_optimizer_grid()
    b = ensure_optimizer_grid()
    assert a is b
    grid, is_valid = b
    assert list(grid) == ["lookbacks"] and len(grid["lookbacks"]) == 1


# --------------------------------------------------------------------------- #
#  NON-REGRESSION : l'existant ne bouge pas d'un iota                          #
# --------------------------------------------------------------------------- #
def test_registre_existant_intact():
    for cle, classe in (("sma", SMACrossover), ("tsmom", TSMomentum),
                        ("rsi", RSIStrategy), ("macd", MACDStrategy),
                        ("bollinger", BollingerStrategy)):
        assert STRATEGIES[cle] is classe


def test_strategies_existantes_signaux_inchanges(long_df):
    """Le signal de chaque strategie du registre est celui de sa classe, intact."""
    attendus = {"sma": SMACrossover(), "tsmom": TSMomentum(), "rsi": RSIStrategy(),
                "macd": MACDStrategy(), "bollinger": BollingerStrategy()}
    for cle, instance in attendus.items():
        pd.testing.assert_series_equal(build_strategy(cle).generate_signals(long_df),
                                       instance.generate_signals(long_df),
                                       check_names=False)


def test_amorcage_declare_reste_nul_pour_les_strategies_classiques():
    """`_declared_warmup` doit continuer a renvoyer 0 partout ailleurs (etudes #4/#5/#7)."""
    assert _declared_warmup(TSMomentum, {"lookback": 365}) == 0
    assert _declared_warmup(SMACrossover, {"fast": 50, "slow": 200}) == 0


def test_walk_forward_tsmom_inchange_par_l_ajout_du_regime():
    """Meme entree, meme sortie qu'avant : le module regime n'a rien effet de bord."""
    df = make_ohlcv(_prices(1400))
    a = walk_forward(df, "tsmom", n_windows=4, train_frac=0.5,
                     fixed_params={"lookback": 365})
    import trading.regime  # noqa: F401  (deja importe ; on force l'effet de bord eventuel)
    b = walk_forward(df, "tsmom", n_windows=4, train_frac=0.5,
                     fixed_params={"lookback": 365})
    assert a["oos_total_return"] == b["oos_total_return"]
    assert a["n_trials"] == b["n_trials"] == 1
