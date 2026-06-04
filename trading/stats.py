"""
Labo de stats : accumule une ligne horodatee par cycle de paper/live trading
dans un CSV, pour etudier PLUS TARD d'eventuels comportements.

Honnetete : ce sont des stats DESCRIPTIVES. Accumuler de la donnee ne cree aucun
edge ; le walk-forward (perf hors-echantillon) reste le seul juge. La valeur de ce
fichier vient uniquement de la DUREE d'accumulation.

- `StatsRecorder` : ecrit (en append) une ligne par cycle, calcule le drawdown
  intra-session (high-water-mark de l'equity).
- `market_features(df)` : snapshot marche (indicateurs a periodes STANDARD fixes,
  independant de la strategie) sur la derniere bougie cloturee.
- `load_stats` / `summarize` / `format_summary` : lecture + synthese pour la
  commande `stats` (fonctions PURES, testables sans reseau).
"""
import csv
from pathlib import Path

import numpy as np
import pandas as pd

from . import indicators as ind

# Ordre EXACT des colonnes du CSV (ne pas reordonner : entete + lecture en dependent).
COLUMNS = [
    "time", "symbol", "timeframe", "price",
    "sma_fast", "sma_slow", "rsi", "macd", "macd_signal",
    "boll_upper", "boll_lower", "vol_recent",
    "hour", "weekday", "signal", "desired", "fraction", "peak",
    "cash", "units", "equity", "drawdown", "exposure",
    "action", "reason", "pnl", "fee_paid", "hold_secs",
]


class StatsRecorder:
    """Accumulateur CSV (lazy : ne cree le fichier qu'au premier `record`)."""

    def __init__(self, file="paper_stats.csv"):
        self.path = Path(file)
        self.equity_peak = None  # high-water-mark de l'equity, sur la session courante

    def record(self, row: dict):
        equity = row.get("equity", 0.0) or 0.0
        if self.equity_peak is None or equity > self.equity_peak:
            self.equity_peak = equity
        # Drawdown intra-session (<= 0) : ecart au plus haut atteint depuis le demarrage.
        row["drawdown"] = (equity / self.equity_peak - 1) if self.equity_peak else 0.0

        write_header = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, restval="", extrasaction="ignore")
            if write_header:
                w.writeheader()
            w.writerow(row)


def _last(series):
    """Derniere valeur finie d'une serie, sinon None (pas de crash si trop courte)."""
    if series is None or len(series) == 0:
        return None
    v = series.iloc[-1]
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
        return None
    return float(v)


def market_features(df) -> dict:
    """
    Snapshot marche sur la derniere bougie cloturee, a PERIODES STANDARD FIXES
    (independant de la strategie active) : SMA 20/50, RSI 14, MACD 12/26/9,
    Bollinger 20/2. `vol_recent` = volatilite annualisee recente (meme logique que
    `_Trader._entry_fraction`). Valeurs indefinies (serie trop courte) -> None.
    """
    close = df["close"]
    macd_line, signal_line, _ = ind.macd(close, 12, 26, 9)
    upper, _mid, lower = ind.bollinger(close, 20, 2.0)

    rets = close.pct_change(fill_method=None)
    sec = pd.Series(df.index).diff().dt.total_seconds().median()
    ppy = (365 * 24 * 3600) / sec if sec and not pd.isna(sec) else 365.0
    vol = _last(rets.rolling(20).std() * np.sqrt(ppy))

    return {
        "sma_fast": _last(ind.sma(close, 20)),
        "sma_slow": _last(ind.sma(close, 50)),
        "rsi": _last(ind.rsi(close, 14)),
        "macd": _last(macd_line),
        "macd_signal": _last(signal_line),
        "boll_upper": _last(upper),
        "boll_lower": _last(lower),
        "vol_recent": vol,
    }


def load_stats(path) -> pd.DataFrame:
    """Lit le CSV de stats. Leve une erreur claire (FR) s'il est absent."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise FileNotFoundError(
            f"Aucune donnee de stats : '{p}' est absent ou vide. "
            "Lance d'abord du paper trading pour accumuler des cycles."
        )
    return pd.read_csv(p)


def _max_drawdown(equity: pd.Series) -> float:
    """Drawdown max (<= 0) recalcule depuis la serie d'equity (high-water-mark global)."""
    eq = pd.to_numeric(equity, errors="coerce").dropna()
    if eq.empty:
        return 0.0
    peak = eq.cummax()
    return float((eq / peak - 1).min())


