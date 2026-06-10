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
    "tsmom": ({"lookback": [90, 180, 365]}, None),
    "rsi": ({"period": [7, 14, 21], "oversold": [20, 25, 30], "overbought": [70, 75, 80]},
            None),
    "macd": ({"fast": [8, 12, 16], "slow": [21, 26, 34], "signal": [7, 9, 12]},
             lambda p: p["fast"] < p["slow"]),
    "bollinger": ({"period": [10, 20, 30], "num_std": [1.5, 2.0, 2.5]}, None),
}

# B1) Marge de warm-up (en bougies) ajoutee EN AMONT de chaque fenetre OOS pour
# amorcer les indicateurs avant de compter le segment hors-echantillon. Doit
# couvrir la plus longue periode de toutes les grilles (SMA slow=200) avec une
# marge confortable pour que l'EMA/RSI/MACD soient bien stabilises (un EMA n'est
# jamais "warm" a 100% mais converge ; 250 bougies de marge >> tout periode de
# grille). Choix : 250.
WARMUP = 250


def _max_period(grid):
    """Plus grande periode entiere apparaissant dans une grille (borne du warm-up reel)."""
    longest = 0
    for vals in grid.values():
        for v in vals:
            if isinstance(v, int) and v > longest:
                longest = v
    return longest


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


# B2) Nb minimum de trades sur la fenetre pour qu'une combinaison soit ELIGIBLE
# a la selection. Une combo "flat" (0 trade) ou quasi-flat (1-2 trades chanceux)
# ne doit pas remporter l'argmax : sa metrique n'est pas statistiquement fiable.
MIN_TRADES = 5


def _best_on(bt, df, strat_cls, grid, is_valid, metric, warmup=0):
    """
    Retourne (best_params, best_metrics).

    B2) Selection en deux temps, du plus fiable au moins fiable :
      1. combos ELIGIBLES : metrique FINIE (ni NaN ni inf) ET `n_trades >= MIN_TRADES`.
      2. si aucune eligible : on retombe sur la combo "moins pire" a metrique finie
         (meme avec peu de trades) pour ne jamais renvoyer None silencieusement ;
         l'info `degenerate=True` est portee dans les metriques retournees.
    Une combo a metrique non-finie (NaN/inf) n'est JAMAIS selectionnee.
    """
    best, best_m, best_metrics = None, -float("inf"), None          # eligible
    fb, fb_m, fb_metrics = None, -float("inf"), None                # fallback fini
    for params in _combos(grid, is_valid):
        try:
            m = bt.run(df, strat_cls(**params), warmup=warmup).metrics
        except Exception:
            continue
        val = m[metric]
        if not np.isfinite(val):
            continue
        if m["n_trades"] >= MIN_TRADES:
            if val > best_m:
                best, best_m, best_metrics = params, val, m
        if val > fb_m:
            fb, fb_m, fb_metrics = params, val, m

    if best is not None:
        return best, best_metrics
    if fb is not None:
        fb_metrics = dict(fb_metrics, degenerate=True)
        return fb, fb_metrics
    return None, None


def optimize(df, strategy_name, train_frac=0.6, metric="sharpe", fee=None,
             stop_loss=None, take_profit=None, trailing_stop=None,
             position_sizing=None, target_vol=None):
    name = strategy_name.lower()
    strat_cls = STRATEGIES[name]
    grid, is_valid = DEFAULT_GRIDS[name]
    split = int(len(df) * train_frac)
    train, test = df.iloc[:split], df.iloc[split:]
    bt = _make_bt(fee, stop_loss, take_profit, trailing_stop, position_sizing, target_vol)

    # Selection sur le TRAIN (in-sample). Pas de warm-up amont possible : il n'y a
    # pas de donnee avant l'indice 0 ; les premieres ~slow bougies sont degenerees,
    # ce qui est inherent a l'in-sample (memes conditions pour toutes les combos).
    best_params, train_m = _best_on(bt, train, strat_cls, grid, is_valid, metric)
    if best_params is None:
        raise RuntimeError("Aucune combinaison valide.")

    # B1) le TEST (hors-echantillon) est backteste sur une fenetre ETENDUE incluant
    # le warm-up amont, mais seul [split, fin) est compte.
    t_start = max(0, split - WARMUP)
    test_ext = df.iloc[t_start:]
    test_m = bt.run(test_ext, strat_cls(**best_params), warmup=split - t_start).metrics
    return {
        "strategy": name, "metric": metric, "best_params": best_params,
        "train": train_m, "test": test_m,
        "full": bt.run(df, strat_cls(**best_params)).metrics,
        "train_period": (train.index[0], train.index[-1]),
        "test_period": (test.index[0], test.index[-1]),
    }


