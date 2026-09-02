"""
Etude #8 -- le juge de la strategie PREDICTIVE (aucune fenetre, sortie terminal).

Protocole GELE dans docs/ETUDE_8_PREDICTIF.md §0 AVANT toute mesure. Ce script ne
fait qu'executer ce protocole :

- donnees Binance daily (historique long), TRONQUEES a la frontiere de holdout
  GELEE (config.HOLDOUT_REFERENCES -> optimizer.holdout_start). Le holdout n'est
  jamais charge : ni --final, ni --use-holdout, et la troncature est plus stricte
  qu'un `--holdout 20` calcule sur l'historique du jour (qui, l'historique ayant
  grandi depuis l'etude #5, mordrait de quelques dizaines de bougies dans la zone
  reservee) ;
- walk-forward 4 fenetres, train_frac 0.5, parametres FIGES (aucune optimisation,
  donc aucun data-mining de grille) ;
- sur EXACTEMENT les memes fenetres : buy & hold net de frais (« ne rien faire »,
  le comparateur de M22) et TSMOM 365 (comparateur de l'etude #5) ;
- chaque contendant est mesure DEUX fois : avec frais reels et avec frais nuls ->
  la part des frais est une SOUSTRACTION mesuree, pas une estimation.

Usage : python scripts/etude8_predictif.py [--horizons 5,10,20]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config                                     # noqa: E402
from trading.backtester import Backtester         # noqa: E402
from trading.history import fetch_long_ohlcv      # noqa: E402
from trading.optimizer import (walk_forward, holdout_start,   # noqa: E402
                               _declared_warmup, _params_warmup)
from trading.strategies import Strategy, STRATEGIES  # noqa: E402

SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]
N_WINDOWS = 4
TRAIN_FRAC = 0.5


class AlwaysLong(Strategy):
    """« Ne rien faire » : investi du premier au dernier jour de la fenetre.

    Passe par le MEME moteur que les autres (memes frais, meme slippage, meme
    execution a l'ouverture de t+1) -> la comparaison est a armes egales.
    """
    name = "Buy & hold"

    def generate_signals(self, df):
        return pd.Series(1, index=df.index)


def load_research(symbol):
    """Historique long TRONQUE avant la frontiere de holdout gelee."""
    df = fetch_long_ohlcv(symbol, "1d", since_days=4000)
    df = df.iloc[:-1]                      # B4 : derniere bougie potentiellement en formation
    start = holdout_start(symbol)
    if start is None:
        raise RuntimeError(f"{symbol} : aucun holdout declare -- refus de deviner.")
    if df.index.tz is not None and start.tzinfo is None:
        start = start.tz_localize("UTC")
    research = df[df.index < start]
    return research, start


def windows_of(n):
    """Bornes d'index des fenetres OOS -- MEME arithmetique que optimizer.walk_forward."""
    train_initial = int(n * TRAIN_FRAC)
    fold = (n - train_initial) // N_WINDOWS
    out = []
    for w in range(N_WINDOWS):
        s = train_initial + w * fold
        e = n if w == N_WINDOWS - 1 else s + fold
        out.append((s, e))
    return out


def run_fixed(df, strat_cls, params, fee, slippage):
    """Walk-forward « maison » a parametres figes, identique a walk_forward mais
    utilisable aussi pour une strategie NON enregistree (le buy & hold)."""
    n = len(df)
    margin = max(_params_warmup(params), _declared_warmup(strat_cls, params))
    bt = Backtester(fee=fee, slippage=slippage)
    compounded, wins = 1.0, []
    for s, e in windows_of(n):
        t0 = max(0, s - margin)
        m = bt.run(df.iloc[t0:e], strat_cls(**params), warmup=s - t0).metrics
        compounded *= (1 + m["total_return"])
        wins.append({"period": (df.index[s], df.index[e - 1]), "metrics": m})
    sh = np.array([w["metrics"]["sharpe"] for w in wins], dtype=float)
    sh = sh[np.isfinite(sh)]
    return {
        "oos_total_return": compounded - 1,
        "windows": wins,
        "sharpe_mean": float(sh.mean()) if sh.size else float("nan"),
        "max_dd": float(min(w["metrics"]["max_drawdown"] for w in wins)),
        "n_trades": int(sum(w["metrics"]["n_trades"] for w in wins)),
        "pct_profitable": sum(1 for w in wins if w["metrics"]["total_return"] > 0) / len(wins),
    }


def contender(df, strat_cls, params):
    """Mesure NETTE (frais reels) + mesure BRUTE (frais nuls) -> part des frais."""
    net = run_fixed(df, strat_cls, params, fee=None, slippage=None)
    gross = run_fixed(df, strat_cls, params, fee=0.0, slippage=0.0)
    net["gross_return"] = gross["oos_total_return"]
    net["fee_cost_pts"] = 100.0 * (gross["oos_total_return"] - net["oos_total_return"])
    return net


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", default="5,10,20",
                    help="horizons du modele predictif (config gelee : 5,10,20)")
    args = ap.parse_args()
    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]

    print(f"Frais actifs : FEE={config.FEE*100:.2f}%/cote, slippage="
          f"{config.SLIPPAGE*100:.2f}%/cote  (aller-retour ~"
          f"{(1/(1-config.FEE)**2 - 1)*100:.2f}% hors slippage)")
    rows = []
    for sym in SYMBOLS:
        df, hstart = load_research(sym)
        print(f"\n===== {sym} : {len(df)} bougies de RECHERCHE "
              f"{df.index[0].date()} -> {df.index[-1].date()} "
              f"(holdout gele a partir du {pd.Timestamp(hstart).date()}, JAMAIS charge) =====")
        for s, e in windows_of(len(df)):
            print(f"   fenetre OOS : {df.index[s].date()} -> {df.index[e-1].date()} "
                  f"({e - s} bougies)")

        essais = [("Buy & hold (ne rien faire)", AlwaysLong, {}),
                  ("TSMOM 365", STRATEGIES["tsmom"], {"lookback": 365})]
        essais += [(f"Predictif H={h}j", STRATEGIES["predictive"], {"horizon": h})
                   for h in horizons]

        for label, cls, params in essais:
            r = contender(df, cls, params)
            rows.append({"symbol": sym, "label": label, **r})
            print(f"   {label:28s} net {r['oos_total_return']*100:+9.1f}%  "
                  f"brut {r['gross_return']*100:+9.1f}%  frais {r['fee_cost_pts']:6.1f} pts  "
                  f"Sharpe {r['sharpe_mean']:5.2f}  DDmax {r['max_dd']*100:6.1f}%  "
                  f"ordres {r['n_trades']:3d}  fen.+ {r['pct_profitable']*100:3.0f}%")

    # ---- verification croisee : le walk_forward DU PROJET doit donner la meme chose
    print("\n--- Verification croisee avec trading.optimizer.walk_forward (memes reglages) ---")
    for sym in SYMBOLS:
        df, _ = load_research(sym)
        for name, params in (("predictive", {"horizon": horizons[0]}),
                             ("tsmom", {"lookback": 365})):
            res = walk_forward(df, name, n_windows=N_WINDOWS, train_frac=TRAIN_FRAC,
                               fixed_params=params)
            mine = [r for r in rows if r["symbol"] == sym
                    and r["label"].startswith("Predictif" if name == "predictive" else "TSMOM")][0]
            ecart = abs(res["oos_total_return"] - mine["oos_total_return"])
            print(f"   {sym:9s} {name:11s} walk_forward {res['oos_total_return']*100:+8.1f}%  "
                  f"script {mine['oos_total_return']*100:+8.1f}%  ecart {ecart*100:.4f} pts")

    # ---- synthese : moyennes par contendant
    print("\n=== SYNTHESE (moyenne des 3 actifs, rendement cumule OOS net) ===")
    labels = []
    for r in rows:
        if r["label"] not in labels:
            labels.append(r["label"])
    for lab in labels:
        vals = [r["oos_total_return"] for r in rows if r["label"] == lab]
        shs = [r["sharpe_mean"] for r in rows if r["label"] == lab]
        pos = sum(1 for v in vals if v > 0)
        print(f"   {lab:28s} moyenne {np.mean(vals)*100:+9.1f}%  "
              f"actifs positifs {pos}/{len(vals)}  Sharpe moyen {np.nanmean(shs):5.2f}")

    # detail par fenetre (trades) pour le critere S5/E5
    print("\n=== Ordres par fenetre (critere S5/E5) ===")
    for r in rows:
        per_win = [w["metrics"]["n_trades"] for w in r["windows"]]
        print(f"   {r['symbol']:9s} {r['label']:28s} {per_win}")


if __name__ == "__main__":
    main()
