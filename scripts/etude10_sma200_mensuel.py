"""
Etude #10 -- SMA 200 jours en cadence MENSUELLE (aucune fenetre, sortie terminal).

Protocole GELE dans docs/ETUDE_9_ALLOCATION.md §4.4 (recopie dans
docs/ETUDE_10_SMA200_MENSUEL.md §1) et criteres GELES dans ce meme fichier §0,
AVANT toute mesure. Ce script ne fait qu'executer ce protocole :

- donnees Binance daily (historique long), TRONQUEES a la frontiere de holdout
  GELEE (config.HOLDOUT_REFERENCES -> optimizer.holdout_start). Le holdout n'est
  jamais charge : ni --final, ni --use-holdout (meme coupe que l'etude #8) ;
- signal SMA 200 evalue UNIQUEMENT aux jours de decision mensuels, position tenue
  entre deux decisions, execution a l'ouverture de la barre suivante (shift(1) du
  moteur) ;
- ETALEMENT OBLIGATOIRE sur 4 tranches (decalage 0/7/14/21 jours du jour de
  decision, cf. etude #9 §4.2 point 2 : sans etalement, jusqu'a 220 bps de CAGR
  sont du bruit de calendrier) ;
- comparateurs sur EXACTEMENT les memes fenetres : buy & hold net de frais (« ne
  rien faire », le comparateur de M22) et TSMOM 365 (comparateur de l'etude #5) ;
- rendement = compose par fenetre (chiffre officiel walk_forward) ; drawdown /
  Sharpe = courbe OOS CONTINUE (methode de l'etude #5, dont sont tires les
  chiffres de reference geles -53.1% / -76.6%) ;
- deux regimes de frais : maker 0.40%/jambe (protocole §4.4 point 4, PRIMAIRE) et
  taker 0.80%/jambe (regime des etudes #5 et #8, continuite).

AUCUN fichier de trading/ n'est touche : la strategie mensuelle est definie ICI et
n'est PAS enregistree dans STRATEGIES.

Usage : python scripts/etude10_sma200_mensuel.py
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
VERDICT_SYMBOL = "BTC/USD"
N_WINDOWS = 4
TRAIN_FRAC = 0.5
SMA_PERIOD = 200
OFFSETS = (0, 7, 14, 21)          # GELE : etude #10 §0.4

FEE_REGIMES = [
    ("PRIMAIRE  maker 0.40%/jambe", config.FEE_MAKER, config.SLIPPAGE),
    ("CONTINUITE taker 0.80%/jambe", config.FEE_TAKER, config.SLIPPAGE),
]


# --------------------------------------------------------------------------- #
# Strategies (definies ICI -- rien n'est ajoute au registre du projet)
# --------------------------------------------------------------------------- #
class AlwaysLong(Strategy):
    """« Ne rien faire » : investi du premier au dernier jour de la fenetre.

    Passe par le MEME moteur que les autres (memes frais, meme slippage, meme
    execution a l'ouverture de t+1) -> la comparaison est a armes egales.
    """
    name = "Buy & hold"

    def generate_signals(self, df):
        return pd.Series(1, index=df.index)


def month_end_positions(index):
    """Positions (entiers) de la DERNIERE barre de chaque mois calendaire REVOLU.

    DEFAUT TROUVE PAR LES TESTS (2026-09-03) : la premiere version prenait le max
    par (annee, mois), donc la derniere barre d'un mois INCOMPLET (fin de serie ou
    fin de tranche de walk-forward) passait pour une fin de mois -- deux decisions
    a 4 jours d'ecart au lieu d'une cadence mensuelle. On exige donc qu'une barre
    SUIVANTE existe et appartienne a un autre mois : un mois n'est clos que quand
    on l'a vu se terminer. Effet mesure sur les resultats : NUL (cette barre etant
    la derniere de sa tranche, le decalage d'execution shift(1) ne l'executait
    jamais) -- verifie en rejouant l'etude avant/apres, chiffres identiques.
    """
    if len(index) < 2:
        return np.empty(0, dtype=int)
    mois = np.asarray(index.month)
    change = np.flatnonzero(mois[1:] != mois[:-1])
    return change.astype(int)


def decision_positions(index, offset_days):
    """Positions des jours de DECISION mensuels, decales de `offset_days`.

    Definition GELEE (etude #10 §0.4) : pour chaque dernier jour de mois `d`, la
    decision a lieu a la derniere barre disponible <= d + offset_days. Les
    positions sont dedupliquees et triees. Une decision dont la date cible depasse
    la fin de la serie n'existe pas (elle n'a pas encore eu lieu).

    Aucune information posterieure n'est utilisee : la position renvoyee est une
    DATE, et le signal y sera calcule sur les seules clotures <= cette date.
    """
    if len(index) == 0:
        return np.empty(0, dtype=int)
    step = pd.Timedelta(days=int(offset_days))
    out = []
    for p in month_end_positions(index):
        target = index[p] + step
        if target > index[-1]:
            continue
        pos = int(index.searchsorted(target, side="right")) - 1
        if pos >= 0:
            out.append(pos)
    return np.array(sorted(set(out)), dtype=int)


class MonthlySMA(Strategy):
    """SMA `period` jours evaluee SEULEMENT aux jours de decision mensuels.

    - au jour de decision d : investi si close[d] > SMA_period(closes <= d), sinon cash ;
    - entre deux decisions : la position precedente est TENUE, quoi qu'il arrive ;
    - avant la premiere decision (ou SMA non amorcee) : flat.
    Le decalage d'execution (ouverture de d+1) est applique par le moteur, pas ici.
    """

    def __init__(self, period: int = SMA_PERIOD, offset_days: int = 0):
        self.period = int(period)
        self.offset_days = int(offset_days)
        self.name = f"SMA{self.period}-M(+{self.offset_days}j)"
        # Amorcage DECLARE (lu par optimizer._declared_warmup) : la SMA (period) plus
        # deux mois, pour qu'une decision mensuelle ait deja eu lieu avant le debut du
        # segment compte. Sans cela une fenetre OOS commencerait flat par accident.
        self.warmup_bars = self.period + 62

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        sma = close.rolling(self.period).mean()
        raw = (close > sma).where(sma.notna(), False).astype(int)
        sig = pd.Series(np.nan, index=df.index, dtype=float)
        pos = decision_positions(df.index, self.offset_days)
        if len(pos):
            sig.iloc[pos] = raw.iloc[pos].astype(float).to_numpy()
        return sig.ffill().fillna(0.0).astype(int)


# --------------------------------------------------------------------------- #
# Harness de mesure
# --------------------------------------------------------------------------- #
def load_research(symbol):
    """Historique long TRONQUE avant la frontiere de holdout gelee."""
    df = fetch_long_ohlcv(symbol, "1d", since_days=4000)
    df = df.iloc[:-1]                      # B4 : derniere bougie potentiellement en formation
    start = holdout_start(symbol)
    if start is None:
        raise RuntimeError(f"{symbol} : aucun holdout declare -- refus de deviner.")
    if df.index.tz is not None and start.tzinfo is None:
        start = start.tz_localize("UTC")
    return df[df.index < start], start


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


def _margin(strat_cls, params):
    return max(_params_warmup(params), _declared_warmup(strat_cls, params))


def run_windowed(df, strat_cls, params, fee, slippage):
    """Rendement OOS compose par fenetre -- le chiffre officiel du projet."""
    bt = Backtester(fee=fee, slippage=slippage)
    margin = _margin(strat_cls, params)
    compounded, wins = 1.0, []
    for s, e in windows_of(len(df)):
        t0 = max(0, s - margin)
        m = bt.run(df.iloc[t0:e], strat_cls(**params), warmup=s - t0).metrics
        compounded *= (1 + m["total_return"])
        wins.append(m)
    return {
        "ret": compounded - 1,
        "n_trades": int(sum(m["n_trades"] for m in wins)),
        "pct_profitable": sum(1 for m in wins if m["total_return"] > 0) / len(wins),
        "win_returns": [m["total_return"] for m in wins],
        "win_dd_worst": float(min(m["max_drawdown"] for m in wins)),
    }


def run_continuous(df, strat_cls, params, fee, slippage):
    """Courbe OOS CONTINUE sur l'union des fenetres -- methode de l'etude #5 pour
    le drawdown et le Sharpe (un drawdown reel peut traverser une frontiere)."""
    bt = Backtester(fee=fee, slippage=slippage)
    n = len(df)
    train_initial = int(n * TRAIN_FRAC)
    margin = _margin(strat_cls, params)
    t0 = max(0, train_initial - margin)
    res = bt.run(df.iloc[t0:], strat_cls(**params), warmup=train_initial - t0)
    bh_dd = float((res.df["buy_hold"] / res.df["buy_hold"].cummax() - 1).min())
    return {
        "sharpe": float(res.metrics["sharpe"]),
        "max_dd": float(res.metrics["max_drawdown"]),
        "ret_cont": float(res.metrics["total_return"]),
        "exposure": float(res.df["position"].mean()),
        "bh_curve_dd": bh_dd,
    }


def contender(df, strat_cls, params, fee, slippage):
    """Mesure NETTE (frais reels) + BRUTE (frais nuls) -> part des frais mesuree."""
    w = run_windowed(df, strat_cls, params, fee, slippage)
    c = run_continuous(df, strat_cls, params, fee, slippage)
    gross = run_windowed(df, strat_cls, params, 0.0, 0.0)
    out = dict(w)
    out.update(c)
    out["gross_ret"] = gross["ret"]
    out["fee_cost_pts"] = 100.0 * (gross["ret"] - w["ret"])
    return out


def fmt(label, r):
    return (f"   {label:26s} net {r['ret']*100:+9.1f}%  brut {r['gross_ret']*100:+9.1f}%  "
            f"frais {r['fee_cost_pts']:6.1f} pts  Sharpe {r['sharpe']:5.2f}  "
            f"DDmax {r['max_dd']*100:6.1f}%  expo {r['exposure']*100:3.0f}%  "
            f"ordres {r['n_trades']:3d}  fen.+ {r['pct_profitable']*100:3.0f}%")


def measure_symbol(df, fee, slippage):
    """Tous les contendants d'un actif, pour un regime de frais donne."""
    out = {}
    out["bh"] = contender(df, AlwaysLong, {}, fee, slippage)
    out["tsmom"] = contender(df, STRATEGIES["tsmom"], {"lookback": 365}, fee, slippage)
    out["tranches"] = {k: contender(df, MonthlySMA,
                                    {"period": SMA_PERIOD, "offset_days": k}, fee, slippage)
                       for k in OFFSETS}
    keys = ("ret", "gross_ret", "fee_cost_pts", "sharpe", "max_dd", "exposure",
            "n_trades", "pct_profitable")
    out["mean"] = {k: float(np.mean([out["tranches"][o][k] for o in OFFSETS])) for k in keys}
    out["spread"] = {k: float(max(out["tranches"][o][k] for o in OFFSETS)
                              - min(out["tranches"][o][k] for o in OFFSETS))
                     for k in ("ret", "max_dd", "sharpe")}
    return out


