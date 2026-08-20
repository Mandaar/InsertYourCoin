"""
BUG-017 (P0, gate Lot 8B FAIL-1) : test d'INTEGRATION du chemin reel du live.

Les 8 tests de tests/test_live_reconcile.py appelaient reconcile() DIRECTEMENT ;
aucun ne verifiait que l'APPLICATION l'appelle. Resultat mesure par la gate :
la methode existait, testee, et JAMAIS invoquee en production -- une position
ouverte reprise apres un restart tournait sans stop ni trailing.

Ces tests ferment ce trou en passant par main.cmd_live (le vrai point d'entree,
celui que build_live_command lance dans le conteneur), avec de vrais doubles :
- l'ORDRE reconcile-avant-run est observe sur l'instance construite PAR cmd_live
  (pas une instance de test) ;
- le scenario de danger complet : etat persiste investi + Kraken investi ->
  apres le chemin reel, entry_price/peak sont restaures AVANT le premier tick
  de run(), donc _risk_overlay est arme.

Aucun reseau, aucune cle : KrakenExchange et build_strategy sont monkeypatches
dans le MODULE main (la ou cmd_live les resout).
"""
import argparse
import json

import pytest

import main
from trading import live_trader
from trading.live_trader import LiveTrader
from trading.strategies import build_strategy


class FakeExchange:
    """Meme patron que tests/test_live_reconcile.py : prix injectes, soldes
    en memoire. base_balance > seuil => 'Kraken investi' pour reconcile()."""
    def __init__(self, prices=(100.0,), balances=None):
        self._prices = list(prices)
        self._i = 0
        self.balances = dict(balances or {})

    def fetch_price(self, symbol):
        p = self._prices[min(self._i, len(self._prices) - 1)]
        self._i += 1
        return p

    def fetch_balance(self):
        return dict(self.balances)


def _args(execute=False):
    """Namespace minimal accepte par cmd_live + _bt_kwargs (memes champs que
    le parser `live` de main.py)."""
    return argparse.Namespace(
        execute=execute, symbol="ETH/USD", timeframe="1h", strategy="sma",
        stop_loss=5.0, take_profit=10.0, trailing_stop=None,
        position_sizing="none", target_vol=None,
    )


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Cable cmd_live sur des doubles et intercepte run() : retourne un
    journal d'appels + l'instance construite par cmd_live."""
    state = tmp_path / "live_state.json"
    monkeypatch.setattr(live_trader, "LOG_FILE", tmp_path / "live.log")
    # Cles presentes (sinon cmd_live sort avant de construire le trader).
    monkeypatch.setattr(main.config, "KRAKEN_API_KEY", "k", raising=False)
    monkeypatch.setattr(main.config, "KRAKEN_API_SECRET", "s", raising=False)

    fake = FakeExchange(prices=(100.0,), balances={"ETH": 2.0})
    journal = {"ordre": [], "trader": None}

    class TraderTrace(LiveTrader):
        """Sous-classe minimale : trace l'ordre des appels, run() ne boucle pas."""
        def __init__(self, *a, **kw):
            kw.setdefault("state_file", str(state))
            super().__init__(*a, **kw)
            journal["trader"] = self

        def reconcile(self):
            journal["ordre"].append("reconcile")
            return super().reconcile()

        def run(self):
            journal["ordre"].append("run")
            # Etat capture AU MOMENT ou run() demarre : c'est LA garantie
            # BUG-017 (le risque doit etre arme avant le premier tick).
            journal["etat_au_demarrage_de_run"] = {
                "entry_price": self.entry_price, "peak": self.peak,
            }

        # ccxt jamais construit : l'exchange est le fake injecte par cmd_live.

    monkeypatch.setattr(main, "LiveTrader", TraderTrace, raising=False)
    # cmd_live fait `from trading.live_trader import LiveTrader` localement :
    # patcher le nom DANS le module d'origine, la ou l'import le resout.
    monkeypatch.setattr(live_trader, "LiveTrader", TraderTrace)
    monkeypatch.setattr(main, "KrakenExchange", lambda: fake, raising=False)
    import trading.exchange as exchange_mod
    monkeypatch.setattr(exchange_mod, "KrakenExchange", lambda: fake)
    return {"state": state, "fake": fake, "journal": journal}


def test_cmd_live_appelle_reconcile_avant_run(wired):
    main.cmd_live(_args(execute=False))
    assert wired["journal"]["ordre"] == ["reconcile", "run"], (
        "le chemin reel doit appeler reconcile() PUIS run() -- BUG-017")


def test_cmd_live_rearme_le_risque_avant_le_premier_tick(wired):
    # Le scenario de danger exact de la gate : position ouverte persistee
    # (entry connu) + Kraken investi -> apres un restart, le chemin reel doit
    # restaurer entry/peak AVANT que run() ne demarre.
    wired["state"].write_text(json.dumps({
        "version": 1, "symbol": "ETH/USD", "entry_price": 90.0, "peak": 120.0,
        "entry_ts": 1.0, "entry_cost": 180.0, "last_trade_ts": 1.0,
    }), encoding="utf-8")
    main.cmd_live(_args(execute=False))
    etat = wired["journal"]["etat_au_demarrage_de_run"]
    assert etat["entry_price"] == 90.0, "entry_price non restaure : stop mort"
    assert etat["peak"] == 120.0, "peak non restaure : trailing mort"


def test_cmd_live_sans_etat_reste_defensif(wired):
    # Kraken investi mais AUCUN etat persiste (position orpheline) : la table
    # de verite S1.4 exige l'ADOPTION DEFENSIVE (ancrage au prix courant),
    # jamais un demarrage nu.
    main.cmd_live(_args(execute=False))
    etat = wired["journal"]["etat_au_demarrage_de_run"]
    assert etat["entry_price"] == 100.0, "adoption defensive absente"
    assert etat["peak"] == 100.0


def test_supervisor_lance_la_commande_qui_passe_par_cmd_live(tmp_path):
    # Complement (BUG-018) : le conteneur passe par build_live_command ->
    # `main.py live` -> cmd_live. Si la commande construite changeait de
    # sous-commande, le correctif BUG-017 serait contourne silencieusement.
    from trading.live_control import build_live_command
    cmd = build_live_command(tmp_path, {
        "strategy": "sma", "symbol": "ETH/USD", "timeframe": "1h",
        "stop_loss": 5.0, "take_profit": 10.0, "trailing_stop": None,
        "position_sizing": None, "target_vol": None,
    }, execute=False)
    assert "live" in cmd, "la commande conteneur doit invoquer la sous-commande live"
    i = cmd.index("live")
    assert cmd[i - 1].endswith("main.py"), "…celle de main.py (routee vers cmd_live)"
