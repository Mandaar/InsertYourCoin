"""
Bande anti-churn de SMACrossover (etude #6 -- les frais mangent 47% en 11 jours
quand la mediane des mouvements captures est -0.03% pour un palier a +1.62%).

Contrat (regle user 2026-08-20 : "pas des delais dans le marbre mais des
marges ; a chaque action le soft doit se demander s il repond a certains
tests") :
- `band` est une MARGE en multiples du cout d aller-retour (round_trip_cost,
  derive de config.FEE) -- si les frais changent, le seuil SUIT ;
- hysteresis : ACHAT si ecart > seuil, VENTE si ecart < -seuil, zone neutre
  entre les deux -> on conserve l etat courant (zero churn) ;
- band=0 (defaut) : comportement STRICTEMENT identique a l historique ;
- le dernier test evalue est expose (gate_info) pour le journal du paper.
"""
import pandas as pd
import pytest

import config
from trading.strategies import SMACrossover, build_strategy, round_trip_cost


def _df(prices):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"close": prices}, index=idx)


def test_round_trip_cost_suit_les_frais():
    # Arithmetique pure : 1/(1-f)^2 - 1. Taker 0.80% -> 1.62%, maker 0.40% -> 0.80%.
    assert round_trip_cost(0.008) == pytest.approx(0.016194, abs=1e-5)
    assert round_trip_cost(0.004) == pytest.approx(0.008048, abs=1e-5)
    # Sans argument : ancre sur config.FEE du moment (la marge est FLUIDE).
    assert round_trip_cost() == pytest.approx(round_trip_cost(config.FEE))


def test_band_zero_identique_au_comportement_historique():
    prices = [100 + (i % 7) - 3 + i * 0.3 for i in range(120)]
    df = _df(prices)
    sans = SMACrossover(fast=5, slow=20).generate_signals(df)
    avec = SMACrossover(fast=5, slow=20, band=0.0).generate_signals(df)
    assert (sans == avec).all(), "band=0 doit etre bit-identique a l historique"
    assert SMACrossover(fast=5, slow=20).name == "SMA(5/20)"


def test_hysteresis_ignore_les_micro_croisements():
    # Serie fabriquee : tendance plate avec micro-oscillations de ~0.2% autour
    # du croisement -> band=0 churne, band large ne bouge pas.
    base = [100.0] * 40
    osc = [100.0 + (0.2 if i % 2 else -0.2) for i in range(40)]
    df = _df(base + osc)
    flips = lambda s: int(s.diff().abs().sum())
    churn = flips(SMACrossover(fast=3, slow=10, band=0.0).generate_signals(df))
    calme = flips(SMACrossover(fast=3, slow=10, band=2.0).generate_signals(df))
    assert churn > 0, "le temoin doit churner (sinon la serie ne teste rien)"
    assert calme == 0, "avec la marge, aucun aller-retour sur du bruit sous le seuil"


def test_vraie_tendance_franchit_la_marge():
    # Hausse franche de 60% : l ecart fast/slow depasse largement 2x les frais
    # -> la strategie DOIT finir investie (la marge filtre le bruit, pas la tendance).
    prices = [100.0] * 30 + [100.0 * (1.02 ** i) for i in range(1, 41)]
    sig = SMACrossover(fast=3, slow=10, band=2.0).generate_signals(_df(prices))
    assert sig.iloc[-1] == 1, "une tendance reelle doit passer le test d achat"


def test_gate_info_expose_le_test_chiffre():
    prices = [100.0] * 30 + [100.0 * (1.02 ** i) for i in range(1, 41)]
    strat = SMACrossover(fast=3, slow=10, band=2.0)
    strat.generate_signals(_df(prices))
    g = strat.gate_info
    assert g is not None
    assert g["seuil_pct"] == pytest.approx(2.0 * round_trip_cost() * 100, abs=0.01)
    assert "ACHAT" in g["verdict"]


def test_build_strategy_accepte_les_params_du_walkforward():
    s = build_strategy("sma", {"fast": 50, "slow": 200, "band": 2})
    assert (s.fast, s.slow, s.band) == (50, 200, 2.0)
    assert "marge 2x frais" in s.name
    # Sans params : defauts historiques inchanges.
    s0 = build_strategy("sma")
    assert (s0.fast, s0.slow, s0.band) == (20, 50, 0.0)


def test_cli_params_atteint_la_strategie():
    # Le chemin CLI complet : --params "..." -> _parse_fixed -> build_strategy.
    import main as m
    import argparse
    args = argparse.Namespace(params="fast=50,slow=200,band=1.5")
    s = build_strategy("sma", m._strategy_params(args))
    assert (s.fast, s.slow, s.band) == (50, 200, 1.5)
    assert m._strategy_params(argparse.Namespace(params=None)) is None
