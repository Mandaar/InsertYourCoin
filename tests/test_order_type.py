"""
Tests du LOT A : ordres LIMITE (maker) vs ordres MARCHE (taker).

Aucun reseau, aucune cle API : exchange factice, prix injectes, `time.sleep`
neutralise. Le point critique teste ici est la COHERENCE frais <-> type d'ordre :
simuler des frais maker en passant des ordres marche serait un mensonge de mesure.
"""
import time

import pytest

import config
import main
from trading import live_trader
from trading.exchange import KrakenExchange
from trading.live_trader import LiveTrader
from trading.paper_trader import PaperTrader
from trading.strategies import build_strategy


# --------------------------------------------------------------------------- #
#  Faux exchange : enregistre les ordres, simule des remplissages scriptes     #
# --------------------------------------------------------------------------- #
class FakeLimitExchange:
    """
    `fills` = liste des quantites remplies renvoyees par les `fetch_order`
    successifs (scenario de remplissage). Les appels sont tous journalises.
    """
    def __init__(self, df=None, prices=None, balances=None, fills=None,
                 place_raises=False):
        self._df = df
        self._prices = list(prices or [100.0])
        self._i = 0
        self.balances = dict(balances or {})
        self.orders = []          # ordres places : (type, side, amount, price)
        self.cancels = []
        self.fetches = 0
        self._fills = list(fills or [])
        self._place_raises = place_raises

    # --- donnees ---
    def fetch_ohlcv(self, symbol, timeframe, limit=200):
        return self._df

    def fetch_price(self, symbol):
        p = self._prices[min(self._i, len(self._prices) - 1)]
        self._i += 1
        return p

    def fetch_balance(self):
        return dict(self.balances)

    # --- ordres ---
    def create_market_buy(self, symbol, amount):
        self.orders.append(("market", "buy", amount, None))
        return {"id": "m-buy", "filled": amount}

    def create_market_sell(self, symbol, amount):
        self.orders.append(("market", "sell", amount, None))
        return {"id": "m-sell", "filled": amount}

    def create_limit_buy(self, symbol, amount, price):
        if self._place_raises:
            raise RuntimeError("postOnly rejected")
        self.orders.append(("limit", "buy", amount, price))
        return {"id": "l-buy", "filled": 0.0, "status": "open"}

    def create_limit_sell(self, symbol, amount, price):
        if self._place_raises:
            raise RuntimeError("postOnly rejected")
        self.orders.append(("limit", "sell", amount, price))
        return {"id": "l-sell", "filled": 0.0, "status": "open"}

    def fetch_order(self, order_id, symbol):
        self.fetches += 1
        filled = self._fills[min(self.fetches - 1, len(self._fills) - 1)] if self._fills else 0.0
        return {"id": order_id, "filled": filled, "status": "open"}

    def cancel_order(self, order_id, symbol):
        self.cancels.append(order_id)
        return {"id": order_id, "status": "canceled"}


@pytest.fixture(autouse=True)
def _no_sleep_no_repo_writes(tmp_path, monkeypatch):
    """Pas d'attente reelle (les tests d'attente bornee doivent rester instantanes)
    et aucun fichier ecrit dans le depot (E2/L3)."""
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(live_trader, "LOG_FILE", tmp_path / "live_trades.log")
    monkeypatch.setattr(live_trader, "STATE_FILE", tmp_path / "live_state.json")


def _live(exchange, **kw):
    """LiveTrader de test. `limit_timeout=0` par defaut : l'ordre est interroge
    UNE fois puis conclu -- les tests restent instantanes sans rien mocker de
    l'horloge (la borne de temps elle-meme est testee a part, horloge simulee)."""
    kw.setdefault("dry_run", False)
    kw.setdefault("limit_timeout", 0)
    return LiveTrader(exchange, build_strategy("sma"), symbol="ETH/USD",
                      timeframe="1h", stats_file=None, **kw)


# --------------------------------------------------------------------------- #
#  1. Coherence frais <-> type d'ordre (LE point critique)                     #
# --------------------------------------------------------------------------- #
def test_config_fee_for_order_type_mappe_market_taker_et_limit_maker():
    assert config.fee_for_order_type("market") == config.FEE_TAKER
    assert config.fee_for_order_type("limit") == config.FEE_MAKER
    with pytest.raises(ValueError):
        config.fee_for_order_type("stop")


