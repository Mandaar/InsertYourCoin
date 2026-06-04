"""
Tests de la logique trailing stop + sizing par volatilite cablee dans paper/live.

Aucun reseau, aucune cle API : on injecte un faux exchange et des prix simules,
et on appelle directement les briques (_rebalance, _risk_overlay, _entry_fraction).
"""
import json

import numpy as np
import pytest

import config
from trading import live_trader
from trading.backtester import Backtester
from trading.live_trader import LiveTrader
from trading.paper_trader import PaperTrader
from trading.strategies import build_strategy


class FakeExchange:
    """Exchange factice : OHLCV fixe, prix injectes, soldes en memoire, ordres enregistres."""
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
    """Evite d'ecrire live_trades.log dans le depot pendant les tests."""
    monkeypatch.setattr(live_trader, "LOG_FILE", tmp_path / "live_trades.log")


def _volatile(n, seed=0):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.05, n)))


def _paper(tmp_path, name="state.json", **kw):
    kw.setdefault("initial_capital", 10_000)
    kw.setdefault("fee", 0.0)
    return PaperTrader(FakeExchange(), build_strategy("sma"),
                       state_file=str(tmp_path / name), **kw)


# --------------------------------------------------------------------------- #
#  PaperTrader : sizing                                                        #
# --------------------------------------------------------------------------- #
def test_paper_invests_all_cash_without_sizing(tmp_path):
    pt = _paper(tmp_path)
    pt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    assert pt.state["invested"] is True
    assert pt.state["cash"] == 0.0
    assert pt.state["base_amount"] == pytest.approx(100.0)   # 10000 / 100
    assert pt.state["entry_price"] == 100.0 and pt.state["peak"] == 100.0
    pt._rebalance(0, price=110.0, reason="signal", fraction=1.0)
    assert pt.state["invested"] is False
    assert pt.state["cash"] == pytest.approx(11_000.0)       # 100 * 110
    assert pt.state["peak"] is None


def test_paper_partial_sizing_invests_only_fraction(tmp_path):
    pt = _paper(tmp_path, position_sizing="vol")
    pt._rebalance(1, price=100.0, reason=None, fraction=0.25)
    assert pt.state["cash"] == pytest.approx(7_500.0)
    assert pt.state["base_amount"] == pytest.approx(25.0)    # 2500 / 100
    assert pt.state["invested"] is True


def test_paper_zero_fraction_skips_entry(tmp_path):
    pt = _paper(tmp_path, position_sizing="vol")
    pt._rebalance(1, price=100.0, reason=None, fraction=0.0)
    assert pt.state["invested"] is False
    assert pt.state["cash"] == 10_000.0


# --------------------------------------------------------------------------- #
#  PaperTrader : trailing stop + persistance du peak                           #
# --------------------------------------------------------------------------- #
def test_paper_peak_persisted_and_reloaded(tmp_path):
    pt = _paper(tmp_path, trailing_stop=0.10)
    pt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    pt._set_peak(150.0)
    assert json.loads((tmp_path / "state.json").read_text())["peak"] == 150.0
    pt2 = _paper(tmp_path, trailing_stop=0.10)              # nouvelle instance, meme fichier
    assert pt2._peak() == 150.0


def test_paper_trailing_stop_triggers(tmp_path):
    pt = _paper(tmp_path, trailing_stop=0.10)
    pt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    assert pt._risk_overlay(1, 120.0) == (1, None)          # monte : on suit
    assert pt._peak() == 120.0
    assert pt._risk_overlay(1, 109.0) == (1, None)          # 120*0.9=108 ; 109>108
    d, r = pt._risk_overlay(1, 107.0)                       # 107<=108 -> sortie
    assert d == 0 and r == "TRAILING-STOP"


def test_paper_fixed_stop_wins_when_tighter(tmp_path):
    pt = _paper(tmp_path, stop_loss=0.05, trailing_stop=0.20)
    pt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    d, r = pt._risk_overlay(1, 94.0)                        # fixe 95 > trailing 80
    assert d == 0 and r == "STOP-LOSS"


def test_paper_trailing_wins_after_peak_rises(tmp_path):
    pt = _paper(tmp_path, stop_loss=0.05, trailing_stop=0.20)
    pt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    pt._risk_overlay(1, 150.0)                              # peak 150 -> trailing 120 > fixe 95
    d, r = pt._risk_overlay(1, 119.0)
    assert d == 0 and r == "TRAILING-STOP"


def test_paper_take_profit_triggers(tmp_path):
    pt = _paper(tmp_path, take_profit=0.20)
    pt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    d, r = pt._risk_overlay(1, 121.0)
    assert d == 0 and r == "TAKE-PROFIT"


