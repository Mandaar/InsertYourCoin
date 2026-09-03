#!/usr/bin/env python3
"""
Etude #11 -- le juge du DETECTEUR DE REGIME PAR VOTE (aucune fenetre, sortie terminal).

Protocole GELE dans docs/ETUDE_11_REGIME.md §0 AVANT toute mesure. Ce script ne fait
qu'executer ce protocole :

- donnees Binance daily, TRONQUEES a la frontiere de holdout GELEE
  (config.HOLDOUT_REFERENCES -> optimizer.holdout_start). Ni --final, ni --use-holdout ;
- walk-forward 4 fenetres, train_frac 0.5, parametres FIGES (aucune optimisation) ;
- sur EXACTEMENT les memes fenetres : detention simple (B&H), TSMOM 365 seul (reference
  etude #5), CHACUN des 5 horizons seuls (dispersion), et le VOTE ;
- cible = DRAWDOWN MAX hors-echantillon sur la courbe d'equite OOS CONTINUE
  (convention etude #5 : un drawdown reel traverse les frontieres de fenetre) ;
  le drawdown par fenetre (convention etude #8) est publie en plus, il n'arbitre rien ;
- frais du verdict : MAKER 0.40%/cote (le serveur passe en ordres limite) ;
  frais de la verification croisee : TAKER 0.80%/cote (pour reproduire #5 et #8).

Usage : python scripts/etude11_regime.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # Windows : sortie UTF-8 (meme garde-fou que main.py, SQA BUG-004).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import numpy as np                                # noqa: E402
import pandas as pd                               # noqa: E402

import config                                     # noqa: E402
from trading.backtester import Backtester         # noqa: E402
from trading.history import fetch_long_ohlcv      # noqa: E402
from trading.optimizer import (walk_forward, holdout_start,   # noqa: E402
                               _declared_warmup, _params_warmup)
from trading.strategies import Strategy, STRATEGIES  # noqa: E402
from trading.regime import DEFAULT_LOOKBACKS, ensure_optimizer_grid  # noqa: E402

SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]
N_WINDOWS = 4
TRAIN_FRAC = 0.5

# Frais : le verdict est prononce en MAKER (docs/ETUDE_11_REGIME.md §0.2).
FEE_VERDICT = config.FEE_MAKER
FEE_CROSSCHECK = config.FEE          # = FEE_TAKER, celui des etudes #5 et #8
SLIP = config.SLIPPAGE

# Chiffres PUBLIES des etudes #5/#8 (regime taker), pour la verification croisee.
REF_TSMOM365_TAKER = {"BTC/USD": 0.559, "ETH/USD": 0.982, "SOL/USD": 2.646}
REF_BH_DD_TAKER = {"BTC/USD": -0.766, "ETH/USD": -0.793, "SOL/USD": -0.598}
REF_TSMOM365_DD_TAKER = {"BTC/USD": -0.531, "ETH/USD": -0.572, "SOL/USD": -0.529}

# Critere R1 gele : reduction minimale du drawdown face a la detention simple.
R1_MIN_POINTS = 5.0


class AlwaysLong(Strategy):
    """« Ne rien faire » : investi du premier au dernier jour, MEME moteur, memes frais."""
    name = "Buy & hold"

    def generate_signals(self, df):
        return pd.Series(1, index=df.index)


def load_research(symbol):
    df = fetch_long_ohlcv(symbol, "1d", since_days=4000).iloc[:-1]   # B4
    start = holdout_start(symbol)
    if start is None:
        raise RuntimeError(f"{symbol} : aucun holdout declare -- refus de deviner.")
    if df.index.tz is not None and start.tzinfo is None:
        start = start.tz_localize("UTC")
    return df[df.index < start], start


def windows_of(n):
    """Bornes des fenetres OOS -- MEME arithmetique que optimizer.walk_forward."""
    train_initial = int(n * TRAIN_FRAC)
    fold = (n - train_initial) // N_WINDOWS
    return [(train_initial + w * fold,
             n if w == N_WINDOWS - 1 else train_initial + (w + 1) * fold)
            for w in range(N_WINDOWS)]


def margin_for(strat_cls, params):
    return max(_params_warmup(params), _declared_warmup(strat_cls, params))


def periods_per_year(index):
    if len(index) < 2:
        return 365.0
    sec = pd.Series(index).diff().dt.total_seconds().median()
    return (365 * 24 * 3600) / sec if sec and not np.isnan(sec) else 365.0


def equity_metrics(equity, ppy):
    """Formules IDENTIQUES a Backtester._metrics (etude #5), pour une courbe pure."""
    rets = equity.pct_change().fillna(0)
    std = rets.std()
    return {
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "sharpe": float(rets.mean() / std * np.sqrt(ppy)) if std > 0 else float("nan"),
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
    }


def run_windows(df, strat_cls, params, fee, slippage):
    """Walk-forward a parametres figes, fenetre par fenetre (convention etude #8)."""
    margin = margin_for(strat_cls, params)
    bt = Backtester(fee=fee, slippage=slippage)
    compounded, wins = 1.0, []
    for s, e in windows_of(len(df)):
        t0 = max(0, s - margin)
        m = bt.run(df.iloc[t0:e], strat_cls(**params), warmup=s - t0).metrics
        compounded *= (1 + m["total_return"])
        wins.append(m)
    sh = np.array([w["sharpe"] for w in wins], dtype=float)
    sh = sh[np.isfinite(sh)]
    return {
        "net": compounded - 1,
        "sharpe_win": float(sh.mean()) if sh.size else float("nan"),
        "dd_win": float(min(w["max_drawdown"] for w in wins)),
        "trades": int(sum(w["n_trades"] for w in wins)),
        "pct_prof": sum(1 for w in wins if w["total_return"] > 0) / len(wins),
        "per_window": [w["total_return"] for w in wins],
    }


def run_continuous(df, strat_cls, params, fee, slippage):
    """UN backtest sur l'union des fenetres OOS [train_initial, n) -- cible du verdict."""
    n = len(df)
    train_initial = int(n * TRAIN_FRAC)
    t0 = max(0, train_initial - margin_for(strat_cls, params))
    res = Backtester(fee=fee, slippage=slippage).run(
        df.iloc[t0:], strat_cls(**params), warmup=train_initial - t0)
    ppy = periods_per_year(res.df.index)
    bh = equity_metrics(res.df["buy_hold"], ppy)       # B&H sans frais (convention #5)
    return res.metrics, bh, (res.df.index[0], res.df.index[-1])


def contender(df, label, strat_cls, params, fee):
    net = run_windows(df, strat_cls, params, fee, SLIP)
    gross = run_windows(df, strat_cls, params, 0.0, 0.0)
    cont, bh_cont, span = run_continuous(df, strat_cls, params, fee, SLIP)
    return {
        "label": label, **net,
        "gross": gross["net"],
        "fee_pts": 100.0 * (gross["net"] - net["net"]),
        "dd_cont": cont["max_drawdown"],
        "sharpe_cont": cont["sharpe"],
        "bh_dd_cont_nofee": bh_cont["max_drawdown"],
        "span": span,
    }


def essais():
    """Les 8 contendants, dans l'ordre du protocole gele."""
    out = [("Detention simple (B&H)", AlwaysLong, {}),
           ("TSMOM 365 seul (ref. #5)", STRATEGIES["tsmom"], {"lookback": 365})]
    out += [(f"TSMOM {L} seul", STRATEGIES["tsmom"], {"lookback": L})
            for L in DEFAULT_LOOKBACKS]
    out += [("VOTE 5 horizons (3/5)", STRATEGIES["regime"],
             {"lookbacks": DEFAULT_LOOKBACKS})]
    return out


def verdict(rows):
    """Applique les criteres GELES (§0.4/0.5). Les FAIL sont imprimes en premier (V3)."""
    print("\n" + "=" * 78)
    print("VERDICT CONTRE LES CRITERES GELES (docs/ETUDE_11_REGIME.md §0.4)")
    print("=" * 78)
    fails, checks = [], []
    for sym in SYMBOLS:
        by = {r["label"]: r for r in rows if r["symbol"] == sym}
        vote = by["VOTE 5 horizons (3/5)"]
        bh = by["Detention simple (B&H)"]
        t365 = by["TSMOM 365 seul (ref. #5)"]
        seuls = [by[f"TSMOM {L} seul"] for L in DEFAULT_LOOKBACKS]

        # ATTENTION AUX SIGNES : un drawdown est NEGATIF, plus il est negatif pire il
        # est. « Points evites » = de combien le creux est MOINS profond que celui de la
        # detention simple = dd_vote - dd_bh (positif quand le vote protege).
        gain = 100.0 * (vote["dd_cont"] - bh["dd_cont"])
        r1 = gain >= R1_MIN_POINTS
        pire_dd = min(s["dd_cont"] for s in seuls)                # le PLUS profond = le pire
        pire_ret = min(s["net"] for s in seuls)
        # « au moins aussi bien que le pire membre » : creux pas plus profond que le sien.
        r2 = (vote["dd_cont"] >= pire_dd) and (vote["net"] >= pire_ret)
        r3a = vote["net"] >= 0
        r3b = vote["fee_pts"] <= 2.0 * abs(t365["fee_pts"]) if t365["fee_pts"] else True
        gain_365 = 100.0 * (t365["dd_cont"] - bh["dd_cont"])
        checks.append({"sym": sym, "r1": r1, "r2": r2, "r3a": r3a, "r3b": r3b,
                       "gain": gain, "gain_365": gain_365,
                       "r1_365": gain_365 >= R1_MIN_POINTS})
        for name, ok, detail in (
            ("R1 protection", r1,
             f"DD vote {vote['dd_cont']*100:.1f}% vs B&H {bh['dd_cont']*100:.1f}% "
             f"-> {gain:+.1f} pts evites (exige >= {R1_MIN_POINTS:.0f})"),
            ("R2 robustesse", r2,
             f"DD vote {vote['dd_cont']*100:.1f}% vs pire membre {pire_dd*100:.1f}% "
             f"(exige : pas plus profond) ; "
             f"ret vote {vote['net']*100:+.1f}% vs pire membre {pire_ret*100:+.1f}%"),
            ("R3a non-destruction", r3a, f"ret net vote {vote['net']*100:+.1f}%"),
            ("R3b frais", r3b,
             f"frais vote {vote['fee_pts']:.1f} pts vs TSMOM365 {t365['fee_pts']:.1f} pts"),
        ):
            line = f"  {'PASS' if ok else 'FAIL'}  {sym:9s} {name:20s} {detail}"
            if ok:
                checks[-1].setdefault("lines", []).append(line)
            else:
                fails.append(line)

    if fails:
        print("\n--- ECHECS (imprimes en premier) ---")
        for l in fails:
            print(l)
    print("\n--- REUSSITES ---")
    for c in checks:
        for l in c.get("lines", []):
            print(l)

    n_r1 = sum(1 for c in checks if c["r1"])
    n_r2 = sum(1 for c in checks if c["r2"])
    n_r3a = sum(1 for c in checks if c["r3a"])
    n_r1_365 = sum(1 for c in checks if c["r1_365"])
    print(f"\nAgregat : R1 {n_r1}/3 · R2 {n_r2}/3 · R3a {n_r3a}/3 "
          f"| TSMOM 365 seul tient R1 sur {n_r1_365}/3")
    if n_r1 == 3 and n_r2 == 3 and n_r3a == 3:
        print("VERDICT A -- SUCCES : le vote protege ET il est robuste.")
    elif (n_r1 < 3 or n_r2 < 3) and n_r1_365 == 3:
        print("VERDICT B -- ECHEC UTILE : le vote echoue la ou 365 seul tenait "
              "-> 365 etait un accident de ce cycle. On ne construit rien dessus.")
    else:
        print("VERDICT C -- INDECIS : ca n'apporte rien de demontrable. "
              "Aucun passage au lot D.")


def main():
    ensure_optimizer_grid()
    print(f"Frais du VERDICT : maker {FEE_VERDICT*100:.2f}%/cote + slippage "
          f"{SLIP*100:.2f}%/cote | verification croisee : taker {FEE_CROSSCHECK*100:.2f}%")
    rows = []
    for sym in SYMBOLS:
        df, hstart = load_research(sym)
        print(f"\n===== {sym} : {len(df)} bougies de RECHERCHE {df.index[0].date()} -> "
              f"{df.index[-1].date()} (holdout gele a partir du "
              f"{pd.Timestamp(hstart).date()}, JAMAIS charge) =====")
        for s, e in windows_of(len(df)):
            print(f"   fenetre OOS : {df.index[s].date()} -> {df.index[e-1].date()} "
                  f"({e - s} bougies)")
        print(f"   {'contendant':26s} {'net':>9s} {'brut':>9s} {'frais':>7s} "
              f"{'DDcont':>8s} {'DDfen':>8s} {'Shcont':>7s} {'Shfen':>6s} {'ordres':>6s}")
        for label, cls, params in essais():
            r = contender(df, label, cls, params, FEE_VERDICT)
            r["symbol"] = sym
            rows.append(r)
            print(f"   {label:26s} {r['net']*100:+8.1f}% {r['gross']*100:+8.1f}% "
                  f"{r['fee_pts']:6.1f}p {r['dd_cont']*100:7.1f}% {r['dd_win']*100:7.1f}% "
                  f"{r['sharpe_cont']:7.2f} {r['sharpe_win']:6.2f} {r['trades']:6d}")

    verdict(rows)

    # ---------------- Verification croisee (critere E4) ----------------
    print("\n" + "=" * 78)
    print("VERIFICATION CROISEE -- le harness doit reproduire les etudes #5 / #8")
    print("=" * 78)
    ok = True
    for sym in SYMBOLS:
        df, _ = load_research(sym)
        # a) TSMOM 365, regime TAKER : chiffres publies etude #5 §2 / #8 §2
        mine = run_windows(df, STRATEGIES["tsmom"], {"lookback": 365},
                           FEE_CROSSCHECK, SLIP)["net"]
        wf = walk_forward(df, "tsmom", n_windows=N_WINDOWS, train_frac=TRAIN_FRAC,
                          fixed_params={"lookback": 365})["oos_total_return"]
        ref = REF_TSMOM365_TAKER[sym]
        d_wf, d_ref = abs(mine - wf) * 100, abs(mine - ref) * 100
        ok &= d_wf < 0.05 and d_ref < 0.05
        print(f"  {sym:9s} TSMOM365 taker : script {mine*100:+8.1f}%  walk_forward "
              f"{wf*100:+8.1f}%  publie #5 {ref*100:+8.1f}%  ecarts {d_wf:.4f} / {d_ref:.4f} pts")
        # b) drawdowns continus publies (etude #5 §2), memes frais taker
        c_t, c_bh, _ = run_continuous(df, STRATEGIES["tsmom"], {"lookback": 365},
                                      FEE_CROSSCHECK, SLIP)
        print(f"            DD continu : TSMOM {c_t['max_drawdown']*100:6.1f}% (publie "
              f"{REF_TSMOM365_DD_TAKER[sym]*100:6.1f}%)  B&H {c_bh['max_drawdown']*100:6.1f}% "
              f"(publie {REF_BH_DD_TAKER[sym]*100:6.1f}%)")
        # c) le VOTE : mon harness contre le walk_forward du projet (memes frais maker)
        v_mine = run_windows(df, STRATEGIES["regime"], {"lookbacks": DEFAULT_LOOKBACKS},
                             FEE_VERDICT, SLIP)["net"]
        v_wf = walk_forward(df, "regime", n_windows=N_WINDOWS, train_frac=TRAIN_FRAC,
                            fixed_params={"lookbacks": DEFAULT_LOOKBACKS},
                            fee=FEE_VERDICT, slippage=SLIP)["oos_total_return"]
        ok &= abs(v_mine - v_wf) * 100 < 0.05
        print(f"            VOTE maker  : script {v_mine*100:+8.1f}%  walk_forward "
              f"{v_wf*100:+8.1f}%  ecart {abs(v_mine - v_wf)*100:.4f} pts")
    print(f"\n  Verification croisee : {'OK' if ok else 'ECHEC -> critere E4, etude NULLE'}")


if __name__ == "__main__":
    main()
