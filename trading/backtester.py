"""
Moteur de backtest event-driven (bougie par bougie).

Gere :
- Stop-loss fixe, take-profit, et stop suiveur (trailing stop).
- Dimensionnement de position : tout-ou-rien, ou cible de volatilite ("vol").

Regles d'execution (realistes) :
- Decision a la cloture de t, executee a l'OUVERTURE de t+1 (pas de lookahead).
- Stops / objectif verifies en intra-bougie (high/low).
- Si plusieurs stops sont actifs, le plus serre (le plus haut) prime ; si stop ET
  objectif sont touches dans la meme bougie, le STOP prime (prudence).
- Apres un stop/objectif, pas de re-entree tant que le signal n'est pas retombe
  a 0 puis remonte a 1 (evite les aller-retours en boucle).
- Frais preleves a chaque ordre. Slippage (B6) applique au prix d'execution :
  ACHAT au prix*(1+slippage), VENTE au prix*(1-slippage), EN PLUS des frais.
  Les prix `entry_price`/`exit_price` enregistres dans les trades restent les prix
  de marche NOMINAUX (lisibilite) ; le slippage est integre au cash et au pnl reels.
  slippage=0 reproduit l'ancien comportement.
"""
import numpy as np
import pandas as pd

import config


class BacktestResult:
    def __init__(self, df, trades, metrics, strategy_name, risk):
        self.df = df
        self.trades = trades
        self.metrics = metrics
        self.strategy_name = strategy_name
        self.risk = risk  # dict: stop_loss, take_profit, trailing_stop, position_sizing

    def summary(self) -> str:
        m = self.metrics
        r = self.risk
        lines = [f"\n=== Backtest : {self.strategy_name} ==="]
        lines.append(f"Periode              : {self.df.index[0].date()} -> {self.df.index[-1].date()}")
        rk = []
        if r.get("stop_loss"):
            rk.append(f"stop -{r['stop_loss']*100:g}%")
        if r.get("trailing_stop"):
            rk.append(f"trailing {r['trailing_stop']*100:g}%")
        if r.get("take_profit"):
            rk.append(f"objectif +{r['take_profit']*100:g}%")
        if rk:
            lines.append(f"Gestion du risque    : {', '.join(rk)}")
        if r.get("position_sizing") == "vol":
            lines.append(f"Dimensionnement      : cible de volatilite {r['target_vol']*100:g}%")
        lines += [
            f"Capital initial      : {m['initial_capital']:,.0f} $",
            f"Capital final        : {m['final_equity']:,.0f} $",
            f"Rendement total      : {m['total_return']*100:+.1f} %",
            f"Rendement annualise  : {m['annual_return']*100:+.1f} %",
            f"Buy & Hold (compar.) : {m['buy_hold_return']*100:+.1f} %",
            f"Ratio de Sharpe      : {m['sharpe']:.2f}",
            f"Ratio de Sortino     : {m['sortino']:.2f}",
            f"Ratio de Calmar      : {m['calmar']:.2f}",
            f"Drawdown max         : {m['max_drawdown']*100:.1f} %",
            f"Volatilite annuelle  : {m['volatility']*100:.1f} %",
            f"Profit factor        : {m['profit_factor']:.2f}",
            f"Nb de trades         : {m['n_trades']}",
            f"Taux de reussite     : {m['win_rate']*100:.0f} %",
            f"Gain moyen / trade   : {m['avg_trade']*100:+.2f} %",
            f"Temps investi        : {m['exposure']*100:.0f} %",
            "",
        ]
        return "\n".join(lines)