def test_order_type_limit_selectionne_fee_maker_paper_et_live(tmp_path):
    paper = PaperTrader(FakeLimitExchange(), build_strategy("sma"),
                        state_file=tmp_path / "s.json", stats_file=None,
                        log_file=None, order_type="limit")
    live = _live(FakeLimitExchange(), order_type="limit")
    assert paper.fee == config.FEE_MAKER
    assert live.fee == config.FEE_MAKER


def test_order_type_market_selectionne_fee_taker_paper_et_live(tmp_path):
    paper = PaperTrader(FakeLimitExchange(), build_strategy("sma"),
                        state_file=tmp_path / "s.json", stats_file=None,
                        log_file=None, order_type="market")
    live = _live(FakeLimitExchange(), order_type="market")
    assert paper.fee == config.FEE_TAKER
    assert live.fee == config.FEE_TAKER


def test_defaut_sans_option_est_market_taker_inchange(tmp_path):
    """NON-REGRESSION : sans la nouvelle option, tout se comporte comme avant."""
    paper = PaperTrader(FakeLimitExchange(), build_strategy("sma"),
                        state_file=tmp_path / "s.json", stats_file=None, log_file=None)
    live = _live(FakeLimitExchange())
    assert paper.order_type == "market" and live.order_type == "market"
    assert paper.fee == config.FEE == config.FEE_TAKER
    assert live.fee == config.FEE


def test_cli_order_type_defaut_market_et_choix_limit():
    p = main.build_parser()
    for cmd in ("paper", "live"):
        assert p.parse_args([cmd]).order_type == "market"
        assert p.parse_args([cmd, "--order-type", "limit"]).order_type == "limit"
    with pytest.raises(SystemExit):
        p.parse_args(["paper", "--order-type", "iceberg"])


def test_order_kwargs_ne_passe_jamais_de_fee():
    """Le CLI ne peut pas faire diverger frais et type d'ordre : il ne transmet
    QUE `order_type` ; `fee` reste derive par config.fee_for_order_type."""
    args = main.build_parser().parse_args(["paper", "--order-type", "limit"])
    kw = main._order_kwargs(args)
    assert kw == {"order_type": "limit"}
    assert "fee" not in kw and "fee" not in main._bt_kwargs(args)


def test_fee_paid_journalise_suit_le_type_d_ordre(tmp_path):
    """Le frais ENREGISTRE dans les stats suit le type d'ordre, des deux cotes."""
    ex_m = FakeLimitExchange(balances={"USD": 1000.0}, prices=[100.0])
    taker = _live(ex_m, order_type="market")
    trade_m = taker._rebalance(1, 100.0, None, 1.0)

    ex_l = FakeLimitExchange(balances={"USD": 1000.0}, prices=[100.0], fills=[1.0])
    maker = _live(ex_l, order_type="limit")
    trade_l = maker._rebalance(1, 100.0, None, 1.0)

    assert trade_m["fee_paid"] == pytest.approx(config.MAX_TRADE_VALUE_USD * config.FEE_TAKER)
    assert trade_l["fee_paid"] == pytest.approx(config.MAX_TRADE_VALUE_USD * config.FEE_MAKER)
    assert trade_l["fee_paid"] < trade_m["fee_paid"]


# --------------------------------------------------------------------------- #
#  2. L'ordre limite est bien construit avec postOnly                          #
# --------------------------------------------------------------------------- #
class _SpyClient:
    def __init__(self):
        self.apiKey = "k"
        self.secret = "s"
        self.calls = []

    def create_order(self, symbol, type_, side, amount, price=None, params=None):
        self.calls.append((symbol, type_, side, amount, price, params))
        return {"id": "x"}

    def cancel_order(self, oid, symbol):
        self.calls.append(("cancel", oid, symbol))
        return {"id": oid}

    def fetch_order(self, oid, symbol):
        self.calls.append(("fetch", oid, symbol))
        return {"id": oid, "filled": 0.0}


def _spied_exchange():
    ex = KrakenExchange.__new__(KrakenExchange)   # pas de ccxt reel, pas de reseau
    ex.client = _SpyClient()
    return ex


