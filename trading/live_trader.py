"""
Trading EN REEL sur Kraken.

⚠️  Argent reel. A n'utiliser qu'APRES validation en backtest puis en paper trading.

Garde-fous (definis dans config.py) :
  - dry_run = True par defaut : aucun ordre envoye tant que --execute n'est pas passe.
  - MAX_TRADE_VALUE_USD / MAX_POSITION_VALUE_USD : plafonds montant et exposition.
  - MIN_TRADE_INTERVAL_SEC : delai minimum entre deux ordres.
  - Stop-loss / take-profit verifies a chaque cycle.
  - Toutes les actions journalisees dans live_trades.log.
"""
import time
from pathlib import Path

import config
from .paper_trader import _Trader, now

LOG_FILE = Path("live_trades.log")


def _log(line: str):
    stamp = f"[{now()}] {line}"
    print(stamp)
    with LOG_FILE.open("a") as f:
        f.write(stamp + "\n")


class LiveTrader(_Trader):
    def __init__(self, exchange, strategy, symbol=None, timeframe=None,
                 stop_loss=None, take_profit=None, dry_run=True, poll_seconds=None):
        super().__init__(exchange, strategy, symbol, timeframe,
                         stop_loss, take_profit, poll_seconds)
        self.dry_run = dry_run
        self.entry_price = None
        self.last_trade_ts = 0.0
        mode = "DRY-RUN (aucun ordre envoye)" if dry_run else "REEL (ordres envoyes !)"
        _log(f"LiveTrader initialise en mode {mode}")

    def _base_balance(self):
        return self.exchange.fetch_balance().get(self.base, 0.0)

    def _quote_balance(self):
        return self.exchange.fetch_balance().get(self.quote, 0.0)

    def _is_invested(self, price):
        return self._base_balance() * price > 1.0  # >1$ d'actif = investi

    def _entry_price(self):
        return self.entry_price

    def _cooldown_ok(self):
        if time.time() - self.last_trade_ts < config.MIN_TRADE_INTERVAL_SEC:
            _log("Ordre ignore : delai minimum entre trades non ecoule (garde-fou).")
            return False
        return True

    def _rebalance(self, desired, price, reason):
        invested = self._is_invested(price)

        if desired == 1 and not invested:                       # ACHAT
            if not self._cooldown_ok():
                return
            budget = min(self._quote_balance(), config.MAX_TRADE_VALUE_USD)
            room = config.MAX_POSITION_VALUE_USD - self._base_balance() * price
            budget = max(0.0, min(budget, room))
            if budget < 1.0:
                _log("Achat ignore : budget sous le plafond/minimum (garde-fou).")
                return
            amount = budget / price
            if self.dry_run:
                _log(f"[DRY-RUN] ACHAT prevu : {amount:.5f} {self.base} (~{budget:.2f} {self.quote}) @ {price:.2f}")
            else:
                order = self.exchange.create_market_buy(self.symbol, amount)
                _log(f"ACHAT EXECUTE : {amount:.5f} {self.base} @ ~{price:.2f} | id={order.get('id')}")
                self.last_trade_ts = time.time()
            self.entry_price = price

        elif desired == 0 and invested:                         # VENTE
            if not self._cooldown_ok():
                return
            amount = self._base_balance()
            tag = f" [{reason}]" if reason else ""
            if self.dry_run:
                _log(f"[DRY-RUN] VENTE prevue{tag} : {amount:.5f} {self.base} @ {price:.2f}")
            else:
                order = self.exchange.create_market_sell(self.symbol, amount)
                _log(f"VENTE EXECUTEE{tag} : {amount:.5f} {self.base} @ ~{price:.2f} | id={order.get('id')}")
                self.last_trade_ts = time.time()
            self.entry_price = None

    def _log_status(self, price):
        try:
            val = self._base_balance() * price
            _log(f"prix {price:.2f} | {self.base} ~{val:.2f} {self.quote} | cash {self._quote_balance():.2f} {self.quote}")
        except Exception as e:
            _log(f"Lecture du solde impossible : {e}")
