"""
Paper trading : stratégie en temps reel sur les VRAIS prix Kraken, argent FICTIF.

Gere, comme le backtester :
- stop-loss fixe, take-profit et stop suiveur (trailing stop), verifies a chaque cycle ;
- dimensionnement de position par volatilite (cible de volatilite annuelle).

`_Trader` = boucle commune (signal -> sizing -> overlay risque -> rebalancement -> attente).
`LiveTrader` (live_trader.py) en herite pour le trading reel.
"""
import json
import time
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import ccxt

import config
from .stats import StatsRecorder, market_features

_TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
               "1h": 3600, "4h": 14400, "1d": 86400}


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def describe_error(exc) -> dict:
    """
    Classe une exception levee pendant un cycle pour des logs lisibles et un
    backoff adapte. ATTENTION a l'ordre : DDoSProtection herite de NetworkError
    dans ccxt, donc on le teste en premier.
    """
    detail = f"{type(exc).__name__}: {str(exc)[:300]}"
    low = str(exc).lower()
    refus_words = ("rate limit", "too many requests", "lockout", "ddos")
    if isinstance(exc, ccxt.DDoSProtection) or any(w in low for w in refus_words):
        category = "kraken_refus"
    elif isinstance(exc, ccxt.RequestTimeout):
        category = "timeout"
    elif isinstance(exc, ccxt.ExchangeNotAvailable):
        category = "indisponible"
    elif isinstance(exc, ccxt.NetworkError):
        category = "reseau"
    else:
        category = "autre"
    return {"category": category, "detail": detail}


def backoff_seconds(consec_failures, category, poll_seconds) -> int:
    """
    Attente avant la prochaine tentative apres `consec_failures` echecs de suite
    (n >= 1). Repart vite au 1er echec, espace ensuite, plafonne. Si Kraken nous
    repousse (rate limit / lockout) on attend plus longtemps.
    """
    if category == "kraken_refus":
        return min(60 * 2 ** (consec_failures - 1), 900)
    return min(30 * 2 ** (consec_failures - 1), 600)


