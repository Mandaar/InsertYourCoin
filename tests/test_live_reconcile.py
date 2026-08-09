"""
Persistance et reprise sure du LiveTrader (Lot 8B, argent reel en conteneur).

Reference gelee : docs/design/LOT8B_LIVE_CONTENEUR_SPEC.md S1 (S1.2 schema,
S1.3 quand ecrire, S1.4 table de verite de reconcile()). Plan de tests exige :
S7, bloc "Persistance & reprise" (tests 1 a 8).

Aucun reseau, aucune cle API : FakeExchange en memoire (meme patron que
tests/test_trader.py). Chaque test redirige explicitement `state_file` (et
`LOG_FILE` via la fixture autouse) vers tmp_path -- rien n'est ecrit dans le
depot.
"""
import json
import time

import pytest

from trading import live_trader
from trading.live_trader import LiveTrader
from trading.strategies import build_strategy


class FakeExchange:
    """Exchange factice : prix injectes (une valeur consommee par appel), soldes
    en memoire, ordres enregistres. Identique au patron de tests/test_trader.py."""
    def __init__(self, df=None, prices=None, balances=None):
        self._df = df
        self._prices = list(prices) if prices is not None else []
        self._i = 0
        self.balances = dict(balances or {})
        self.orders = []

    def fetch_ohlcv(self, symbol, timeframe, limit=200):
        return self._df

    def fetch_price(self, symbol):
        p = self._prices[min(self._i, len(self._prices) - 1)]
        self._i += 1
        return p

    def fetch_balance(self):
        return dict(self.balances)

    def create_market_buy(self, symbol, amount):
        self.orders.append(("buy", amount))
        return {"id": "fake-buy"}

    def create_market_sell(self, symbol, amount):
        self.orders.append(("sell", amount))
        return {"id": "fake-sell"}


@pytest.fixture(autouse=True)
def _redirect_live_log(tmp_path, monkeypatch):
    """Evite d'ecrire live_trades.log dans le depot pendant les tests (E2/L3)."""
    monkeypatch.setattr(live_trader, "LOG_FILE", tmp_path / "live_trades.log")


def _write_state(path, **overrides):
    """Ecrit un live_state.json valide (schema S1.2) avec des overrides cibles."""
    base = {
        "version": 1, "mode": "reel", "symbol": "ETH/USD", "timeframe": "5m",
        "strategy": "sma", "invested": False, "entry_price": None, "peak": None,
        "entry_ts": None, "entry_cost": None, "last_trade_ts": 0.0,
        "updated_ts": 0.0,
    }
    base.update(overrides)
    path.write_text(json.dumps(base, indent=2))


def _live(ex, tmp_path, state_name="live_state.json", **kw):
    kw.setdefault("dry_run", True)
    return LiveTrader(ex, build_strategy("sma"), symbol="ETH/USD",
                      state_file=str(tmp_path / state_name), **kw)


# --------------------------------------------------------------------------- #
#  1. Persistance : roundtrip, ecriture atomique, aucun secret                #
# --------------------------------------------------------------------------- #
def test_live_state_roundtrip(tmp_path):
    ex = FakeExchange(balances={"USD": 1000.0})
    lt = _live(ex, tmp_path, timeframe="5m")
    lt.entry_price = 3120.5
    lt.peak = 3240.0
    lt.entry_ts = 1765300000.0
    lt.entry_cost = 98.7
    lt.last_trade_ts = 1765300000.0
    lt._save_state()

    state_file = tmp_path / "live_state.json"
    assert state_file.exists()
    assert not (tmp_path / "live_state.json.tmp").exists()  # ecriture atomique : pas de residu

    data = json.loads(state_file.read_text())
    assert data["version"] == 1
    assert data["mode"] == "dry"
    assert data["symbol"] == "ETH/USD"
    assert data["timeframe"] == "5m"
    assert data["invested"] is True
    assert data["entry_price"] == 3120.5
    assert data["peak"] == 3240.0
    assert data["entry_ts"] == 1765300000.0
    assert data["entry_cost"] == 98.7
    assert data["last_trade_ts"] == 1765300000.0
    assert "updated_ts" in data

    # Une nouvelle instance relit le meme contenu brut (sans le charger dans self).
    lt2 = _live(ex, tmp_path)
    raw = lt2._load_raw_state()
    assert raw["entry_price"] == 3120.5 and raw["peak"] == 3240.0
    # __init__ ne charge JAMAIS automatiquement (reconcile() est un pas delibere).
    assert lt2.entry_price is None and lt2.peak is None