def test_create_limit_buy_et_sell_utilisent_postOnly():
    ex = _spied_exchange()
    ex.create_limit_buy("ETH/USD", 2.0, 1500.0)
    ex.create_limit_sell("ETH/USD", 2.0, 1600.0)
    buy, sell = ex.client.calls[0], ex.client.calls[1]
    assert buy[1:5] == ("limit", "buy", 2.0, 1500.0)
    assert buy[5] == {"postOnly": True}
    assert sell[1:5] == ("limit", "sell", 2.0, 1600.0)
    assert sell[5] == {"postOnly": True}


def test_ordres_marche_restent_sans_params_postOnly():
    """NON-REGRESSION : le chemin marche existant n'est pas touche."""
    ex = _spied_exchange()
    ex.create_market_buy("ETH/USD", 1.0)
    assert ex.client.calls[0][:4] == ("ETH/USD", "market", "buy", 1.0)
    assert ex.client.calls[0][4] is None and ex.client.calls[0][5] is None


def test_cancel_et_fetch_order_exigent_des_cles():
    ex = _spied_exchange()
    ex.client.apiKey = ""
    for call in (lambda: ex.cancel_order("1", "ETH/USD"),
                 lambda: ex.fetch_order("1", "ETH/USD"),
                 lambda: ex.create_limit_buy("ETH/USD", 1.0, 1.0),
                 lambda: ex.create_limit_sell("ETH/USD", 1.0, 1.0)):
        with pytest.raises(RuntimeError):
            call()


# --------------------------------------------------------------------------- #
#  3. Non-remplissage : annulation + aucune position fantome                   #
# --------------------------------------------------------------------------- #
def test_achat_limite_non_rempli_est_annule_et_ne_cree_aucune_position():
    ex = FakeLimitExchange(balances={"USD": 1000.0}, prices=[100.0], fills=[0.0])
    tr = _live(ex, order_type="limit")
    trade = tr._rebalance(1, 100.0, None, 1.0)

    assert trade is None                       # aucun trade enregistre
    assert tr.entry_price is None              # AUCUNE position fantome
    assert tr.entry_cost is None and tr.peak is None
    assert ex.cancels == ["l-buy"]             # l'ordre a bien ete annule
    assert tr.last_trade_ts == 0.0             # pas de cooldown consomme


def test_attente_est_bornee_par_le_timeout_puis_annulation(monkeypatch):
    """L'attente s'arrete au bout du delai (horloge simulee), puis annule."""
    ex = FakeLimitExchange(balances={"USD": 1000.0}, prices=[100.0], fills=[0.0])
    tr = _live(ex, order_type="limit", limit_timeout=10)
    clock = {"t": 0.0}

    def _tick():
        clock["t"] += 2.0        # chaque lecture d'horloge avance de 2 s (simule)
        return clock["t"]

    monkeypatch.setattr(live_trader.time, "time", _tick)
    assert tr._place_limit("buy", 1.0, 100.0) == 0.0
    assert ex.cancels == ["l-buy"]
    assert ex.fetches <= 10                    # borne, pas une boucle infinie


def test_timeout_limite_est_borne_par_la_cadence_du_cycle():
    """Jamais d'attente plus longue qu'un cycle de re-evaluation."""
    tr = _live(FakeLimitExchange(), order_type="limit", poll_seconds=5,
               limit_timeout=None)          # None -> defaut config (60 s)
    assert tr.limit_timeout == 5            # ... rabote a la cadence du cycle
    tr2 = _live(FakeLimitExchange(), order_type="limit", poll_seconds=3600,
                limit_timeout=None)
    assert tr2.limit_timeout == config.LIMIT_ORDER_TIMEOUT_SEC


def test_rejet_postOnly_a_l_envoi_ne_cree_aucune_position():
    ex = FakeLimitExchange(balances={"USD": 1000.0}, prices=[100.0], place_raises=True)
    tr = _live(ex, order_type="limit")
    assert tr._rebalance(1, 100.0, None, 1.0) is None
    assert tr.entry_price is None and ex.cancels == []


def test_vente_limite_non_remplie_laisse_la_position_ouverte():
    """Une sortie de risque non remplie ne doit PAS effacer les ancres de risque
    (sinon la position resterait ouverte sans stop ni trailing)."""
    ex = FakeLimitExchange(balances={"ETH": 1.0, "USD": 0.0}, prices=[100.0], fills=[0.0])
    tr = _live(ex, order_type="limit")
    tr.entry_price, tr.peak, tr.entry_cost, tr.entry_ts = 120.0, 130.0, 120.0, 1.0

    assert tr._rebalance(0, 100.0, "STOP-LOSS", 1.0) is None
    assert tr.entry_price == 120.0 and tr.peak == 130.0   # ancres INTACTES
    assert ex.cancels == ["l-sell"]


