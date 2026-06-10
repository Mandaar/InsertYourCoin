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
import pandas as pd

from .backtester import Backtester
from .strategies import STRATEGIES
from .stats_metrics import probabilistic_sharpe_ratio, deflated_sharpe_ratio

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


def _make_bt(fee, stop_loss, take_profit, trailing_stop, position_sizing, target_vol,
             slippage=None):
    # B6) slippage propage tel quel : None => le Backtester prend config.SLIPPAGE,
    # donc optimize / walk_forward heritent automatiquement du cout d'execution.
    return Backtester(fee=fee, stop_loss=stop_loss, take_profit=take_profit,
                      trailing_stop=trailing_stop, position_sizing=position_sizing,
                      target_vol=target_vol, slippage=slippage)


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
             position_sizing=None, target_vol=None, slippage=None):
    name = strategy_name.lower()
    strat_cls = STRATEGIES[name]
    grid, is_valid = DEFAULT_GRIDS[name]
    split = int(len(df) * train_frac)
    train, test = df.iloc[:split], df.iloc[split:]
    bt = _make_bt(fee, stop_loss, take_profit, trailing_stop, position_sizing, target_vol,
                  slippage)

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
                 position_sizing=None, target_vol=None, fixed_params=None, slippage=None):
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
    bt = _make_bt(fee, stop_loss, take_profit, trailing_stop, position_sizing, target_vol,
                  slippage)

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

    # B12+) Sharpe deflate / probabiliste : penalise le nb d'essais et la
    # non-normalite. n_trials = nb de combinaisons de la grille en mode OPTIMISE
    # (chaque fenetre re-choisit la meilleure parmi autant de combos => data-mining),
    # = 1 en mode FIGE (aucune selection). n_obs = total des bougies hors-echantillon.
    n_trials = 1 if fixed_params else sum(1 for _ in _combos(grid, is_valid))
    n_obs = _oos_n_obs(df, train_initial, fold, n_windows, n)
    psr, dsr = _walk_forward_sharpe_deflated(df, windows, n_obs, n_trials)

    return {
        "strategy": name, "metric": metric, "windows": windows,
        "oos_total_return": compounded - 1,
        "avg_window_metric": avg_metric,
        "pct_profitable": sum(1 for r in returns if r > 0) / len(returns),
        "fixed_params": fixed_params,
        "n_trials": n_trials,
        "n_obs_oos": n_obs,
        "psr": psr,
        "dsr": dsr,
    }


def holdout_split(n, holdout_frac):
    """
    B7) Indice de coupe du holdout SACRE : les bougies [cut, n) sont RESERVEES
    a la validation finale et ne doivent JAMAIS etre vues par la recherche
    (ni optimisation, ni fenetres OOS du walk-forward).

    Fonction UNIQUE partagee par le CLI et holdout_check, pour garantir que la
    recherche et la validation finale utilisent exactement la meme frontiere.
    """
    if not (0.0 < holdout_frac < 1.0):
        raise ValueError("holdout_frac doit etre dans ]0, 1[.")
    return int(n * (1 - holdout_frac))


def holdout_check(df, holdout_frac, strategy_name, fixed_params=None, metric="sharpe",
                  fee=None, stop_loss=None, take_profit=None, trailing_stop=None,
                  position_sizing=None, target_vol=None, slippage=None):
    """
    B7) VALIDATION FINALE sur le holdout sacre : evalue la strategie UNE SEULE
    fois sur les dernieres bougies, jamais vues par la recherche.

    - Le decoupage (holdout_split) est identique a celui applique cote CLI :
      la recherche n'a JAMAIS vu [cut, n).
    - `fixed_params` fourni (recommande, anti-data-mining) : la strategie est
      evaluee telle quelle. Sinon, les parametres sont choisis par _best_on sur
      le segment de RECHERCHE uniquement (jamais sur le holdout).
    - B1) warm-up : la fenetre passee au Backtester est ETENDUE en amont du
      holdout pour amorcer les indicateurs, mais seules les bougies du holdout
      sont comptees (equity/trades/metriques).

    A ne faire qu'UNE fois par strategie : re-tester apres avoir vu le resultat
    = data-mining (le holdout ne serait plus hors-echantillon).
    """
    name = strategy_name.lower()
    strat_cls = STRATEGIES[name]
    n = len(df)
    cut = holdout_split(n, holdout_frac)
    if (n - cut) < 5:
        raise RuntimeError("Holdout trop court (< 5 bougies). Augmente --days ou --holdout.")
    bt = _make_bt(fee, stop_loss, take_profit, trailing_stop, position_sizing,
                  target_vol, slippage)
    if fixed_params:
        params = dict(fixed_params)
        optimised = False
    else:
        if cut < 30:
            raise RuntimeError("Pas assez de donnees de recherche pour optimiser "
                               "avant le holdout. Augmente --days ou utilise --fixed.")
        grid, is_valid = DEFAULT_GRIDS[name]
        research = df.iloc[:cut]
        params, _ = _best_on(bt, research, strat_cls, grid, is_valid, metric)
        if params is None:
            raise RuntimeError("Aucune combinaison valide sur le segment de recherche.")
        optimised = True
    warmup_margin = _params_warmup(params)
    t_start = max(0, cut - warmup_margin)
    ext = df.iloc[t_start:]
    m = bt.run(ext, strat_cls(**params), warmup=cut - t_start).metrics
    return {
        "strategy": name, "metric": metric, "params": params,
        "optimised_on_research": optimised,
        "holdout_period": (df.index[cut], df.index[-1]),
        "n_holdout": n - cut, "holdout_frac": holdout_frac,
        "metrics": m,
    }