class _Trader:
    def __init__(self, exchange, strategy, symbol=None, timeframe=None,
                 stop_loss=None, take_profit=None, trailing_stop=None,
                 position_sizing=None, target_vol=None, vol_window=None,
                 max_fraction=None, poll_seconds=None, stats_file=None,
                 log_file=None):
        self.exchange = exchange
        self.strategy = strategy
        self.log_file = Path(log_file) if log_file else None
        self.consec_failures = 0
        self.recorder = StatsRecorder(stats_file) if stats_file else None
        self.symbol = symbol or config.DEFAULT_SYMBOL
        self.timeframe = timeframe or config.DEFAULT_TIMEFRAME
        self.stop_loss = config.STOP_LOSS if stop_loss is None else stop_loss
        self.take_profit = config.TAKE_PROFIT if take_profit is None else take_profit
        self.trailing_stop = config.TRAILING_STOP if trailing_stop is None else trailing_stop
        self.position_sizing = config.POSITION_SIZING if position_sizing is None else position_sizing
        self.target_vol = config.TARGET_VOL if target_vol is None else target_vol
        self.vol_window = config.VOL_WINDOW if vol_window is None else vol_window
        self.max_fraction = config.MAX_FRACTION if max_fraction is None else max_fraction
        self.poll_seconds = poll_seconds or _TF_SECONDS.get(self.timeframe, 3600)
        self.base = self.symbol.split("/")[0]
        self.quote = self.symbol.split("/")[1]

    def _trace(self, msg):
        """Trace lisible (console + fichier si log_file). N'ecrit le fichier
        que lazy, a la 1ere trace ; un echec d'ecriture ne casse jamais le run."""
        line = f"[{now()}] {msg}"
        print(line)
        if self.log_file:
            try:
                with self.log_file.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass  # ne JAMAIS crasher le run a cause du log

    def _closed_candles(self) -> pd.DataFrame:
        """Bougies CLOTUREES (la derniere, en cours de formation, est retiree)."""
        df = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=200)
        return df.iloc[:-1]

    def _latest_signal(self, df) -> int:
        """Signal sur la derniere bougie cloturee."""
        return int(self.strategy.generate_signals(df).iloc[-1])

    def _entry_fraction(self, df) -> float:
        """
        Fraction du capital a investir A L'ENTREE, identique au backtester
        (_size_series) : on cible une volatilite annuelle constante a partir de la
        volatilite recente de la derniere bougie cloturee.
        - 1.0 si le sizing est desactive (tout-ou-rien) ;
        - 0.0 si la volatilite n'est pas estimable (debut de serie).
        Plafonnee a MAX_FRACTION (pas de levier par defaut).
        """
        if self.position_sizing != "vol":
            return 1.0
        rets = df["close"].pct_change()
        sec = pd.Series(df.index).diff().dt.total_seconds().median()
        ppy = (365 * 24 * 3600) / sec if sec and not pd.isna(sec) else 365.0
        vol = (rets.rolling(self.vol_window).std() * np.sqrt(ppy)).iloc[-1]
        if not vol or pd.isna(vol) or vol <= 0:
            return 0.0
        return float(min(self.target_vol / vol, self.max_fraction))

    def _risk_overlay(self, desired: int, price: float):
        """
        Stop-loss / trailing stop / take-profit peuvent forcer une sortie, par-dessus
        le signal. Coherent avec le backtester : le stop le plus serre prime, et le
        stop l'emporte sur l'objectif (prudence).
        """
        ep = self._entry_price()
        if not (self._is_invested(price) and ep):
            return desired, None

        # Suit le plus haut atteint depuis l'entree (pour le trailing stop).
        if self.trailing_stop:
            self._set_peak(max(self._peak() or ep, price))

        stops = []
        if self.stop_loss:
            stops.append((ep * (1 - self.stop_loss), "STOP-LOSS"))
        if self.trailing_stop:
            stops.append(((self._peak() or ep) * (1 - self.trailing_stop), "TRAILING-STOP"))
        if stops:
            stop_p, reason = max(stops, key=lambda s: s[0])  # le plus serre prime
            if price <= stop_p:
                return 0, reason
        if self.take_profit and price >= ep * (1 + self.take_profit):
            return 0, "TAKE-PROFIT"
        return desired, None

    def run(self):
        risk = []
        if self.stop_loss:
            risk.append(f"stop -{self.stop_loss*100:g}%")
        if self.trailing_stop:
            risk.append(f"trailing {self.trailing_stop*100:g}%")
        if self.take_profit:
            risk.append(f"objectif +{self.take_profit*100:g}%")
        if self.position_sizing == "vol":
            risk.append(f"sizing vol cible {self.target_vol*100:g}%")
        risk_txt = (" | " + ", ".join(risk)) if risk else ""
        self._trace(f"Demarrage : {self.strategy} sur {self.symbol} ({self.timeframe}){risk_txt}")
        self._trace(f"Re-evaluation toutes les {self.poll_seconds} s. Ctrl+C pour arreter.")
        while True:
            try:
                df = self._closed_candles()
                signal = self._latest_signal(df)
                fraction = self._entry_fraction(df)
                price = self.exchange.fetch_price(self.symbol)
                desired, reason = self._risk_overlay(signal, price)
                trade = self._rebalance(desired, price, reason, fraction)
                self._log_status(price)
                if self.recorder:
                    self._record_cycle(df, price, signal, desired, fraction, reason, trade)
                if self.consec_failures:
                    self._trace(f"Reconnexion OK apres {self.consec_failures} echec(s) consecutif(s).")
                    self.consec_failures = 0
            except KeyboardInterrupt:
                self._trace("Arret demande. A bientot.")
                break
            except Exception as e:
                self.consec_failures += 1
                info = describe_error(e)
                wait = backoff_seconds(self.consec_failures, info["category"], self.poll_seconds)
                self._trace(f"Erreur cycle [{info['category']}] ({self.consec_failures}e echec consecutif) : "
                            f"{info['detail']} -> nouvelle tentative dans {wait}s")
                time.sleep(wait)
                continue
            time.sleep(self.poll_seconds)

    def _record_cycle(self, df, price, signal, desired, fraction, reason, trade):
        """Assemble et enregistre une ligne de stats pour le cycle courant."""
        cash = self._cash()
        units = self._units()
        equity = cash + units * price
        ts = dt.datetime.now()
        row = {
            "time": now(), "symbol": self.symbol, "timeframe": self.timeframe,
            "price": price,
            "hour": ts.hour, "weekday": ts.weekday(),
            "signal": signal, "desired": desired, "fraction": fraction,
            "peak": self._peak(), "cash": cash, "units": units, "equity": equity,
            "exposure": (units * price / equity) if equity else 0.0,
            "action": (trade or {}).get("action", "hold"),
            "reason": reason,
            "pnl": (trade or {}).get("pnl", ""),
            "fee_paid": (trade or {}).get("fee_paid", ""),
            "hold_secs": (trade or {}).get("hold_secs", ""),
        }
        row.update(market_features(df))
        self.recorder.record(row)

    # Implementes par les sous-classes
    def _rebalance(self, desired, price, reason, fraction): raise NotImplementedError
    def _log_status(self, price): raise NotImplementedError
    def _is_invested(self, price): raise NotImplementedError
    def _entry_price(self): raise NotImplementedError
    def _peak(self): raise NotImplementedError
    def _set_peak(self, value): raise NotImplementedError
    def _cash(self): raise NotImplementedError
    def _units(self): raise NotImplementedError


