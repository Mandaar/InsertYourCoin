"""
Tests du harness de l'etude #10 (SMA 200 j en cadence MENSUELLE).

Ce que ces tests garantissent, et pourquoi :

- **non-lookahead** : la decision du dernier jour du mois n'utilise QUE les
  clotures jusqu'a ce jour inclus. Deux controles complementaires : (a) egalite
  exacte avec une SMA recalculee sur le seul PREFIXE de la serie ; (b) causalite
  -- reecrire tout le futur apres la barre k ne change aucun signal jusqu'a k.
  Si l'un des deux tombe, tous les chiffres de l'etude sont nuls (critere gele
  §0.7 de docs/ETUDE_10_SMA200_MENSUEL.md) ;
- **cadence mensuelle** : une decision par mois, pas une par jour -- c'est le
  point du dossier qui n'avait jamais ete teste ;
- **tenue de position entre deux decisions** ;
- **execution a l'ouverture de la barre SUIVANTE** (convention du projet) ;
- **determinisme** : deux executions identiques donnent le meme resultat au bit
  pres (aucun aleatoire, aucune dependance a l'ordre d'iteration) ;
- **fenetres identiques a optimizer.walk_forward** : le decoupage OOS du script
  n'est pas une reinvention.

Aucun reseau, aucune cle, aucune fenetre.
"""
import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

