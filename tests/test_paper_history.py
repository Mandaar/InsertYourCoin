"""
Tests LOT A (constat C01) : l'historique charge par le paper suit le besoin
d'amorcage de la strategie, au lieu d'un `limit=200` fige.

Avant le correctif, TSMOM(lookback=365) ne recevait que 200 bougies (199
cloturees) : `close.shift(365)` restait NaN sur toute la fenetre et le signal
etait fige a 0 -- jamais de position. Ces tests EXERCENT le chemin production
(`PaperTrader._closed_candles` / `_run_cycle`) : si le `limit` redevient fige a
200, `test_tsmom_365_avec_assez_dhistorique_peut_passer_en_position` echoue.

Aucun reseau, aucune cle API : `FakeExchange` local, tout sous tmp_path.
"""
import numpy as np
import pytest

from trading.paper_trader import PaperTrader, _required_history, _MAX_CANDLES
from trading.strategies import build_strategy


class FakeExchange:
    """Exchange factice qui respecte `limit` (dernieres lignes), comme Kraken."""
    def __init__(self, df=None, prices=None):
        self._df = df
        self._prices = list(prices) if prices is not None else [1.0]
        self._i = 0

    def fetch_ohlcv(self, symbol, timeframe, limit=200):
        return self._df if self._df is None else self._df.iloc[-limit:]

    def fetch_price(self, symbol):
        p = self._prices[min(self._i, len(self._prices) - 1)]
        self._i += 1
        return p


def _paper(tmp_path, ex, strategy, name="s.json", **kw):
    kw.setdefault("initial_capital", 10_000)
    kw.setdefault("fee", 0.0)
    return PaperTrader(ex, strategy, state_file=str(tmp_path / name),
                       stats_file=None, log_file=str(tmp_path / "trades.log"), **kw)


# --------------------------------------------------------------------------- #
#  _required_history : le besoin d'amorcage, pur                              #
# --------------------------------------------------------------------------- #
def test_sma_20_50_garde_le_plancher_historique_de_200():
    assert _required_history(build_strategy("sma")) == 200          # fast=20, slow=50


def test_rsi_macd_bollinger_gardent_aussi_200():
    assert _required_history(build_strategy("rsi")) == 200
    assert _required_history(build_strategy("macd")) == 200
    assert _required_history(build_strategy("bollinger")) == 200


def test_tsmom_365_a_besoin_de_415_bougies():
    # 365 (lookback) + 50 (marge, meme constante que optimizer._params_warmup)
    assert _required_history(build_strategy("tsmom", {"lookback": 365})) == 415


def test_tsmom_lookback_court_reste_au_plancher_de_200():
    assert _required_history(build_strategy("tsmom", {"lookback": 30})) == 200


# --------------------------------------------------------------------------- #
#  PaperTrader charge REELLEMENT ce besoin (via fetch_ohlcv `limit=`)         #
# --------------------------------------------------------------------------- #
def test_papertrader_calcule_le_meme_besoin_que_la_fonction_pure(tmp_path):
    pt = _paper(tmp_path, FakeExchange(), build_strategy("tsmom", {"lookback": 365}))
    assert pt._required_candles == 415


def test_papertrader_sma_reste_a_200_non_regression(tmp_path):
    pt = _paper(tmp_path, FakeExchange(), build_strategy("sma"))
    assert pt._required_candles == 200


def test_tsmom_365_avec_assez_dhistorique_peut_passer_en_position(tmp_path, make_df):
    """Preuve du correctif (constat C01) : 719 bougies CROISSANTES, `limit`
    calcule (415) suffit largement a amorcer TSMOM(365) -> le signal sort de 0
    et le cycle investit. Si `_closed_candles` retombe sur `limit=200` fige, la
    fenetre cloturee (199) est trop courte, le signal reste 0 et cette assertion
    echoue : c'est le garde-fou anti-regression du constat C01."""
    closes = 100.0 * np.linspace(1.0, 2.0, 719)          # strictement croissant
    df = make_df(list(closes), freq="1D")
    ex = FakeExchange(df=df, prices=[closes[-1]])
    strat = build_strategy("tsmom", {"lookback": 365})
    pt = _paper(tmp_path, ex, strat)

    pt._run_cycle()

    assert pt.state["invested"] is True
    assert len(pt.state["trades"]) == 1 and pt.state["trades"][0]["side"] == "buy"


def test_tsmom_365_tronque_a_200_naurait_jamais_pu_investir(make_df):
    """Documente le defaut d'ORIGINE (sans passer par PaperTrader) : sur la MEME
    serie croissante, 200 bougies brutes (199 cloturees) ne suffisent jamais a
    amorcer TSMOM(365) -- `close.shift(365)` reste NaN partout, signal fige a 0.
    C'est exactement pourquoi `_required_history` doit depasser 200 ici."""
    closes = 100.0 * np.linspace(1.0, 2.0, 719)
    df = make_df(list(closes), freq="1D")
    closed_199 = df.iloc[-200:].iloc[:-1]                 # ancien comportement fige
    strat = build_strategy("tsmom", {"lookback": 365})
    signal = int(strat.generate_signals(closed_199).iloc[-1])
    assert signal == 0


# --------------------------------------------------------------------------- #
#  Refus de demarrer si le besoin depasse le plafond Kraken (720/appel)       #
# --------------------------------------------------------------------------- #
def test_refuse_de_demarrer_si_le_besoin_depasse_le_plafond_kraken(tmp_path):
    strat = build_strategy("tsmom", {"lookback": 700})    # 700 + 50 = 750 > 720
    with pytest.raises(RuntimeError) as exc:
        _paper(tmp_path, FakeExchange(), strat)
    msg = str(exc.value)
    assert "750" in msg and str(_MAX_CANDLES) in msg


def test_lookback_tout_juste_sous_le_plafond_demarre(tmp_path):
    strat = build_strategy("tsmom", {"lookback": 669})    # 669 + 50 = 719 <= 720
    pt = _paper(tmp_path, FakeExchange(), strat)
    assert pt._required_candles == 719


# --------------------------------------------------------------------------- #
#  Historique insuffisant EN COURS DE ROUTE : pas de decision, ligne journal   #
# --------------------------------------------------------------------------- #
def test_historique_insuffisant_ne_decide_rien_et_ecrit_la_ligne(tmp_path, make_df):
    df = make_df(list(range(100, 150)))                   # 50 bougies seulement
    ex = FakeExchange(df=df, prices=[999.0])
    strat = build_strategy("tsmom", {"lookback": 365})    # besoin : 415
    pt = _paper(tmp_path, ex, strat)

    pt._run_cycle()

    assert pt.state["invested"] is False
    assert pt.state["trades"] == []
    log_text = (tmp_path / "trades.log").read_text(encoding="utf-8")
    assert "historique insuffisant" in log_text
    assert "414" in log_text        # requis = _required_candles(415) - 1
