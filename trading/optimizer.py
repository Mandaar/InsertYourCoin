"""
Optimisation des parametres d'une stratégie, AVEC validation honnete.

Deux outils :
- optimize()      : separation simple train / test (in-sample vs out-of-sample).
- walk_forward()  : optimisation GLISSANTE. On re-optimise periodiquement sur le
                    passe, puis on trade la periode suivante (jamais vue), et on
                    avance. C'est ce qui se rapproche le plus de la realite d'un
                    bot qu'on re-regle de temps en temps. Le verdict porte sur la
                    performance cumulee HORS-ECHANTILLON.
"""
import itertools

import numpy as np

from .backtester import Backtester
from .strategies import STRATEGIES

DEFAULT_GRIDS = {
    "sma": ({"fast": [10, 20, 30, 50], "slow": [50, 100, 150, 200]},
            lambda p: p["fast"] < p["slow"]),
    "rsi": ({"period": [7, 14, 21], "oversold": [20, 25, 30], "overbought": [70, 75, 80]},
            None),
    "macd": ({"fast": [8, 12, 16], "slow": [21, 26, 34], "signal": [7, 9, 12]},
             lambda p: p["fast"] < p["slow"]),
    "bollinger": ({"period": [10, 20, 30], "num_std": [1.5, 2.0, 2.5]}, None),
}


def _combos(grid, is_valid):
    keys = list(grid)
    for values in itertools.product(*[grid[k] for k in keys]):
        params = dict(zip(keys, values))
        if is_valid is None or is_valid(params):
            yield params


def _make_bt(fee, stop_loss, take_profit, trailing_stop, position_sizing, target_vol):
    return Backtester(fee=fee, stop_loss=stop_loss, take_profit=take_profit,
                      trailing_stop=trailing_stop, position_sizing=position_sizing,
                      target_vol=target_vol)


def _best_on(bt, df, strat_cls, grid, is_valid, metric):
    best, best_m, best_metrics = None, -float("inf"), None
    for params in _combos(grid, is_valid):
        try:
            m = bt.run(df, strat_cls(**params)).metrics
        except Exception:
            continue
        if m[metric] > best_m:
            best, best_m, best_metrics = params, m[metric], m
    return best, best_metrics


def optimize(df, strategy_name, train_frac=0.6, metric="sharpe", fee=None,
             stop_loss=None, take_profit=None, trailing_stop=None,
             position_sizing=None, target_vol=None):
    name = strategy_name.lower()
    strat_cls = STRATEGIES[name]
    grid, is_valid = DEFAULT_GRIDS[name]
    split = int(len(df) * train_frac)
    train, test = df.iloc[:split], df.iloc[split:]
    bt = _make_bt(fee, stop_loss, take_profit, trailing_stop, position_sizing, target_vol)

    best_params, train_m = _best_on(bt, train, strat_cls, grid, is_valid, metric)
    if best_params is None:
        raise RuntimeError("Aucune combinaison valide.")
    return {
        "strategy": name, "metric": metric, "best_params": best_params,
        "train": train_m, "test": bt.run(test, strat_cls(**best_params)).metrics,
        "full": bt.run(df, strat_cls(**best_params)).metrics,
        "train_period": (train.index[0], train.index[-1]),
        "test_period": (test.index[0], test.index[-1]),
    }