class PaperTrader(_Trader):
    def __init__(self, exchange, strategy, symbol=None, timeframe=None,
                 stop_loss=None, take_profit=None, trailing_stop=None,
                 position_sizing=None, target_vol=None, vol_window=None,
                 max_fraction=None, initial_capital=None, fee=None,
                 poll_seconds=None, state_file="paper_state.json",
                 stats_file="paper_stats.csv", log_file="paper_trades.log"):
        super().__init__(exchange, strategy, symbol, timeframe, stop_loss,
                         take_profit, trailing_stop, position_sizing, target_vol,
                         vol_window, max_fraction, poll_seconds, stats_file,
                         log_file=log_file)
        self.fee = config.FEE if fee is None else fee
        self.state_file = Path(state_file)
        init_cap = config.INITIAL_CAPITAL if initial_capital is None else initial_capital
        self.state = self._load_state(init_cap)

    def _load_state(self, init_cap):
        if self.state_file.exists():
            print(f"[{now()}] Reprise de l'etat depuis {self.state_file}")
            state = json.loads(self.state_file.read_text())
            state.setdefault("peak", None)  # retro-compat des anciens etats sans 'peak'
            state.setdefault("entry_ts", None)    # retro-compat (suivi pnl/duree par trade)
            state.setdefault("entry_cost", None)
            return state
        return {"cash": init_cap, "base_amount": 0.0, "invested": False,
                "entry_price": None, "peak": None, "entry_ts": None,
                "entry_cost": None, "trades": []}

    def _save(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def _is_invested(self, price): return self.state["invested"]
    def _entry_price(self): return self.state.get("entry_price")
    def _peak(self): return self.state.get("peak")
    def _cash(self): return self.state["cash"]
    def _units(self): return self.state["base_amount"]

    def _set_peak(self, value):
        if self.state.get("peak") != value:
            self.state["peak"] = value
            self._save()

    def _rebalance(self, desired, price, reason, fraction=1.0):
        s = self.state
        if desired == 1 and not s["invested"]:
            spend = s["cash"] * fraction
            if fraction <= 0 or spend <= 0:
                return None  # rien a investir (sizing nul / pas de cash)
            s["base_amount"] = spend * (1 - self.fee) / price
            s["cash"] -= spend
            s["invested"] = True
            s["entry_price"] = price
            s["peak"] = price
            s["entry_ts"] = time.time()
            s["entry_cost"] = spend  # cout total engage (cash sorti), frais inclus
            s["trades"].append({"time": now(), "side": "buy", "price": price})
            extra = f" (sizing {fraction*100:.0f}%)" if self.position_sizing == "vol" else ""
            print(f"[{now()}] >>> ACHAT (simule) : {s['base_amount']:.5f} {self.base} @ {price:.2f}{extra}")
            self._save()
            return {"action": "buy", "pnl": 0.0, "fee_paid": spend * self.fee, "hold_secs": ""}
        elif desired == 0 and s["invested"]:
            amount = s["base_amount"]
            proceeds = amount * price * (1 - self.fee)  # cash recu, net de frais
            fee_sell = amount * price * self.fee
            pnl = proceeds - (s.get("entry_cost") or 0.0)
            hold = time.time() - (s.get("entry_ts") or time.time())
            s["cash"] += proceeds
            tag = f" [{reason}]" if reason else ""
            print(f"[{now()}] >>> VENTE (simule){tag} : {amount:.5f} {self.base} @ {price:.2f}")
            s["base_amount"] = 0.0
            s["invested"] = False
            s["entry_price"] = None
            s["peak"] = None
            s["entry_ts"] = None
            s["entry_cost"] = None
            s["trades"].append({"time": now(), "side": "sell", "price": price, "reason": reason})
            self._save()
            return {"action": "sell", "pnl": pnl, "fee_paid": fee_sell,
                    "hold_secs": hold, "reason": reason}
        return None

    def _log_status(self, price):
        s = self.state
        value = s["cash"] + s["base_amount"] * price
        etat = "INVESTI" if s["invested"] else "CASH"
        print(f"[{now()}] {etat:7s} | prix {price:.2f} | portefeuille {value:,.2f} {self.quote} "
              f"| {len(s['trades'])} ordres")
