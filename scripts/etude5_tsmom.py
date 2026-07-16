#!/usr/bin/env python3
"""
Etude #5 -- TSMOM vs Buy & Hold, sur les MEMES fenetres hors-echantillon.

But (caveat n.1 de l'etude #4) : l'etude #4 a montre TSMOM 365j positif 3/3 actifs
en walk-forward, mais SANS comparaison Buy & Hold. Ce script tranche honnetement :
TSMOM bat-il le B&H, ou ne fait-il que le suivre avec moins de casse ?

Methode (aucun fichier de code existant n'est modifie -- import seul) :
- Donnees : source Binance (historique long), timeframe 1d, holdout 20% RESERVE
  (jamais vu, comme le CLI). On travaille sur le segment de RECHERCHE uniquement.
- Comparaison sur les MEMES fenetres OOS que le walk-forward :
  * TSMOM OOS = walk_forward(..., fixed_params).oos_total_return (chiffre officiel,
    identique a l'affichage CLI et a l'etude #4).
  * B&H OOS (fenetres) = compose des `buy_hold_return` PAR FENETRE que le backtester
    calcule deja (rebase sur le 1er close de chaque segment compte) -> apples-to-apples,
    exactement les memes bornes de fenetres, meme traitement.
- Qualite de risque (Sharpe, max drawdown, volatilite) : mesuree sur la courbe d'equite
  OOS CONTINUE (un seul backtest sur l'union des fenetres [train_initial, n)),
  pour TSMOM (res.metrics) ET pour le B&H (res.df["buy_hold"], memes formules moteur).
  La courbe continue est plus honnete pour le drawdown (un DD reel peut traverser une
  frontiere de fenetre).

Frais/slippage = ceux de config.py (0.80% + 5 bps), NON modifies. Aucun --final.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows : sortie UTF-8 (meme garde-fou que main.py, cf. SQA BUG-004).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import numpy as np

import config
from trading.history import fetch_long_ohlcv
from trading.optimizer import walk_forward, holdout_split, _params_warmup
from trading.backtester import Backtester
from trading.strategies import TSMomentum, SMACrossover

HOLDOUT_FRAC = 0.20
N_WINDOWS = 4
TRAIN_FRAC = 0.5
TIMEFRAME = "1d"
SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]

# Reglages a tester (params FIGES, jamais optimises -- anti-data-mining).
# On documente la SENSIBILITE (180/365/540) ; on ne SELECTIONNE pas le meilleur.
TSMOM_LOOKBACKS = [180, 365, 540]
SMA_PARAMS = {"fast": 50, "slow": 200}


def periods_per_year(index):
    """Bougies/an (identique a Backtester._periods_per_year)."""
    import pandas as pd
    if len(index) < 2:
        return 365.0
    sec = pd.Series(index).diff().dt.total_seconds().median()
    return (365 * 24 * 3600) / sec if sec and not np.isnan(sec) else 365.0


def equity_curve_metrics(equity, ppy):
    """
    Metriques d'une courbe d'equite PURE (buy & hold : toujours investi, 0 trade).
    Replique EXACTEMENT les formules de Backtester._metrics pour rester comparable :
      - rets = equity.pct_change().fillna(0)  (std ddof=1 pandas)
      - sharpe = mean/std * sqrt(ppy)
      - vol_annual = std * sqrt(ppy)
      - max_dd = min(equity/equity.cummax() - 1)
    Le B&H n'est jamais 'degenere' (exposition continue) -> pas de garde NaN.
    """
    rets = equity.pct_change().fillna(0)
    std = rets.std()
    sharpe = float(rets.mean() / std * np.sqrt(ppy)) if std > 0 else float("nan")
    vol_annual = float(std * np.sqrt(ppy))
    dd = float((equity / equity.cummax() - 1).min())
    total = float(equity.iloc[-1] / equity.iloc[0] - 1)
    return {"total_return": total, "sharpe": sharpe,
            "max_drawdown": dd, "volatility": vol_annual}


def load_research(symbol):
    """
    Segment de RECHERCHE identique au CLI :
    - historique long Binance (since_days=None = tout le listing),
    - exclusion B4 de la derniere bougie (potentiellement en formation),
    - holdout 20% recent RETIRE (holdout_split, meme frontiere que le CLI).
    Le holdout n'est JAMAIS touche ici (jamais de --final).
    """
    full = fetch_long_ohlcv(symbol, TIMEFRAME, since_days=None)
    df = full.iloc[:-1] if len(full) > 1 else full          # B4
    cut = holdout_split(len(df), HOLDOUT_FRAC)              # B7 holdout sacre
    return df.iloc[:cut], (df.index[cut], df.index[-1]), (len(df) - cut)


def continuous_oos(research, params, strat):
    """
    Un SEUL backtest sur l'union des fenetres OOS = [train_initial, n_research).
    train_initial identique a walk_forward (int(n*TRAIN_FRAC)). warmup amont via
    _params_warmup (meme logique B5 que l'optimizer). Renvoie (metriques strategie,
    metriques B&H, (date_debut, date_fin)) sur EXACTEMENT le meme span.
    """
    n = len(research)
    train_initial = int(n * TRAIN_FRAC)
    warmup_margin = _params_warmup(params)
    t_start = max(0, train_initial - warmup_margin)
    ext = research.iloc[t_start:]
    res = Backtester().run(ext, strat, warmup=train_initial - t_start)
    ppy = periods_per_year(res.df.index)
    strat_m = res.metrics
    bh_m = equity_curve_metrics(res.df["buy_hold"], ppy)
    return strat_m, bh_m, (res.df.index[0], res.df.index[-1]), len(res.df)


def bh_windowed_from_wf(wf):
    """
    Rendement B&H compose sur les MEMES fenetres que le walk-forward, en reutilisant
    le `buy_hold_return` que le backtester calcule DEJA pour chaque fenetre OOS
    (rebase sur le 1er close du segment compte). Meme traitement que oos_total_return.
    """
    comp = 1.0
    per_win = []
    for w in wf["windows"]:
        bh = w["metrics"]["buy_hold_return"]
        comp *= (1.0 + bh)
        per_win.append(bh)
    return comp - 1.0, per_win


def run_case(symbol, research, label, params, strat_factory):
    strat = strat_factory()
    wf = walk_forward(research, _name_of(strat),
                      n_windows=N_WINDOWS, train_frac=TRAIN_FRAC,
                      fixed_params=params)
    ts_oos = wf["oos_total_return"]
    bh_oos_win, bh_per_win = bh_windowed_from_wf(wf)
    strat_m, bh_m, span, n_oos = continuous_oos(research, params, strat_factory())
    return {
        "symbol": symbol,
        "label": label,
        "params": params,
        "oos_span": [str(span[0].date()), str(span[1].date())],
        "n_oos": n_oos,
        # Rendement OOS -- fenetres identiques (walk-forward)
        "ts_oos_return_windowed": ts_oos,
        "bh_oos_return_windowed": bh_oos_win,
        "pct_profitable": wf["pct_profitable"],
        "dsr": wf.get("dsr"),
        "psr": wf.get("psr"),
        # Rendement + risque OOS -- courbe continue (memes bornes)
        "ts_return_cont": strat_m["total_return"],
        "ts_sharpe": strat_m["sharpe"],
        "ts_maxdd": strat_m["max_drawdown"],
        "ts_vol": strat_m["volatility"],
        "ts_exposure": strat_m["exposure"],
        "ts_ntrades": strat_m["n_trades"],
        "bh_return_cont": bh_m["total_return"],
        "bh_sharpe": bh_m["sharpe"],
        "bh_maxdd": bh_m["max_drawdown"],
        "bh_vol": bh_m["volatility"],
        "windows_ts": [w["metrics"]["total_return"] for w in wf["windows"]],
        "windows_bh": bh_per_win,
    }


def _name_of(strat):
    """Nom court de la strategie pour walk_forward (registre)."""
    from trading.strategies import STRATEGIES
    for k, cls in STRATEGIES.items():
        if isinstance(strat, cls):
            return k
    raise ValueError("strategie inconnue")


def fmt_pct(x):
    if x is None or not np.isfinite(x):
        return "   n/a"
    return f"{x*100:+6.1f}%"


def fmt_ratio(x):
    if x is None or not np.isfinite(x):
        return "  n/a"
    return f"{x:5.2f}"


def print_case_table(rows, title):
    print(f"\n{'='*94}")
    print(f"  {title}")
    print(f"{'='*94}")
    hdr = (f"{'Actif':9s} {'Span OOS':23s} {'n':>4s} | "
           f"{'TSMOM ret':>9s} {'B&H ret':>9s} | "
           f"{'TS Shrp':>7s} {'BH Shrp':>7s} | {'TS DD':>7s} {'BH DD':>7s} | "
           f"{'%prof':>5s} {'DSR':>4s}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        span = f"{r['oos_span'][0]}->{r['oos_span'][1]}"
        print(f"{r['symbol']:9s} {span:23s} {r['n_oos']:>4d} | "
              f"{fmt_pct(r['ts_oos_return_windowed']):>9s} "
              f"{fmt_pct(r['bh_oos_return_windowed']):>9s} | "
              f"{fmt_ratio(r['ts_sharpe']):>7s} {fmt_ratio(r['bh_sharpe']):>7s} | "
              f"{fmt_pct(r['ts_maxdd']):>7s} {fmt_pct(r['bh_maxdd']):>7s} | "
              f"{r['pct_profitable']*100:4.0f}% "
              f"{(r['dsr']*100 if r['dsr'] is not None and np.isfinite(r['dsr']) else float('nan')):3.0f}%")
    print("-" * len(hdr))
    print("Note: TSMOM ret / B&H ret = rendement OOS compose sur les MEMES fenetres "
          "(walk-forward).\n      Sharpe / DD = courbe OOS continue (memes bornes). "
          "Frais 0.80% + slippage 5 bps.")


def main():
    print("ETUDE #5 -- TSMOM vs Buy & Hold sur les memes fenetres OOS")
    print(f"Frais config : taker {config.FEE*100:.2f}% | slippage {config.SLIPPAGE*1e4:.0f} bps "
          f"| holdout {HOLDOUT_FRAC*100:.0f}% (INTACT, jamais --final)")

    # Charge chaque actif une fois (cache disque reutilise).
    research = {}
    holdout_info = {}
    for s in SYMBOLS:
        rdf, span_ho, n_ho = load_research(s)
        research[s] = rdf
        holdout_info[s] = (span_ho, n_ho)
        print(f"  {s:9s} recherche={len(rdf)} bougies "
              f"(du {rdf.index[0].date()} au {rdf.index[-1].date()}) | "
              f"holdout reserve={n_ho} ({span_ho[0].date()}->{span_ho[1].date()})")

    all_results = {}

    # 1+2) TSMOM lookback 180 / 365 / 540 (365 = principal, 180/540 = sensibilite)
    for lb in TSMOM_LOOKBACKS:
        rows = []
        for s in SYMBOLS:
            rows.append(run_case(s, research[s], f"TSMOM({lb}j)",
                                 {"lookback": lb},
                                 lambda lb=lb: TSMomentum(lookback=lb)))
        all_results[f"tsmom_{lb}"] = rows
        print_case_table(rows, f"TSMOM lookback={lb}j (FIGE) vs Buy & Hold -- OOS")

    # 3) SMA 50/200 temoin
    rows = []
    for s in SYMBOLS:
        rows.append(run_case(s, research[s], "SMA(50/200)",
                             dict(SMA_PARAMS),
                             lambda: SMACrossover(fast=50, slow=200)))
    all_results["sma_50_200"] = rows
    print_case_table(rows, "SMA 50/200 (FIGE) vs Buy & Hold -- OOS (temoin)")

    # Dump JSON pour la redaction du rapport (scratchpad, hors repo).
    out = os.environ.get("ETUDE5_JSON")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\n[JSON ecrit : {out}]")


if __name__ == "__main__":
    main()