def walk_forward(df, strategy_name, n_windows=4, train_frac=0.5, metric="sharpe",
                 fee=None, stop_loss=None, take_profit=None, trailing_stop=None,
                 position_sizing=None, target_vol=None):
    name = strategy_name.lower()
    strat_cls = STRATEGIES[name]
    grid, is_valid = DEFAULT_GRIDS[name]
    n = len(df)
    train_initial = int(n * train_frac)
    if train_initial < 30 or (n - train_initial) < n_windows * 5:
        raise RuntimeError("Pas assez de donnees pour ce walk-forward. "
                           "Augmente l'historique (--days) ou reduis --windows.")
    fold = (n - train_initial) // n_windows
    bt = _make_bt(fee, stop_loss, take_profit, trailing_stop, position_sizing, target_vol)

    windows = []
    compounded = 1.0
    for w in range(n_windows):
        test_start = train_initial + w * fold
        test_end = n if w == n_windows - 1 else test_start + fold
        train = df.iloc[:test_start]
        test = df.iloc[test_start:test_end]
        best_params, _ = _best_on(bt, train, strat_cls, grid, is_valid, metric)
        tm = bt.run(test, strat_cls(**best_params)).metrics
        compounded *= (1 + tm["total_return"])
        windows.append({"period": (test.index[0], test.index[-1]),
                        "params": best_params, "metrics": tm})

    returns = [win["metrics"]["total_return"] for win in windows]
    return {
        "strategy": name, "metric": metric, "windows": windows,
        "oos_total_return": compounded - 1,
        "avg_window_metric": float(np.mean([w["metrics"][metric] for w in windows])),
        "pct_profitable": sum(1 for r in returns if r > 0) / len(returns),
    }


# ---------------------------------------------------------------------- #
def format_report(res) -> str:
    bp = ", ".join(f"{k}={v}" for k, v in res["best_params"].items())
    t, te, mtr = res["train"], res["test"], res["metric"]
    out = [
        f"\n=== Optimisation : {res['strategy'].upper()} (critere : {mtr}) ===",
        f"Train : {res['train_period'][0].date()} -> {res['train_period'][1].date()}",
        f"Test  : {res['test_period'][0].date()} -> {res['test_period'][1].date()}",
        "",
        f"Meilleurs parametres (sur le TRAIN) : {bp}",
        "",
        f"{'':22s} {'TRAIN (in-sample)':>18s} {'TEST (hors-ech.)':>18s}",
        f"{mtr.capitalize():22s} {t[mtr]:18.2f} {te[mtr]:18.2f}",
        f"{'Rendement total':22s} {t['total_return']*100:17.1f}% {te['total_return']*100:17.1f}%",
        f"{'Drawdown max':22s} {t['max_drawdown']*100:17.1f}% {te['max_drawdown']*100:17.1f}%",
        f"{'Profit factor':22s} {t['profit_factor']:18.2f} {te['profit_factor']:18.2f}",
        "",
    ]
    out += _verdict(te[mtr], t[mtr], te["total_return"])
    return "\n".join(out)


def format_walk_forward(res) -> str:
    out = [f"\n=== Walk-forward : {res['strategy'].upper()} (critere : {res['metric']}) ===",
           f"{len(res['windows'])} fenetres hors-echantillon enchainees\n",
           f"{'Fenetre (hors-ech.)':28s} {'Parametres':22s} {'Rendement':>10s} {'Sharpe':>7s}"]
    out.append("-" * 70)
    for w in res["windows"]:
        per = f"{w['period'][0].date()}->{w['period'][1].date()}"
        bp = ",".join(f"{k}={v}" for k, v in w["params"].items())
        m = w["metrics"]
        out.append(f"{per:28s} {bp[:22]:22s} {m['total_return']*100:+9.1f}% {m['sharpe']:7.2f}")
    out.append("-" * 70)
    out += [
        "",
        f"Rendement cumule HORS-ECHANTILLON : {res['oos_total_return']*100:+.1f} %",
        f"Fenetres profitables             : {res['pct_profitable']*100:.0f} %",
        f"Critere moyen ({res['metric']})              : {res['avg_window_metric']:.2f}",
        "",
    ]
    out += _verdict(res["avg_window_metric"], 1.0, res["oos_total_return"], wf=True)
    return "\n".join(out)


def _verdict(test_metric, train_metric, test_return, wf=False):
    label = "cumulee hors-echantillon" if wf else "hors-echantillon"
    if test_return < 0 or test_metric < 0:
        return [f"⚠️  Verdict : performance {label} negative -> stratégie peu fiable",
                "   telle quelle. Ne pas trader."]
    if test_metric < 0.5 * max(train_metric, 1e-9):
        return [f"⚠️  Verdict : forte chute de performance {label} -> sur-apprentissage",
                "   probable. A prendre avec beaucoup de prudence."]
    return [f"✓  Verdict : la performance tient (en partie) {label}.",
            "   Encourageant, mais jamais une garantie pour le futur."]