def walk_forward_multi(data, strategy_name, **wf_kwargs):
    """
    Robustesse MULTI-ACTIFS : memes reglages de walk-forward appliques a chaque
    actif de `data` ({symbole: DataFrame}), puis synthese agregee.

    Un edge ROBUSTE doit tenir sur la MAJORITE des actifs (1 positif sur 3 =
    pas robuste). Un actif en echec est signale et ignore (pattern _load_basket),
    jamais masque.
    """
    per_symbol, errors = {}, {}
    for sym, df in data.items():
        try:
            per_symbol[sym] = walk_forward(df, strategy_name, **wf_kwargs)
        except Exception as e:  # signaler, pas masquer
            errors[sym] = str(e)
    if not per_symbol:
        raise RuntimeError("Aucun actif evaluable en walk-forward : "
                           + " ; ".join(f"{s}: {m}" for s, m in errors.items()))
    oos = [r["oos_total_return"] for r in per_symbol.values()]
    n_assets = len(per_symbol)
    n_positive = sum(1 for r in oos if r > 0)
    avg_oos = float(np.mean(oos))
    summary = {
        "n_assets": n_assets,
        "n_positive": n_positive,
        "avg_oos_return": avg_oos,
        # SOURCE DE VERITE UNIQUE de la robustesse : majorite STRICTE d'actifs
        # OOS > 0 ET moyenne OOS positive. L'affichage (format_walk_forward_multi)
        # lit ce drapeau tel quel -- jamais de re-test divergent qui ferait dire
        # au dict "robust" pendant que le texte dit "NON robuste".
        "robust": (n_positive * 2 > n_assets) and (avg_oos > 0),
    }
    return {"strategy": strategy_name.lower(), "per_symbol": per_symbol,
            "errors": errors, "summary": summary}


def _oos_n_obs(df, train_initial, fold, n_windows, n):
    """Total des bougies effectivement comptees hors-echantillon (somme des fenetres)."""
    total = 0
    for w in range(n_windows):
        test_start = train_initial + w * fold
        test_end = n if w == n_windows - 1 else test_start + fold
        total += (test_end - test_start)
    return total


def _periods_per_year(index):
    """Bougies/an a partir d'un index temporel (pour de-annualiser le Sharpe)."""
    if len(index) < 2:
        return 365.0
    sec = pd.Series(index).diff().dt.total_seconds().median()
    return (365 * 24 * 3600) / sec if sec and not np.isnan(sec) else 365.0


def _walk_forward_sharpe_deflated(df, windows, n_obs, n_trials):
    """
    PSR (proba que le vrai Sharpe > 0) et DSR (proba que le vrai Sharpe > seuil de
    data-mining pour n_trials essais), calcules sur le Sharpe MOYEN hors-echantillon.

    Le Sharpe stocke est ANNUALISE ; PSR/DSR raisonnent par observation -> on
    de-annualise (sharpe_obs = sharpe_annuel / sqrt(bougies/an)) pour rester coherent
    avec n_obs (nb de bougies). Aucune fenetre a Sharpe fini -> (NaN, NaN).
    """
    sharpes = np.array([w["metrics"]["sharpe"] for w in windows], dtype=float)
    finite = sharpes[np.isfinite(sharpes)]
    if finite.size == 0:
        return float("nan"), float("nan")
    ppy = _periods_per_year(df.index)
    sharpe_obs = float(finite.mean()) / np.sqrt(ppy)
    psr = probabilistic_sharpe_ratio(sharpe_obs, n_obs)
    dsr = deflated_sharpe_ratio(sharpe_obs, n_obs, n_trials)
    return psr, dsr


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
    ]
    out += _format_deflated_sharpe(res)
    out.append("")
    out += _verdict(res["avg_window_metric"], 1.0, res["oos_total_return"], wf=True)
    return "\n".join(out)