# --------------------------------------------------------------------------- #
#  _entry_fraction : coherence avec le backtester                             #
# --------------------------------------------------------------------------- #
def test_entry_fraction_is_one_without_sizing(tmp_path, make_df):
    pt = _paper(tmp_path)
    assert pt._entry_fraction(make_df(_volatile(60))) == 1.0


def test_entry_fraction_vol_in_range_and_monotonic(tmp_path, make_df):
    df = make_df(_volatile(60))
    lo = _paper(tmp_path, "a.json", position_sizing="vol", target_vol=0.20,
                vol_window=20, max_fraction=1.0)._entry_fraction(df)
    hi = _paper(tmp_path, "b.json", position_sizing="vol", target_vol=2.0,
                vol_window=20, max_fraction=1.0)._entry_fraction(df)
    assert 0.0 < lo <= 1.0
    assert hi >= lo                                         # cible plus haute -> investit plus


def test_entry_fraction_zero_when_too_short(tmp_path, make_df):
    pt = _paper(tmp_path, position_sizing="vol", vol_window=20)
    assert pt._entry_fraction(make_df(_volatile(10))) == 0.0


def test_entry_fraction_matches_backtester(tmp_path, make_df):
    closes = list(_volatile(60))
    df = make_df(closes)
    df_plus = make_df(closes + [closes[-1]])               # +1 bougie : execution a t+1
    bt = Backtester(position_sizing="vol", target_vol=0.30, vol_window=20, max_fraction=1.0)
    expected = bt._size_series(df_plus, bt._periods_per_year(df_plus))[-1]
    pt = _paper(tmp_path, position_sizing="vol", target_vol=0.30, vol_window=20, max_fraction=1.0)
    assert pt._entry_fraction(df) == pytest.approx(expected, rel=1e-9)


# --------------------------------------------------------------------------- #
#  LiveTrader : securite, plafonds, sizing, trailing en memoire               #
# --------------------------------------------------------------------------- #
def test_live_dry_run_places_no_order(tmp_path):
    ex = FakeExchange(balances={"USD": 1000.0})
    lt = LiveTrader(ex, build_strategy("sma"), symbol="ETH/USD", dry_run=True)
    lt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    assert ex.orders == []                                  # AUCUN ordre en dry-run
    assert lt.entry_price == 100.0 and lt.peak == 100.0     # etat interne a jour


def test_live_respects_max_trade_value_cap(tmp_path):
    ex = FakeExchange(balances={"USD": 100_000.0})          # cash >> plafond
    lt = LiveTrader(ex, build_strategy("sma"), symbol="ETH/USD", dry_run=False)
    lt._rebalance(1, price=100.0, reason=None, fraction=1.0)
    side, amount = ex.orders[0]
    assert side == "buy"
    assert amount * 100.0 <= config.MAX_TRADE_VALUE_USD + 1e-9
    assert amount == pytest.approx(config.MAX_TRADE_VALUE_USD / 100.0)


def test_live_vol_sizing_scales_order_below_caps(tmp_path):
    full = FakeExchange(balances={"USD": 50.0})             # cash faible : le sizing pilote
    half = FakeExchange(balances={"USD": 50.0})
    LiveTrader(full, build_strategy("sma"), dry_run=False)._rebalance(1, 100.0, None, 1.0)
    LiveTrader(half, build_strategy("sma"), dry_run=False)._rebalance(1, 100.0, None, 0.5)
    assert half.orders[0][1] == pytest.approx(full.orders[0][1] / 2)


def test_live_zero_fraction_no_order(tmp_path):
    ex = FakeExchange(balances={"USD": 1000.0})
    lt = LiveTrader(ex, build_strategy("sma"), dry_run=False)
    lt._rebalance(1, price=100.0, reason=None, fraction=0.0)
    assert ex.orders == [] and lt.entry_price is None


def test_live_trailing_tracks_in_memory(tmp_path):
    ex = FakeExchange(balances={"ETH": 1.0})               # 1 ETH detenu -> investi
    lt = LiveTrader(ex, build_strategy("sma"), symbol="ETH/USD",
                    dry_run=True, trailing_stop=0.10)
    lt.entry_price, lt.peak = 100.0, 100.0
    assert lt._risk_overlay(1, 120.0) == (1, None) and lt.peak == 120.0
    d, r = lt._risk_overlay(1, 107.0)                       # 120*0.9=108 ; 107<=108
    assert d == 0 and r == "TRAILING-STOP"


def test_live_sell_resets_entry_and_peak(tmp_path):
    ex = FakeExchange(balances={"ETH": 1.0})
    lt = LiveTrader(ex, build_strategy("sma"), symbol="ETH/USD", dry_run=False)
    lt.entry_price, lt.peak = 100.0, 130.0
    lt._rebalance(0, price=120.0, reason="TRAILING-STOP", fraction=1.0)
    assert lt.entry_price is None and lt.peak is None
    assert ex.orders[0][0] == "sell"