# --------------------------------------------------------------------------- #
#  4. Remplissage PARTIEL : la position vaut le rempli REEL                    #
# --------------------------------------------------------------------------- #
def test_achat_partiellement_rempli_donne_une_position_egale_au_rempli():
    ex = FakeLimitExchange(balances={"USD": 1000.0}, prices=[100.0], fills=[0.4])
    tr = _live(ex, order_type="limit")
    amount_demande = config.MAX_TRADE_VALUE_USD / 100.0     # plafond garde-fou

    trade = tr._rebalance(1, 100.0, None, 1.0)

    assert ex.orders[0][:2] == ("limit", "buy")
    assert ex.orders[0][2] == pytest.approx(amount_demande)  # demande = plafond
    assert 0.4 < amount_demande                              # rempli PARTIEL
    assert tr.entry_cost == pytest.approx(0.4 * 100.0)       # cout = le REMPLI
    assert trade["fee_paid"] == pytest.approx(0.4 * 100.0 * config.FEE_MAKER)
    assert ex.cancels == ["l-buy"]                           # le reste est annule


def test_vente_partiellement_remplie_solde_au_prorata_et_garde_le_reste():
    ex = FakeLimitExchange(balances={"ETH": 1.0, "USD": 0.0}, prices=[100.0], fills=[0.25])
    tr = _live(ex, order_type="limit")
    tr.entry_price, tr.peak, tr.entry_cost, tr.entry_ts = 80.0, 100.0, 80.0, 1.0

    trade = tr._rebalance(0, 100.0, None, 1.0)

    assert trade["action"] == "sell"
    # 25 % vendus : produit 0.25*100, cout impute 25 % de 80.
    assert trade["pnl"] == pytest.approx(0.25 * 100.0 * (1 - config.FEE_MAKER) - 20.0)
    assert trade["fee_paid"] == pytest.approx(0.25 * 100.0 * config.FEE_MAKER)
    assert tr.entry_price == 80.0                 # position residuelle : ancres gardees
    assert tr.entry_cost == pytest.approx(60.0)   # 75 % du cout reste engage


# --------------------------------------------------------------------------- #
#  5. Non-regression du chemin MARCHE (aucune option passee)                   #
# --------------------------------------------------------------------------- #
def test_chemin_marche_inchange_aucun_ordre_limite_ni_annulation():
    ex = FakeLimitExchange(balances={"USD": 1000.0}, prices=[100.0])
    tr = _live(ex)                                # defaut : market
    trade = tr._rebalance(1, 100.0, None, 1.0)
    assert [o[:2] for o in ex.orders] == [("market", "buy")]
    assert ex.cancels == [] and ex.fetches == 0
    assert trade["action"] == "buy"
    assert tr.entry_cost == pytest.approx(config.MAX_TRADE_VALUE_USD)


def test_dry_run_ne_passe_aucun_ordre_meme_en_limite():
    """Garde-fou live : le dry-run reste muet cote exchange, quel que soit le type."""
    ex = FakeLimitExchange(balances={"USD": 1000.0}, prices=[100.0], fills=[1.0])
    tr = _live(ex, order_type="limit", dry_run=True)
    trade = tr._rebalance(1, 100.0, None, 1.0)
    assert ex.orders == [] and ex.cancels == [] and ex.fetches == 0
    assert trade["action"] == "buy" and tr.last_trade_ts == 0.0


def test_paper_en_limite_facture_le_maker_sur_un_achat_simule(tmp_path):
    ex = FakeLimitExchange(prices=[100.0])
    pt = PaperTrader(ex, build_strategy("sma"), state_file=tmp_path / "s.json",
                     stats_file=None, log_file=None, order_type="limit",
                     initial_capital=1000.0)
    trade = pt._rebalance(1, 100.0, None, 1.0)
    assert trade["fee_paid"] == pytest.approx(1000.0 * config.FEE_MAKER)
    assert pt.state["base_amount"] == pytest.approx(1000.0 * (1 - config.FEE_MAKER) / 100.0)