def verdict_btc(res):
    """Confrontation aux criteres GELES du §0.5 / §0.6. Ne juge QUE BTC."""
    bh, mean, tr, sp = res["bh"], res["mean"], res["tranches"], res["spread"]
    dd_red = (bh["max_dd"] - mean["max_dd"]) * -100.0   # points de DD evites (positif = mieux)
    per_tranche = {k: (bh["max_dd"] - tr[k]["max_dd"]) * -100.0 for k in OFFSETS}
    spread_dd = sp["max_dd"] * 100.0
    checks = {
        "P1 reduction DD moyenne >= 15.0 pts": (dd_red >= 15.0, f"{dd_red:+.1f} pts"),
        "P2 P1 tenu sur >= 3 tranches / 4": (
            sum(1 for v in per_tranche.values() if v >= 15.0) >= 3,
            ", ".join(f"+{k}j {v:+.1f}" for k, v in per_tranche.items())),
        "P3 reduction > dispersion inter-tranches": (
            dd_red > spread_dd, f"reduction {dd_red:+.1f} vs dispersion {spread_dd:.1f} pts"),
        "P4 >= 4 ordres OOS (moyenne)": (mean["n_trades"] >= 4.0,
                                         f"{mean['n_trades']:.1f} ordres"),
        "C1 rendement net moyen >= 0 %": (mean["ret"] >= 0.0, f"{mean['ret']*100:+.1f}%"),
        "C2 rendement net >= B&H - 20 pts": (
            mean["ret"] * 100.0 >= bh["ret"] * 100.0 - 20.0,
            f"{mean['ret']*100:+.1f}% vs B&H {bh['ret']*100:+.1f}% - 20"),
    }
    if dd_red < 8.0 or dd_red <= spread_dd or mean["ret"] < 0.0:
        label = "NE PROTEGE PAS"
    elif all(ok for ok, _ in checks.values()):
        label = "PROTEGE"
    else:
        label = "INDETERMINE"
    return label, checks, dd_red, spread_dd, per_tranche


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    args = ap.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    data = {}
    for sym in symbols:
        df, hstart = load_research(sym)
        data[sym] = df
        print(f"\n===== {sym} : {len(df)} bougies de RECHERCHE "
              f"{df.index[0].date()} -> {df.index[-1].date()} "
              f"(holdout gele a partir du {pd.Timestamp(hstart).date()}, JAMAIS charge) =====")
        for s, e in windows_of(len(df)):
            print(f"   fenetre OOS : {df.index[s].date()} -> {df.index[e-1].date()} "
                  f"({e - s} bougies)")
        d0 = decision_positions(df.index, 0)
        d21 = decision_positions(df.index, 21)
        print(f"   jours de decision : tranche +0j = {len(d0)} "
              f"(1re {df.index[d0[0]].date()}, derniere {df.index[d0[-1]].date()}) ; "
              f"tranche +21j = {len(d21)} (1re {df.index[d21[0]].date()})")

    results = {}
    for reg_label, fee, slip in FEE_REGIMES:
        print(f"\n################ REGIME DE FRAIS : {reg_label} "
              f"(+ slippage {slip*100:.2f}%/cote) ################")
        results[reg_label] = {}
        for sym in symbols:
            res = measure_symbol(data[sym], fee, slip)
            results[reg_label][sym] = res
            print(f"\n--- {sym} ---")
            print(fmt("Ne rien faire (B&H)", res["bh"]))
            print(fmt("TSMOM 365", res["tsmom"]))
            for k in OFFSETS:
                print(fmt(f"SMA200 mensuel +{k}j", res["tranches"][k]))
            m, sp = res["mean"], res["spread"]
            print(f"   {'SMA200-M MOYENNE 4 tranches':26s} net {m['ret']*100:+9.1f}%  "
                  f"brut {m['gross_ret']*100:+9.1f}%  frais {m['fee_cost_pts']:6.1f} pts  "
                  f"Sharpe {m['sharpe']:5.2f}  DDmax {m['max_dd']*100:6.1f}%  "
                  f"expo {m['exposure']*100:3.0f}%  ordres {m['n_trades']:5.1f}")
            print(f"   {'DISPERSION (max-min)':26s} rendement {sp['ret']*100:6.1f} pts  "
                  f"DD {sp['max_dd']*100:6.1f} pts  Sharpe {sp['sharpe']:5.2f}")
            print(f"   DD du B&H recalcule sur sa propre courbe (etude #5) : "
                  f"{res['bh']['bh_curve_dd']*100:.1f}%")

    # ---- verification croisee OBLIGATOIRE (etude #10 §0.9)
    print("\n--- Verification croisee : TSMOM 365 contre trading.optimizer.walk_forward "
          "(frais etudes #5/#8 : taker 0.80% + 5 bps) ---")
    ref = {"BTC/USD": 55.9, "ETH/USD": 98.2, "SOL/USD": 264.6}
    ok_all = True
    for sym in symbols:
        wf = walk_forward(data[sym], "tsmom", n_windows=N_WINDOWS, train_frac=TRAIN_FRAC,
                          fixed_params={"lookback": 365})
        mine = results["CONTINUITE taker 0.80%/jambe"][sym]["tsmom"]["ret"]
        ecart = abs(wf["oos_total_return"] - mine) * 100.0
        ecart_ref = abs(mine * 100.0 - ref.get(sym, float("nan")))
        ok_all &= (ecart < 1e-6) and (ecart_ref < 0.05)
        print(f"   {sym:9s} walk_forward {wf['oos_total_return']*100:+8.1f}%  "
              f"script {mine*100:+8.1f}%  etude #5 {ref.get(sym, float('nan')):+8.1f}%  "
              f"ecart moteur {ecart:.4f} pts  ecart etude #5 {ecart_ref:.4f} pts")
    print(f"   -> harness {'VALIDE' if ok_all else 'INVALIDE -- aucun verdict ne vaut'}")

    # ---- verdict, sur BTC uniquement (protocole §4.4 point 1)
    if VERDICT_SYMBOL in symbols:
        for reg_label, _, _ in FEE_REGIMES:
            res = results[reg_label][VERDICT_SYMBOL]
            label, checks, dd_red, spread_dd, per_tranche = verdict_btc(res)
            print(f"\n=== CRITERES GELES -- {VERDICT_SYMBOL} -- {reg_label} ===")
            for name, (ok, val) in checks.items():
                print(f"   [{'OK  ' if ok else 'ECHEC'}] {name:42s} : {val}")
            print(f"   Drawdown : B&H {res['bh']['max_dd']*100:.1f}%  "
                  f"SMA200-M moyenne {res['mean']['max_dd']*100:.1f}%  "
                  f"-> {dd_red:+.1f} pts evites, dispersion {spread_dd:.1f} pts")
            print(f"   >>> VERDICT PROTECTION ({reg_label}) : {label}")
            axe = ("BAT le B&H" if res["mean"]["ret"] > res["bh"]["ret"]
                   else "NE BAT PAS le B&H")
            print(f"   >>> Axe rendement (critere etude #9 §4.4 pt 8) : {axe} "
                  f"({res['mean']['ret']*100:+.1f}% contre {res['bh']['ret']*100:+.1f}%)")

    # ---- robustesse, hors verdict
    print("\n=== ROBUSTESSE (HORS VERDICT -- ETH et SOL, protocole §4.4 point 1) ===")
    for reg_label, _, _ in FEE_REGIMES:
        for sym in symbols:
            if sym == VERDICT_SYMBOL:
                continue
            res = results[reg_label][sym]
            dd_red = (res["bh"]["max_dd"] - res["mean"]["max_dd"]) * -100.0
            print(f"   {reg_label:28s} {sym:9s} SMA200-M {res['mean']['ret']*100:+8.1f}% "
                  f"vs B&H {res['bh']['ret']*100:+9.1f}%  |  DD {res['mean']['max_dd']*100:6.1f}% "
                  f"vs {res['bh']['max_dd']*100:6.1f}%  ({dd_red:+.1f} pts)  "
                  f"dispersion DD {res['spread']['max_dd']*100:.1f} pts")


if __name__ == "__main__":
    main()
