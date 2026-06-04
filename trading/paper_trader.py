"""
Paper trading : stratégie en temps reel sur les VRAIS prix Kraken, argent FICTIF.
Inclut le stop-loss / take-profit (verifies a chaque cycle).

`_Trader` = boucle commune (signal -> overlay risque -> rebalancement -> attente).
`LiveTrader` (live_trader.py) en herite pour le trading reel.
"""
import json
import time
import datetime as dt
from pathlib import Path

import config

_TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
               "1h": 3600, "4h": 14400, "1d": 86400}


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Trader:
    def __init__(self, exchange, strategy, symbol=None, timeframe=None,
                 stop_loss=None, take_profit=None, poll_seconds=None):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol or config.DEFAULT_SYMBOL
        self.timeframe = timeframe or config.DEFAULT_TIMEFRAME
        self.stop_loss = config.STOP_LOSS if stop_loss is None else stop_loss
        self.take_profit = config.TAKE_PROFIT if take_profit is None else take_profit
        self.poll_seconds = poll_seconds or _TF_SECONDS.get(self.timeframe, 3600)
        self.base = self.symbol.split("/")[0]
        self.quote = self.symbol.split("/")[1]

    def _latest_signal(self) -> int:
        """Signal sur la derniere bougie CLOTUREE (la bougie en cours est ignoree)."""
        df = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=200)
        df = df.iloc[:-1]
        return int(self.strategy.generate_signals(df).iloc[-1])

    def _risk_overlay(self, desired: int, price: float):
        """Le stop-loss / take-profit peut forcer une sortie, par-dessus le signal."""
        ep = self._entry_price()
        if self._is_invested(price) and ep:
            if self.stop_loss and price <= ep * (1 - self.stop_loss):
                return 0, "STOP-LOSS"
            if self.take_profit and price >= ep * (1 + self.take_profit):
                return 0, "TAKE-PROFIT"
        return desired, None

    def run(self):
        risk = []
        if self.stop_loss:
            risk.append(f"stop -{self.stop_loss*100:g}%")
        if self.take_profit:
            risk.append(f"objectif +{self.take_profit*100:g}%")
        risk_txt = (" | " + ", ".join(risk)) if risk else ""
        print(f"[{now()}] Demarrage : {self.strategy} sur {self.symbol} ({self.timeframe}){risk_txt}")
        print(f"[{now()}] Re-evaluation toutes les {self.poll_seconds} s. Ctrl+C pour arreter.\n")
        while True:
            try:
                desired = self._latest_signal()
                price = self.exchange.fetch_price(self.symbol)
                desired, reason = self._risk_overlay(desired, price)
                self._rebalance(desired, price, reason)
                self._log_status(price)
            except KeyboardInterrupt:
                print(f"\n[{now()}] Arret demande. A bientot.")
                break
            except Exception as e:
                print(f"[{now()}] Erreur (on reessaie au prochain cycle) : {e}")
            time.sleep(self.poll_seconds)

    # Implementes par les sous-classes
    def _rebalance(self, desired, price, reason): raise NotImplementedError
    def _log_status(self, price): raise NotImplementedError
    def _is_invested(self, price): raise NotImplementedError
    def _entry_price(self): raise NotImplementedError


class PaperTrader(_Trader):
    def __init__(self, exchange, strategy, symbol=None, timeframe=None,
                 stop_loss=None, take_profit=None, initial_capital=None,
                 fee=None, poll_seconds=None, state_file="paper_state.json"):
        super().__init__(exchange, strategy, symbol, timeframe,
                         stop_loss, take_profit, poll_seconds)
        self.fee = config.FEE if fee is None else fee
        self.state_file = Path(state_file)
        init_cap = config.INITIAL_CAPITAL if initial_capital is None else initial_capital
        self.state = self._load_state(init_cap)

    def _load_state(self, init_cap):
        if self.state_file.exists():
            print(f"[{now()}] Reprise de l'etat depuis {self.state_file}")
            return json.loads(self.state_file.read_text())
        return {"cash": init_cap, "base_amount": 0.0, "invested": False,
                "entry_price": None, "trades": []}

    def _save(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def _is_invested(self, price): return self.state["invested"]
    def _entry_price(self): return self.state.get("entry_price")

    def _rebalance(self, desired, price, reason):
        s = self.state
        if desired == 1 and not s["invested"]:
            s["base_amount"] = (s["cash"] * (1 - self.fee)) / price
            s["cash"] = 0.0
            s["invested"] = True
            s["entry_price"] = price
            s["trades"].append({"time": now(), "side": "buy", "price": price})
            print(f"[{now()}] >>> ACHAT (simule) : {s['base_amount']:.5f} {self.base} @ {price:.2f}")
            self._save()
        elif desired == 0 and s["invested"]:
            s["cash"] = s["base_amount"] * price * (1 - self.fee)
            tag = f" [{reason}]" if reason else ""
            print(f"[{now()}] >>> VENTE (simule){tag} : {s['base_amount']:.5f} {self.base} @ {price:.2f}")
            s["base_amount"] = 0.0
            s["invested"] = False
            s["entry_price"] = None
            s["trades"].append({"time": now(), "side": "sell", "price": price, "reason": reason})
            self._save()

    def _log_status(self, price):
        s = self.state
        value = s["cash"] + s["base_amount"] * price
        etat = "INVESTI" if s["invested"] else "CASH"
        print(f"[{now()}] {etat:7s} | prix {price:.2f} | portefeuille {value:,.2f} {self.quote} "
              f"| {len(s['trades'])} ordres")