def test_live_state_ecriture_atomique_pas_de_residu(tmp_path):
    ex = FakeExchange(balances={"USD": 1000.0})
    lt = _live(ex, tmp_path)
    lt.entry_price = 10.0
    lt._save_state()
    lt.entry_price = 20.0
    lt._save_state()
    assert json.loads((tmp_path / "live_state.json").read_text())["entry_price"] == 20.0
    assert not (tmp_path / "live_state.json.tmp").exists()


def test_live_state_sans_cle_ni_solde(tmp_path):
    ex = FakeExchange(balances={"USD": 1000.0})
    lt = _live(ex, tmp_path, dry_run=False)
    lt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    raw_text = (tmp_path / "live_state.json").read_text()
    for forbidden in ("apiKey", "api_key", "KRAKEN_API", "secret", "cash", "base_amount"):
        assert forbidden not in raw_text


# --------------------------------------------------------------------------- #
#  2. reconcile() -- la table de verite a 4 cas (S1.4), l'exchange fait foi   #
# --------------------------------------------------------------------------- #
def test_reconcile_reprise_normale_investie(tmp_path):
    state_file = tmp_path / "live_state.json"
    _write_state(state_file, invested=True, entry_price=3000.0, peak=3300.0,
                 entry_ts=111.0, entry_cost=300.0, last_trade_ts=222.0)
    ex = FakeExchange(balances={"ETH": 1.0}, prices=[3200.0])  # base*price >> 1$ -> investi
    lt = _live(ex, tmp_path)

    result = lt.reconcile()

    assert result == {"kraken_invested": True, "state_invested": True}
    assert lt.entry_price == 3000.0
    assert lt.peak == 3300.0
    assert lt.entry_ts == 111.0
    assert lt.entry_cost == 300.0
    assert lt.last_trade_ts == 222.0


def test_reconcile_divergence_kraken_investi_etat_flat(tmp_path):
    state_file = tmp_path / "live_state.json"
    _write_state(state_file, invested=False, entry_price=None, peak=None,
                 entry_ts=None, entry_cost=None, last_trade_ts=555.0)
    ex = FakeExchange(balances={"ETH": 2.0}, prices=[150.0])
    lt = _live(ex, tmp_path)

    result = lt.reconcile()

    assert result == {"kraken_invested": True, "state_invested": False}
    # Adoption defensive : ancre au prix courant, jamais un rachat ni une vente.
    assert lt.entry_price == 150.0
    assert lt.peak == 150.0
    assert lt.entry_cost == pytest.approx(2.0 * 150.0)
    assert lt.entry_ts is not None
    assert lt.last_trade_ts == 555.0  # cooldown preserve malgre la divergence
    assert ex.orders == []
    saved = json.loads(state_file.read_text())
    assert saved["entry_price"] == 150.0 and saved["invested"] is True
    log_text = (tmp_path / "live_trades.log").read_text()
    assert "ADOPTION DEFENSIVE" in log_text