def _format_deflated_sharpe(res):
    """Ligne 'Sharpe deflate (PSR/DSR)' + interpretation honnete (B12+).

    PSR = proba que le vrai Sharpe OOS soit > 0 (tient compte de la taille
    d'echantillon). DSR = la meme proba mais contre le seuil de data-mining attendu
    pour `n_trials` essais : en mode optimise, plus la grille est grande, plus le DSR
    chute. Un DSR << PSR signale que l'edge apparent vient surtout du nombre d'essais.
    """
    psr = res.get("psr")
    dsr = res.get("dsr")
    n_trials = res.get("n_trials", 1)
    if psr is None or dsr is None:
        return []
    def _pct(x):
        return "n/a" if (x is None or not np.isfinite(x)) else f"{x*100:.0f} %"
    lines = [
        f"Sharpe deflate (PSR/DSR)         : PSR {_pct(psr)} / DSR {_pct(dsr)} "
        f"(essais testes : {n_trials})",
    ]
    if not np.isfinite(dsr):
        lines.append("   -> Sharpe OOS non fiable (trop peu d'observations ou degenere) ; indecidable.")
    elif n_trials > 1:
        lines.append("   -> DSR = proba que l'edge soit reel APRES correction du data-mining "
                     f"({n_trials} combos testes).")
        lines.append("      DSR faible (< 50 %) = l'edge apparent vient surtout du nombre d'essais. "
                     "Figer les parametres et re-tester.")
    else:
        lines.append("   -> Parametres figes (1 essai) : DSR = PSR, pas de penalite de data-mining ici.")
    return lines


def _avg_window_sharpe(res):
    """Sharpe moyen des fenetres OOS (fenetres a Sharpe fini uniquement)."""
    vals = np.array([w["metrics"]["sharpe"] for w in res["windows"]], dtype=float)
    finite = vals[np.isfinite(vals)]
    return float(finite.mean()) if finite.size else float("nan")


def format_walk_forward_multi(res) -> str:
    def _pct(x):
        return "n/a" if (x is None or not np.isfinite(x)) else f"{x*100:.0f}%"
    out = [f"\n=== Walk-forward MULTI-ACTIFS : {res['strategy'].upper()} ===",
           "Robustesse : memes reglages appliques a chaque actif, verdict global agrege.\n",
           f"{'Actif':12s} {'OOS cumule':>11s} {'Fen. prof.':>10s} {'Sharpe moy':>10s} "
           f"{'PSR':>5s} {'DSR':>5s}"]
    out.append("-" * 60)
    for sym, r in res["per_symbol"].items():
        sh = _avg_window_sharpe(r)
        sh_s = f"{sh:.2f}" if np.isfinite(sh) else "n/a"
        out.append(f"{sym:12s} {r['oos_total_return']*100:+10.1f}% "
                   f"{r['pct_profitable']*100:9.0f}% {sh_s:>10s} "
                   f"{_pct(r.get('psr')):>5s} {_pct(r.get('dsr')):>5s}")
    out.append("-" * 60)
    for sym, msg in res["errors"].items():
        out.append(f"(ignore {sym} : {msg})")
    s = res["summary"]
    out += ["",
            f"Synthese : {s['n_assets']} actifs evalues, {s['n_positive']} avec OOS > 0 ; "
            f"OOS moyen {s['avg_oos_return']*100:+.1f} %"]
    if s["robust"]:
        out += ["✓  Verdict global : l'edge tient sur la majorite des actifs.",
                "   Encourageant, mais jamais une garantie pour le futur."]
    else:
        out += ["⚠️  Verdict global : edge NON robuste -- il ne tient pas sur la majorite",
                "   des actifs (ou la moyenne OOS est negative). Un seul actif positif",
                "   peut etre du hasard. Ne pas trader en l'etat."]
    return "\n".join(out)


def format_holdout(res) -> str:
    m = res["metrics"]
    bp = ", ".join(f"{k}={v}" for k, v in res["params"].items())
    src = ("optimises sur la RECHERCHE uniquement, jamais sur le holdout"
           if res["optimised_on_research"]
           else "FIGES, aucune optimisation")
    out = [
        "",
        "=" * 72,
        f"=== VALIDATION FINALE sur holdout : {res['strategy'].upper()} ===",
        "⚠️  A ne faire qu'UNE fois par strategie ; re-tester apres l'avoir vu",
        "    = data-mining (le holdout ne serait plus hors-echantillon).",
        "=" * 72,
        f"Holdout : {res['holdout_period'][0].date()} -> {res['holdout_period'][1].date()} "
        f"({res['n_holdout']} bougies, {res['holdout_frac']*100:.0f}% recents)",
        f"Parametres : {bp} ({src})",
        "",
        f"{'Rendement total':18s} : {m['total_return']*100:+.1f} %",
        f"{'Sharpe':18s} : {m['sharpe']:.2f}",
        f"{'Drawdown max':18s} : {m['max_drawdown']*100:.1f} %",
        f"{'Trades':18s} : {m['n_trades']}",
    ]
    if m["n_trades"] < MIN_TRADES:
        out.append(f"⚠️  Tres peu de trades sur le holdout (< {MIN_TRADES}) : "
                   "resultat peu significatif statistiquement.")
    out += _verdict(m[res["metric"]], 0.0, m["total_return"])
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
