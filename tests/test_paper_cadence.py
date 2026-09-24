"""
Tests LOT A (constat C15) : la cadence du paper/live se cale sur la cloture des
bougies quand `poll_seconds` n'est pas fourni explicitement, au lieu de dormir
un multiple fixe de la timeframe qui peut deriver de l'horloge Kraken.

`next_close_wait_seconds` est une fonction PURE (horloge `now_ts` INJECTEE en
parametre) : testee sans monkeypatch. `_next_wait_seconds` (methode d'instance)
est testee en injectant l'horloge via `trading.paper_trader.time.time`
(monkeypatch), pour verifier le branchement complet (mode auto vs explicite).

Aucun reseau, aucune cle API : FakeExchange local, tout sous tmp_path.
"""
import config
from trading import paper_trader
from trading.paper_trader import PaperTrader, next_close_wait_seconds
from trading.strategies import build_strategy


class FakeExchange:
    def fetch_ohlcv(self, symbol, timeframe, limit=200):
        return None

    def fetch_price(self, symbol):
        return 1.0


def _paper(tmp_path, timeframe="1h", poll_seconds=None, name="s.json"):
    return PaperTrader(FakeExchange(), build_strategy("sma"), timeframe=timeframe,
                       poll_seconds=poll_seconds, state_file=str(tmp_path / name),
                       stats_file=None, log_file=None,
                       initial_capital=10_000, fee=0.0)


# --------------------------------------------------------------------------- #
#  next_close_wait_seconds : fonction PURE, horloge injectee                  #
# --------------------------------------------------------------------------- #
def test_attend_le_reste_du_cycle_plus_la_marge():
    # 1h = 3600s ; on est a 900s apres une cloture -> il reste 2700s + marge
    now_ts = 10 * 3600 + 900
    assert next_close_wait_seconds("1h", 60, now_ts) == 2700 + 60


def test_pile_a_la_cloture_attend_un_cycle_plein_plus_la_marge():
    now_ts = 7 * 86400  # exactement une cloture journaliere
    assert next_close_wait_seconds("1d", 60, now_ts) == 86400 + 60


def test_juste_avant_la_cloture_attend_presque_rien_plus_la_marge():
    now_ts = 5 * 3600 - 1  # 1s avant la cloture horaire
    assert next_close_wait_seconds("1h", 60, now_ts) == 1 + 60


def test_timeframe_inconnue_retombe_sur_une_heure():
    assert next_close_wait_seconds("bogus", 60, 0) == 3600 + 60


def test_marge_nulle_naffecte_que_la_marge():
    now_ts = 10 * 3600 + 900
    assert next_close_wait_seconds("1h", 0, now_ts) == 2700


# --------------------------------------------------------------------------- #
#  _Trader._next_wait_seconds : branchement explicite vs auto                 #
# --------------------------------------------------------------------------- #
def test_poll_seconds_explicite_garde_lattente_fixe_historique(tmp_path):
    pt = _paper(tmp_path, timeframe="1h", poll_seconds=120)
    assert pt._explicit_poll is True
    assert pt._next_wait_seconds() == 120


def test_poll_seconds_absent_active_le_mode_auto(tmp_path, monkeypatch):
    pt = _paper(tmp_path, timeframe="1h", poll_seconds=None)
    assert pt._explicit_poll is False
    monkeypatch.setattr(paper_trader.time, "time", lambda: 10 * 3600 + 900)
    assert pt._next_wait_seconds() == (3600 - 900) + config.CANDLE_CLOSE_MARGIN_SEC


def test_mode_auto_recalcule_a_chaque_appel_selon_lhorloge(tmp_path, monkeypatch):
    """L'attente auto n'est PAS figee a la construction : elle suit l'horloge
    injectee a chaque appel (utile si le cycle precedent a pris du temps)."""
    pt = _paper(tmp_path, timeframe="1h", poll_seconds=None)
    monkeypatch.setattr(paper_trader.time, "time", lambda: 0)
    premiere = pt._next_wait_seconds()
    monkeypatch.setattr(paper_trader.time, "time", lambda: 1800)
    seconde = pt._next_wait_seconds()
    assert premiere == 3600 + config.CANDLE_CLOSE_MARGIN_SEC
    assert seconde == 1800 + config.CANDLE_CLOSE_MARGIN_SEC


def test_poll_seconds_explicite_zero_reste_explicite(tmp_path):
    """0 est falsy mais reste une valeur EXPLICITEMENT fournie -- `is not None`,
    pas juste `or`, pilote le mode (garde-fou d'implementation)."""
    pt = _paper(tmp_path, timeframe="1h", poll_seconds=0)
    assert pt._explicit_poll is True