def _params_warmup(params):
    """Marge de warm-up suffisante pour des parametres FIGES donnes.

    B5) en mode parametres figes, la strategie peut avoir une periode plus longue
    que la plus longue grille (ex. TSMOM lookback=365 > WARMUP=250). On etend le
    warm-up pour ne pas amputer artificiellement le signal fige sur les fenetres
    OOS courtes (memes garanties B1 que pour le mode optimise).
    """
    longest = 0
    for v in params.values():
        if isinstance(v, int) and v > longest:
            longest = v
    return max(WARMUP, longest + 50)


def walk_forward(df, strategy_name, n_windows=4, train_frac=0.5, metric="sharpe",
                 fee=None, stop_loss=None, take_profit=None, trailing_stop=None,
                 position_sizing=None, target_vol=None, fixed_params=None):
    """
    Walk-forward hors-echantillon.

    B5) `fixed_params` (dict) : mode PARAMETRES FIGES. Si fourni, on N'OPTIMISE
    PAS (jamais d'appel a `_best_on`) ; on instancie la strategie avec ces
    parametres et on l'applique telle quelle sur CHAQUE fenetre OOS. Cela separe
    l'edge d'un bot a parametres fixes (50/200, lookback 12 mois) de l'overfit
    introduit par l'optimisation de la grille (data-mining, cf. AUDIT B5). Le
    warm-up amont (B1) et le comptage OOS restent identiques.
    """
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

    warmup_margin = _params_warmup(fixed_params) if fixed_params else WARMUP

    windows = []
    compounded = 1.0
    for w in range(n_windows):
        test_start = train_initial + w * fold
        test_end = n if w == n_windows - 1 else test_start + fold
        if fixed_params:
            # B5) aucune optimisation : params figes appliques tels quels.
            params = dict(fixed_params)
        else:
            # Selection sur tout le passe disponible (deja warm depuis l'indice 0).
            train = df.iloc[:test_start]
            params, _ = _best_on(bt, train, strat_cls, grid, is_valid, metric)
        # B1) OOS [test_start, test_end) backteste avec warm-up amont, mais seul
        # ce segment est compte (equity/trades/metriques).
        t_start = max(0, test_start - warmup_margin)
        test_ext = df.iloc[t_start:test_end]
        tm = bt.run(test_ext, strat_cls(**params), warmup=test_start - t_start).metrics
        compounded *= (1 + tm["total_return"])
        test = df.iloc[test_start:test_end]
        windows.append({"period": (test.index[0], test.index[-1]),
                        "params": params, "metrics": tm})

    returns = [win["metrics"]["total_return"] for win in windows]
    # B2) avg_window_metric ignore les fenetres degenerees (NaN/inf) au lieu de
    # se faire contaminer (np.mean d'un NaN = NaN ; un inf domine tout).
    metric_vals = np.array([w["metrics"][metric] for w in windows], dtype=float)
    finite = metric_vals[np.isfinite(metric_vals)]
    avg_metric = float(finite.mean()) if finite.size else float("nan")
    return {
        "strategy": name, "metric": metric, "windows": windows,
        "oos_total_return": compounded - 1,
        "avg_window_metric": avg_metric,
        "pct_profitable": sum(1 for r in returns if r > 0) / len(returns),
        "fixed_params": fixed_params,
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
    fixed = res.get("fixed_params")
    if fixed:
        bp = ", ".join(f"{k}={v}" for k, v in fixed.items())
        mode = f"parametres FIGES ({bp}) -- aucune optimisation (anti-data-mining)"
    else:
        mode = "parametres OPTIMISES sur chaque train (re-selection de la grille)"
    out = [f"\n=== Walk-forward : {res['strategy'].upper()} (critere : {res['metric']}) ===",
           f"Mode : {mode}",
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
    # B2) une metrique non-finie (NaN) = trop peu de trades fiables -> on ne
    # conclut PAS un succes par defaut (nan < 0 vaut False en Python).
    if test_metric is None or not np.isfinite(test_metric):
        return [f"⚠️  Verdict : metrique {label} non fiable (trop peu de trades ou cas",
                "   degenere) -> indecidable. Ne pas se fier a ce chiffre."]
    if test_return < 0 or test_metric < 0:
        return [f"⚠️  Verdict : performance {label} negative -> stratégie peu fiable",
                "   telle quelle. Ne pas trader."]
    if test_metric < 0.5 * max(train_metric, 1e-9):
        return [f"⚠️  Verdict : forte chute de performance {label} -> sur-apprentissage",
                "   probable. A prendre avec beaucoup de prudence."]
    return [f"✓  Verdict : la performance tient (en partie) {label}.",
            "   Encourageant, mais jamais une garantie pour le futur."]