def test_reconcile_divergence_kraken_flat_etat_investi(tmp_path):
    state_file = tmp_path / "live_state.json"
    _write_state(state_file, invested=True, entry_price=100.0, peak=120.0,
                 entry_ts=10.0, entry_cost=100.0, last_trade_ts=20.0)
    ex = FakeExchange(balances={}, prices=[100.0])  # aucun ETH detenu -> flat
    lt = _live(ex, tmp_path)

    result = lt.reconcile()

    assert result == {"kraken_invested": False, "state_invested": True}
    assert lt.entry_price is None and lt.peak is None
    assert lt.entry_ts is None and lt.entry_cost is None
    assert lt.last_trade_ts == 20.0
    assert ex.orders == []  # JAMAIS de rachat sur un etat perime
    saved = json.loads(state_file.read_text())
    assert saved["invested"] is False and saved["entry_price"] is None
    log_text = (tmp_path / "live_trades.log").read_text()
    assert "RETOUR A PLAT" in log_text or "retour a plat" in log_text


def test_reconcile_etat_absent_kraken_investi(tmp_path):
    ex = FakeExchange(balances={"ETH": 0.5}, prices=[400.0])
    lt = _live(ex, tmp_path)  # aucun live_state.json n'existe

    result = lt.reconcile()

    assert result == {"kraken_invested": True, "state_invested": False}
    assert lt.entry_price == 400.0 and lt.peak == 400.0
    assert lt.entry_cost == pytest.approx(0.5 * 400.0)
    assert lt.last_trade_ts == 0.0
    assert ex.orders == []
    assert (tmp_path / "live_state.json").exists()  # reconcile persiste toujours


def test_reconcile_etat_absent_kraken_flat(tmp_path):
    ex = FakeExchange(balances={}, prices=[100.0])
    lt = _live(ex, tmp_path)

    result = lt.reconcile()

    assert result == {"kraken_invested": False, "state_invested": False}
    assert lt.entry_price is None and lt.peak is None
    assert ex.orders == []


# --------------------------------------------------------------------------- #
#  3. Le cooldown et le risk overlay tiennent apres reprise (danger n1)        #
# --------------------------------------------------------------------------- #
def test_last_trade_ts_survit_au_restart(tmp_path):
    state_file = tmp_path / "live_state.json"
    recent_trade = time.time() - 10  # il y a 10s -- tres en dessous de MIN_TRADE_INTERVAL_SEC
    _write_state(state_file, invested=False, entry_price=None, peak=None,
                 entry_ts=None, entry_cost=None, last_trade_ts=recent_trade)
    ex = FakeExchange(balances={}, prices=[100.0])
    lt = _live(ex, tmp_path, dry_run=False)

    lt.reconcile()

    # Sans persistance, un restart remettrait last_trade_ts a 0.0 et le cooldown
    # serait contourne par un simple redemarrage (spec S1.2) -- ici il tient.
    assert lt.last_trade_ts == pytest.approx(recent_trade)
    assert lt._cooldown_ok() is False


def test_risk_overlay_actif_apres_reprise(tmp_path):
    """Non-regression du danger n1 (spec S0ter) : paper_trader.py:159-160 sort
    immediatement de _risk_overlay si entry_price est absent. Apres reconcile()
    sur une position reprise, le stop doit de nouveau declencher."""
    state_file = tmp_path / "live_state.json"
    _write_state(state_file, invested=True, entry_price=100.0, peak=100.0,
                 entry_ts=1000.0, entry_cost=100.0, last_trade_ts=900.0)
    ex = FakeExchange(balances={"ETH": 1.0}, prices=[100.0])
    lt = _live(ex, tmp_path, stop_loss=0.05)

    # AVANT reconcile() : etat en memoire vide -> le danger n1 tel que documente
    # (_risk_overlay sort silencieusement, aucun stop actif).
    assert lt._risk_overlay(1, 90.0) == (1, None)

    lt.reconcile()

    # APRES reconcile() : le stop-loss (-5%) redevient actif sur la position reprise.
    d, r = lt._risk_overlay(1, 90.0)  # -10% < -5% -> stop
    assert d == 0 and r == "STOP-LOSS"