def _group_counts(df: pd.DataFrame, key: str) -> dict:
    """Par valeur de `key` : nb de cycles et nb de trades (buy/sell)."""
    out = {}
    if key not in df.columns:
        return out
    trades = df["action"].isin(["buy", "sell"]) if "action" in df.columns else False
    for val, sub in df.groupby(key):
        n_tr = int(sub["action"].isin(["buy", "sell"]).sum()) if "action" in sub else 0
        out[val] = {"cycles": int(len(sub)), "trades": n_tr}
    return out


def summarize(df: pd.DataFrame) -> dict:
    """Synthese descriptive depuis le CSV (source de verite)."""
    n = len(df)
    equity = pd.to_numeric(df.get("equity", pd.Series(dtype=float)), errors="coerce")
    eq = equity.dropna()
    ret = (eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) >= 2 and eq.iloc[0] else 0.0

    action = df["action"] if "action" in df.columns else pd.Series([], dtype=object)
    sells = df[action == "sell"] if "action" in df.columns else df.iloc[0:0]
    pnl = pd.to_numeric(sells.get("pnl", pd.Series(dtype=float)), errors="coerce").dropna()
    fees = pd.to_numeric(df.get("fee_paid", pd.Series(dtype=float)), errors="coerce").dropna()
    exposure = pd.to_numeric(df.get("exposure", pd.Series(dtype=float)), errors="coerce").dropna()

    n_buy = int((action == "buy").sum())
    n_sell = int((action == "sell").sum())
    wins = int((pnl > 0).sum())
    pnl_total = float(pnl.sum())
    fees_total = float(fees.sum())
    denom = abs(pnl_total) + fees_total
    return {
        "time_min": str(df["time"].iloc[0]) if n and "time" in df else None,
        "time_max": str(df["time"].iloc[-1]) if n and "time" in df else None,
        "n_cycles": n,
        "total_return": ret,
        "max_drawdown": _max_drawdown(equity),
        "n_trades": n_buy + n_sell,
        "n_buy": n_buy,
        "n_sell": n_sell,
        "win_rate": (wins / n_sell) if n_sell else 0.0,
        "pnl_total": pnl_total,
        "fees_total": fees_total,
        "fees_share": (fees_total / denom) if denom else 0.0,
        "avg_exposure": float(exposure.mean()) if len(exposure) else 0.0,
        "by_hour": _group_counts(df, "hour"),
        "by_weekday": _group_counts(df, "weekday"),
    }


_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def format_summary(d: dict) -> str:
    """Rendu texte lisible + disclaimer d'honnetete."""
    L = []
    L.append("=" * 60)
    L.append("  LABO DE STATS - synthese descriptive")
    L.append("=" * 60)
    L.append(f"Periode      : {d['time_min']} -> {d['time_max']}")
    L.append(f"Cycles       : {d['n_cycles']}")
    L.append(f"Rendement    : {d['total_return']*100:+.2f}%  (equity debut -> fin)")
    L.append(f"Drawdown max : {d['max_drawdown']*100:.2f}%")
    L.append(f"Trades       : {d['n_trades']}  ({d['n_buy']} achats / {d['n_sell']} ventes)")
    L.append(f"Reussite     : {d['win_rate']*100:.0f}%  (ventes a pnl>0)")
    L.append(f"PnL total    : {d['pnl_total']:+.2f}")
    L.append(f"Frais totaux : {d['fees_total']:.2f}  (part ~{d['fees_share']*100:.0f}% de |pnl|+frais)")
    L.append(f"Exposition   : {d['avg_exposure']*100:.0f}% en moyenne")

    if d["by_hour"]:
        L.append("\nPar heure (cycles / trades) :")
        for h in sorted(d["by_hour"], key=lambda x: int(x)):
            c = d["by_hour"][h]
            L.append(f"  {int(h):02d}h : {c['cycles']:4d} / {c['trades']}")
    if d["by_weekday"]:
        L.append("\nPar jour (cycles / trades) :")
        for wd in sorted(d["by_weekday"], key=lambda x: int(x)):
            c = d["by_weekday"][wd]
            nom = _DAYS[int(wd)] if 0 <= int(wd) < 7 else str(wd)
            L.append(f"  {nom:9s} : {c['cycles']:4d} / {c['trades']}")

    L.append("\n" + "-" * 60)
    L.append("Honnetete : stats DESCRIPTIVES, pas une preuve d'edge. Accumuler de la")
    L.append("donnee ne cree aucun profit ; seul le walk-forward (hors-echantillon)")
    L.append("juge une strategie. Sur timeframe court, les frais Kraken (0,26%/ordre)")
    L.append("pesent lourd. La valeur de ce CSV vient de la DUREE d'accumulation.")
    L.append("-" * 60)
    return "\n".join(L)