class Backtester:
    def __init__(self, fee=None, initial_capital=None, stop_loss=None, take_profit=None,
                 trailing_stop=None, position_sizing=None, target_vol=None,
                 vol_window=None, max_fraction=None, slippage=None):
        self.fee = config.FEE if fee is None else fee
        # B6) slippage = cout d'execution defavorable, applique au PRIX d'execution
        # (achat plus cher, vente moins chere) EN PLUS des frais. slippage=0 reproduit
        # exactement l'ancien comportement (resultats optimistes d'avant).
        self.slippage = config.SLIPPAGE if slippage is None else slippage
        self.initial_capital = config.INITIAL_CAPITAL if initial_capital is None else initial_capital
        self.stop_loss = config.STOP_LOSS if stop_loss is None else stop_loss
        self.take_profit = config.TAKE_PROFIT if take_profit is None else take_profit
        self.trailing_stop = config.TRAILING_STOP if trailing_stop is None else trailing_stop
        self.position_sizing = config.POSITION_SIZING if position_sizing is None else position_sizing
        self.target_vol = config.TARGET_VOL if target_vol is None else target_vol
        self.vol_window = config.VOL_WINDOW if vol_window is None else vol_window
        self.max_fraction = config.MAX_FRACTION if max_fraction is None else max_fraction

    def _periods_per_year(self, df):
        if len(df) < 2:
            return 365.0
        sec = pd.Series(df.index).diff().dt.total_seconds().median()
        return (365 * 24 * 3600) / sec if sec and not np.isnan(sec) else 365.0

    def _size_series(self, df, ppy):
        """Fraction du capital a investir A L'ENTREE (1.0 par defaut)."""
        if self.position_sizing != "vol":
            return np.ones(len(df))
        rets = df["close"].pct_change()
        vol = rets.rolling(self.vol_window).std() * np.sqrt(ppy)
        frac = (self.target_vol / vol).clip(upper=self.max_fraction)
        frac = frac.shift(1).fillna(0.0).clip(lower=0.0)  # vol de la derniere bougie close
        return frac.values

    def run(self, df, strategy, warmup=0) -> BacktestResult:
        """
        `warmup` (B1) : nb de bougies de tete servant UNIQUEMENT a amorcer les
        indicateurs (warm-up SMA/EMA/RSI/...). Les signaux et l'execution sont
        calcules sur TOUT le df fourni (warm-up correct), mais l'equity, les
        trades, le buy&hold et les metriques ne comptent QU'A PARTIR de l'indice
        `warmup`. L'equity hors-echantillon redemarre au capital initial au point
        `warmup`, comme si on lancait le bot a cet instant (toute position deja
        ouverte est ignoree au demarrage du segment compte).
        """
        df = df.copy()
        ppy = self._periods_per_year(df)
        signal = strategy.generate_signals(df).astype(int)
        desired = signal.shift(1).fillna(0).astype(int).values
        size_arr = self._size_series(df, ppy)

        o, h, l, c = (df["open"].values, df["high"].values,
                      df["low"].values, df["close"].values)
        idx = df.index
        n = len(df)
        fee = self.fee
        slip = self.slippage

        cash = self.initial_capital
        units = 0.0
        in_pos = False
        blocked = False
        entry_price = entry_time = peak = None
        equity = np.empty(n)
        pos_flag = np.zeros(n)
        trades = []

        def append_trade(exit_price, exit_time, reason, closed=True):
            # B6) le pnl reflete le slippage REEL : on est entre a entry_price*(1+slip)
            # et on sort a exit_price*(1-slip). On garde les prix NOMINAUX dans le trade
            # (lisibilite), mais le rendement comptabilise le cout d'execution.
            entry_eff = entry_price * (1 + slip)
            exit_eff = exit_price * (1 - slip)
            mult = (1 - fee) ** 2 if closed else (1 - fee)
            trades.append({"entry_time": entry_time, "entry_price": entry_price,
                           "exit_time": exit_time, "exit_price": exit_price,
                           "pnl": (exit_eff / entry_eff) * mult - 1, "reason": reason})

        for i in range(n):
            # B1) au point `warmup`, on (re)demarre le segment compte : capital
            # initial frais, aucune position heritee (le warm-up n'a servi qu'a
            # amorcer les indicateurs, pas a porter du capital).
            if i == warmup and warmup > 0:
                cash = self.initial_capital
                units = 0.0
                in_pos = False
                blocked = False
                entry_price = entry_time = peak = None
                trades = []

            # A) action sur signal, a l'ouverture
            if desired[i] == 0:
                blocked = False
            if desired[i] == 1 and not in_pos and not blocked:
                frac = size_arr[i]
                if frac > 0:
                    spend = cash * frac
                    # B6) achat au prix d'execution defavorable : o[i]*(1+slip).
                    units = spend * (1 - fee) / (o[i] * (1 + slip))
                    cash -= spend
                    in_pos = True
                    entry_price = o[i]            # prix NOMINAL (le slippage est dans units)
                    entry_time = idx[i]
                    peak = o[i]
            elif desired[i] == 0 and in_pos:
                # B6) vente au prix d'execution defavorable : o[i]*(1-slip).
                cash += units * o[i] * (1 - slip) * (1 - fee)
                append_trade(o[i], idx[i], "signal")
                units = 0.0
                in_pos = False

            # B) stops / objectif en intra-bougie
            if in_pos and (self.stop_loss or self.take_profit or self.trailing_stop):
                if self.trailing_stop:
                    peak = max(peak, h[i])
                stops = []
                if self.stop_loss:
                    stops.append((entry_price * (1 - self.stop_loss), "stop"))
                if self.trailing_stop:
                    stops.append((peak * (1 - self.trailing_stop), "trailing"))
                stop_p, stop_reason = max(stops, key=lambda s: s[0]) if stops else (None, None)
                tp_p = entry_price * (1 + self.take_profit) if self.take_profit else None

                if stop_p is not None and l[i] <= stop_p:
                    # B6) vente au prix d'execution defavorable : stop_p*(1-slip).
                    cash += units * stop_p * (1 - slip) * (1 - fee)
                    append_trade(stop_p, idx[i], stop_reason)
                    units = 0.0; in_pos = False; blocked = True
                elif tp_p is not None and h[i] >= tp_p:
                    # B6) vente au prix d'execution defavorable : tp_p*(1-slip).
                    cash += units * tp_p * (1 - slip) * (1 - fee)
                    append_trade(tp_p, idx[i], "objectif")
                    units = 0.0; in_pos = False; blocked = True

            equity[i] = cash + units * c[i]
            pos_flag[i] = 1.0 if in_pos else 0.0

        if in_pos:
            append_trade(c[-1], idx[-1], "ouvert", closed=False)

        df["equity"] = equity
        df["position"] = pos_flag

        # B1) on ne RAPPORTE que le segment hors-warm-up : equity / buy&hold /
        # trades / metriques portent uniquement sur [warmup, n). buy&hold est
        # rebase sur le 1er close du segment compte (comparaison juste).
        if warmup > 0:
            df = df.iloc[warmup:].copy()
            c = df["close"].values
            ppy = self._periods_per_year(df)
        df["buy_hold"] = self.initial_capital * c / c[0]
        df["drawdown"] = df["equity"] / df["equity"].cummax() - 1

        metrics = self._metrics(df, trades, ppy)
        risk = {"stop_loss": self.stop_loss, "take_profit": self.take_profit,
                "trailing_stop": self.trailing_stop, "position_sizing": self.position_sizing,
                "target_vol": self.target_vol}
        return BacktestResult(df, trades, metrics, str(strategy), risk)

    def _metrics(self, df, trades, ppy):
        n = len(df)
        final_equity = df["equity"].iloc[-1]
        total_return = final_equity / self.initial_capital - 1
        years = n / ppy
        annual = (final_equity / self.initial_capital) ** (1 / years) - 1 if years > 0 else 0.0

        n_trades = len(trades)
        # B2) metriques DEGENEREES -> NaN (jamais 0.0 ni inf), pour qu'elles ne
        # soient ni selectionnables (argmax) ni traitees comme "neutres". Une combo
        # "flat" (0 trade) ou tous-gagnants ne doit pas battre une vraie strategie.
        nan = float("nan")
        rets = df["equity"].pct_change().fillna(0)
        std = rets.std()
        vol_annual = std * np.sqrt(ppy)
        degenerate = n_trades == 0
        sharpe = (rets.mean() / std * np.sqrt(ppy)) if (std > 0 and not degenerate) else nan
        downside = rets[rets < 0].std()
        sortino = (rets.mean() / downside * np.sqrt(ppy)) if (downside and downside > 0 and not degenerate) else nan
        max_dd = df["drawdown"].min()
        calmar = (annual / abs(max_dd)) if (max_dd < 0 and not degenerate) else nan

        pnls = [t["pnl"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gw, gl = sum(wins), abs(sum(losses))
        # profit_factor : NaN si 0 perte (jamais inf -> non selectionnable / ne casse
        # pas les moyennes) ; NaN aussi si 0 trade.
        profit_factor = (gw / gl) if gl > 0 else nan

        return {
            "initial_capital": self.initial_capital,
            "final_equity": final_equity,
            "total_return": total_return,
            "annual_return": annual,
            "buy_hold_return": df["buy_hold"].iloc[-1] / self.initial_capital - 1,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_drawdown": max_dd,
            "volatility": vol_annual,
            "profit_factor": profit_factor,
            "n_trades": n_trades,
            "win_rate": (len(wins) / len(pnls)) if pnls else 0.0,
            "avg_trade": (sum(pnls) / len(pnls)) if pnls else 0.0,
            "exposure": df["position"].mean(),
        }