from conftest import make_ohlcv
from trading.backtester import Backtester
from trading.optimizer import walk_forward

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts", "etude10_sma200_mensuel.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("etude10_sma200_mensuel", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E10 = _load_module()


# --------------------------------------------------------------------------- #
# Donnees synthetiques : 3 ans de daily, deterministes (aucune graine aleatoire)
# --------------------------------------------------------------------------- #
def _series(n=1100, start="2019-01-01"):
    t = np.arange(n, dtype=float)
    # tendance + deux cycles de longueurs differentes -> la SMA 200 est franchie
    # plusieurs fois dans les deux sens, sans aucun tirage aleatoire.
    closes = 100.0 * (1.0 + 0.0006 * t) * (1.0 + 0.30 * np.sin(t / 90.0)
                                           + 0.12 * np.sin(t / 23.0))
    return make_ohlcv(closes.tolist(), start=start)


@pytest.fixture(scope="module")
def df():
    return _series()


# --------------------------------------------------------------------------- #
# 1. Cadence mensuelle
# --------------------------------------------------------------------------- #
def test_decisions_une_par_mois(df):
    pos = E10.decision_positions(df.index, 0)
    dates = df.index[pos]
    # une decision par mois calendaire couvert (a un mois pres en bordure)
    mois = len(set(zip(df.index.year, df.index.month)))
    assert mois - 1 <= len(pos) <= mois
    ecarts = np.diff(dates.values).astype("timedelta64[D]").astype(int)
    assert ecarts.min() >= 28 and ecarts.max() <= 31


def test_decisions_sont_les_derniers_jours_du_mois(df):
    pos = E10.decision_positions(df.index, 0)
    for p in pos:
        d = df.index[p]
        suivant = df.index[p + 1] if p + 1 < len(df.index) else None
        assert suivant is None or suivant.month != d.month


@pytest.mark.parametrize("offset", [0, 7, 14, 21])
def test_toutes_les_tranches_restent_mensuelles(df, offset):
    pos = E10.decision_positions(df.index, offset)
    ecarts = np.diff(df.index[pos].values).astype("timedelta64[D]").astype(int)
    assert ecarts.min() >= 28 and ecarts.max() <= 31


def test_les_quatre_tranches_decident_des_jours_differents(df):
    jours = {k: set(E10.decision_positions(df.index, k).tolist()) for k in (0, 7, 14, 21)}
    for a in (0, 7, 14, 21):
        for b in (0, 7, 14, 21):
            if a < b:
                assert jours[a] != jours[b]
                # recouvrement marginal seulement (mois de longueurs inegales)
                assert len(jours[a] & jours[b]) < 0.2 * len(jours[a])


def test_aucune_decision_apres_la_fin_de_serie(df):
    for k in (0, 7, 14, 21):
        pos = E10.decision_positions(df.index, k)
        assert pos.max() < len(df.index)
        assert (np.diff(pos) > 0).all()          # triees, sans doublon


# --------------------------------------------------------------------------- #
# 2. Non-lookahead -- le test qui annule l'etude s'il tombe
# --------------------------------------------------------------------------- #
def test_sma_du_jour_de_decision_n_utilise_que_le_passe(df):
    """La SMA du jour de decision, recalculee sur le SEUL prefixe de la serie
    (aucune barre posterieure n'existe), doit donner exactement le meme signal."""
    strat = E10.MonthlySMA(period=200, offset_days=0)
    sig = strat.generate_signals(df)
    for p in E10.decision_positions(df.index, 0):
        prefixe = df["close"].iloc[:p + 1]
        if len(prefixe) < 200:
            assert sig.iloc[p] == 0
            continue
        attendu = int(prefixe.iloc[-1] > prefixe.iloc[-200:].mean())
        assert int(sig.iloc[p]) == attendu, f"desaccord au {df.index[p].date()}"


def test_causalite_reecrire_le_futur_ne_change_pas_le_passe(df):
    """Controle de causalite (methode etude #8 §1.2) : on multiplie par 4 puis on
    divise par 4 tout ce qui suit la barre k. Aucun signal jusqu'a k ne bouge."""
    strat = E10.MonthlySMA(period=200, offset_days=0)
    base = strat.generate_signals(df)
    k = 700
    for facteur in (4.0, 0.25):
        trafique = df.copy()
        for col in ("open", "high", "low", "close"):
            trafique.iloc[k + 1:, trafique.columns.get_loc(col)] *= facteur
        autre = E10.MonthlySMA(period=200, offset_days=0).generate_signals(trafique)
        pd.testing.assert_series_equal(base.iloc[:k + 1], autre.iloc[:k + 1])


def test_le_test_de_causalite_sait_mordre(df):
    """Garde-fou du garde-fou : une strategie qui REGARDE le futur doit faire
    tomber le test precedent. Sinon le test ne prouverait rien."""
    class Tricheuse(E10.MonthlySMA):
        def generate_signals(self, d):
            futur = d["close"].shift(-1)
            return (futur > d["close"]).fillna(False).astype(int)

    base = Tricheuse().generate_signals(df)
    k = 700
    detecte = False
    for facteur in (4.0, 0.25):
        trafique = df.copy()
        trafique.iloc[k + 1:, trafique.columns.get_loc("close")] *= facteur
        autre = Tricheuse().generate_signals(trafique)
        detecte |= not base.iloc[:k + 1].equals(autre.iloc[:k + 1])
    assert detecte, "le controle de causalite ne detecte meme pas une tricheuse"


def test_flat_tant_que_la_sma_n_est_pas_amorcee(df):
    sig = E10.MonthlySMA(period=200, offset_days=0).generate_signals(df)
    assert (sig.iloc[:200] == 0).all()


# --------------------------------------------------------------------------- #
# 3. Tenue de position et execution differee
# --------------------------------------------------------------------------- #
def test_la_position_est_tenue_entre_deux_decisions(df):
    sig = E10.MonthlySMA(period=200, offset_days=0).generate_signals(df)
    decisions = set(E10.decision_positions(df.index, 0).tolist())
    changements = {i for i in range(1, len(sig)) if sig.iloc[i] != sig.iloc[i - 1]}
    # tout changement de signal a lieu UN JOUR DE DECISION, jamais entre deux
    assert changements.issubset(decisions)
    assert changements, "serie de test degeneree : aucun changement de signal"


def test_execution_a_l_ouverture_de_la_barre_suivante(df):
    """Le moteur decale d'une barre : un signal qui passe a 1 au jour j se traduit
    par une position ouverte au jour j+1, jamais au jour j."""
    strat = E10.MonthlySMA(period=200, offset_days=0)
    sig = strat.generate_signals(df)
    res = Backtester(fee=0.0, slippage=0.0).run(df, strat)
    changements = [i for i in range(1, len(sig)) if sig.iloc[i] != sig.iloc[i - 1]]
    premier = changements[0]
    assert res.df["position"].iloc[premier] == 0.0
    assert res.df["position"].iloc[premier + 1] == 1.0


# --------------------------------------------------------------------------- #
# 4. Determinisme
# --------------------------------------------------------------------------- #
def test_signaux_deterministes(df):
    a = E10.MonthlySMA(period=200, offset_days=14).generate_signals(df)
    b = E10.MonthlySMA(period=200, offset_days=14).generate_signals(df)
    pd.testing.assert_series_equal(a, b)


def test_mesure_deterministe(df):
    p = {"period": 200, "offset_days": 7}
    a = E10.run_windowed(df, E10.MonthlySMA, p, 0.004, 0.0005)
    b = E10.run_windowed(df, E10.MonthlySMA, p, 0.004, 0.0005)
    assert a["ret"] == b["ret"] and a["n_trades"] == b["n_trades"]
    c = E10.run_continuous(df, E10.MonthlySMA, p, 0.004, 0.0005)
    d = E10.run_continuous(df, E10.MonthlySMA, p, 0.004, 0.0005)
    assert c == d


# --------------------------------------------------------------------------- #
# 5. Le harness ne reinvente pas le decoupage du projet
# --------------------------------------------------------------------------- #
def test_fenetres_identiques_a_walk_forward(df):
    """Meme arithmetique de fenetres que optimizer.walk_forward : on le PROUVE en
    comparant les bornes de periode renvoyees par le moteur du projet."""
    res = walk_forward(df, "tsmom", n_windows=E10.N_WINDOWS, train_frac=E10.TRAIN_FRAC,
                       fixed_params={"lookback": 200})
    attendues = [(df.index[s], df.index[e - 1]) for s, e in E10.windows_of(len(df))]
    assert [w["period"] for w in res["windows"]] == attendues


def test_run_windowed_reproduit_walk_forward_sur_tsmom(df):
    """Le rendement OOS compose du harness doit coller a celui du moteur officiel
    pour une strategie ENREGISTREE (ici TSMOM), sinon le harness est faux."""
    from trading.strategies import STRATEGIES
    p = {"lookback": 200}
    mine = E10.run_windowed(df, STRATEGIES["tsmom"], p, None, None)["ret"]
    ref = walk_forward(df, "tsmom", n_windows=E10.N_WINDOWS, train_frac=E10.TRAIN_FRAC,
                       fixed_params=p)["oos_total_return"]
    assert abs(mine - ref) < 1e-12


def test_buy_and_hold_est_investi_en_permanence(df):
    res = Backtester(fee=0.0, slippage=0.0).run(df, E10.AlwaysLong())
    assert res.df["position"].iloc[1:].min() == 1.0
    assert len(res.trades) == 1


# --------------------------------------------------------------------------- #
# 6. Le holdout n'est pas touche par le chargement de l'etude
# --------------------------------------------------------------------------- #
def test_offsets_geles():
    """Les 4 tranches sont GELEES (etude #10 §0.4) : toute derive se voit ici."""
    assert E10.OFFSETS == (0, 7, 14, 21)
    assert E10.SMA_PERIOD == 200
    assert E10.N_WINDOWS == 4 and E10.TRAIN_FRAC == 0.5
    assert E10.VERDICT_SYMBOL == "BTC/USD"
