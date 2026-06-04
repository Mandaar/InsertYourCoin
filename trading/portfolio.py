"""
Backtest de portefeuille multi-actifs.

On applique la meme stratégie a chaque actif d'un panier, chacun avec sa part
du capital (equipondere par defaut), puis on additionne les courbes de capital.
On compare le portefeuille a un "buy & hold" equipondere du meme panier, et on
affiche la correlation des actifs (pour juger du vrai benefice de diversification).
"""
import numpy as np
import pandas as pd

from .backtester import Backtester
from .strategies import build_strategy


def _ppy(index):
    if len(index) < 2:
        return 365.0
    sec = pd.Series(index).diff().dt.total_seconds().median()
    return (365 * 24 * 3600) / sec if sec and not np.isnan(sec) else 365.0


def _series_metrics(equity, ppy):
    eq = equity.dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = len(eq) / ppy
    annual = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
    rets = eq.pct_change().fillna(0)
    std = rets.std()
    downside = rets[rets < 0].std()
    dd = (eq / eq.cummax() - 1).min()
    return {
        "total_return": total,
        "annual_return": annual,
        "volatility": std * np.sqrt(ppy),
        "sharpe": (rets.mean() / std * np.sqrt(ppy)) if std > 0 else 0.0,
        "sortino": (rets.mean() / downside * np.sqrt(ppy)) if downside and downside > 0 else 0.0,
        "max_drawdown": dd,
    }


def backtest_portfolio(data: dict, strategy_name, weights=None,
                       initial_capital=10_000.0, **bt_kwargs):
    symbols = list(data.keys())
    n = len(symbols)
    weights = weights or [1.0 / n] * n

    per_asset, equities, bh_equities = {}, {}, {}
    for sym, w in zip(symbols, weights):
        bt = Backtester(initial_capital=initial_capital * w, **bt_kwargs)
        res = bt.run(data[sym], build_strategy(strategy_name))
        per_asset[sym] = res.metrics
        equities[sym] = res.df["equity"]
        bh_equities[sym] = res.df["buy_hold"]

    port_eq = pd.DataFrame(equities).dropna().sum(axis=1)
    port_bh = pd.DataFrame(bh_equities).dropna().sum(axis=1)
    ppy = _ppy(port_eq.index)

    corr = pd.DataFrame({s: data[s]["close"].pct_change() for s in symbols}).dropna().corr()

    return {
        "symbols": symbols,
        "weights": weights,
        "strategy": build_strategy(strategy_name).name,
        "per_asset": per_asset,
        "portfolio": _series_metrics(port_eq, ppy),
        "portfolio_bh": _series_metrics(port_bh, ppy),
        "correlation": corr,
        "equity": port_eq,
        "initial_capital": initial_capital,
        "final_equity": float(port_eq.iloc[-1]),
    }


def format_portfolio(res) -> str:
    out = [f"\n=== Portefeuille : {res['strategy']} ===",
           f"Panier : {', '.join(res['symbols'])} (equipondere)",
           f"Periode : {res['equity'].index[0].date()} -> {res['equity'].index[-1].date()}",
           ""]
    head = f"{'Actif':10s} | {'Rendement':>10s} | {'Sharpe':>6s} | {'Vol':>5s} | {'DD max':>7s}"
    out += [head, "-" * len(head)]
    for s in res["symbols"]:
        m = res["per_asset"][s]
        out.append(f"{s:10s} | {m['total_return']*100:+9.1f}% | {m['sharpe']:6.2f} | "
                   f"{m['volatility']*100:4.0f}% | {m['max_drawdown']*100:6.1f}%")
    out.append("-" * len(head))
    p, b = res["portfolio"], res["portfolio_bh"]
    out += [
        f"{'PORTEFEUILLE':10s} | {p['total_return']*100:+9.1f}% | {p['sharpe']:6.2f} | "
        f"{p['volatility']*100:4.0f}% | {p['max_drawdown']*100:6.1f}%",
        f"{'(buy&hold)':10s} | {b['total_return']*100:+9.1f}% | {b['sharpe']:6.2f} | "
        f"{b['volatility']*100:4.0f}% | {b['max_drawdown']*100:6.1f}%",
        "",
        "Correlation des rendements (1 = bougent ensemble) :",
        res["correlation"].round(2).to_string(),
        "",
    ]
    avg = res["correlation"].values[np.triu_indices(len(res["correlation"]), 1)].mean()
    out.append(f"Correlation moyenne : {avg:.2f}")
    if avg > 0.7:
        out.append("→ Actifs tres correles : diversification limitee (tout chute ensemble"
                    " en cas de krach). Lisse les bords, ne protege pas du risque systemique crypto.")
    else:
        out.append("→ Correlation moderee : la diversification apporte un vrai lissage ici.")
    return "\n".join(out)
