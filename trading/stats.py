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
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

import config
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


# --------------------------------------------------------------------------- #
#  Filtrage temporel (fonctions PURES : aucune I/O, aucun reseau)             #
# --------------------------------------------------------------------------- #
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def parse_bound(value, end=False):
    """
    Convertit une borne de date CLI en Timestamp. Formats acceptes :
    'YYYY-MM-DD' et 'YYYY-MM-DD HH:MM:SS'. Retourne None si `value` est vide.

    `end=True` (borne de FIN) et date SEULE -> fin de journee (23:59:59), pour que
    `--until 2026-09-01` inclue toute la journee du 1er (sinon la borne serait
    minuit et la journee demandee serait vide, piege classique). Une borne avec
    heure explicite est prise telle quelle. Les deux bornes sont INCLUSIVES.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            ts = pd.Timestamp(dt.datetime.strptime(s, fmt))
        except ValueError:
            continue
        if end and fmt == "%Y-%m-%d":
            ts = ts + pd.Timedelta(hours=23, minutes=59, seconds=59)
        return ts
    raise ValueError(
        f"Date invalide : '{value}'. Formats acceptes : "
        "'YYYY-MM-DD' ou 'YYYY-MM-DD HH:MM:SS'."
    )


def filter_period(df: pd.DataFrame, since=None, until=None) -> pd.DataFrame:
    """
    Restreint le CSV a une fenetre temporelle sur la colonne `time`, bornes
    INCLUSIVES. `since`/`until` sont des chaines CLI (cf. parse_bound) ou None.

    - fenetre vide -> DataFrame vide (memes colonnes), jamais une erreur ;
    - lignes a `time` illisible -> exclues des qu'un filtre est demande (on ne
      peut pas affirmer qu'elles sont dans la fenetre) ;
    - aucun filtre -> le DataFrame est retourne TEL QUEL (comportement inchange).
    """
    lo = parse_bound(since, end=False)
    hi = parse_bound(until, end=True)
    if lo is None and hi is None:
        return df
    if "time" not in df.columns:
        raise ValueError("Colonne 'time' absente : impossible de filtrer par date.")
    t = pd.to_datetime(df["time"], errors="coerce")
    keep = t.notna()
    if lo is not None:
        keep &= t >= lo
    if hi is not None:
        keep &= t <= hi
    return df[keep]


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


def summarize(df: pd.DataFrame, since=None, until=None, n_total=None) -> dict:
    """
    Synthese descriptive depuis le CSV (source de verite).

    `since`/`until`/`n_total` sont PUREMENT DESCRIPTIFS (le filtrage, lui, est fait
    par `filter_period` en amont) : ils servent a ce que le resume dise sur quelle
    FENETRE il porte, pour qu'on ne puisse pas confondre une fenetre avec le total.
    Appel historique `summarize(df)` : sortie inchangee, plus 3 cles descriptives.
    """
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
        # Fenetre demandee (None = aucun filtre) + total AVANT filtrage.
        "filter_since": str(since) if since else None,
        "filter_until": str(until) if until else None,
        "n_cycles_total": int(n if n_total is None else n_total),
    }


WEEKDAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def honesty_note() -> str:
    """Encart d'honnetete : SOURCE UNIQUE, partagee par le rendu CLI (format_summary
    ci-dessous) et le rendu web (trading/stats_page.py). Garantit que l'ecran web
    reprend ce texte MOT POUR MOT (spec §4.11) -- une seule fonction, jamais deux
    copies qui pourraient diverger.

    Le taux de frais AFFICHE est DERIVE de `config.FEE` (jamais recopie en dur) :
    si `config.FEE` change (nouvelle grille Kraken), ce texte suit automatiquement --
    corrige BUG P2-1 (l'ancien texte fige affichait "0,26%/ordre" alors que
    config.FEE_TAKER vaut 0,80% depuis BUG-003, docs/SQA.md).
    """
    fee_pct = config.FEE * 100
    return (
        "Honnêteté : stats DESCRIPTIVES, pas une preuve d'edge. Accumuler de la\n"
        "donnée ne crée aucun profit ; seul le walk-forward (hors-échantillon)\n"
        f"juge une stratégie. Sur timeframe court, les frais Kraken ({fee_pct:.2f}%/ordre)\n"
        "pèsent lourd. La valeur de ce CSV vient de la DURÉE d'accumulation."
    )


def format_summary(d: dict) -> str:
    """Rendu texte lisible + disclaimer d'honnetete."""
    L = []
    L.append("=" * 60)
    L.append("  LABO DE STATS - synthese descriptive")
    L.append("=" * 60)
    L.append(f"Periode      : {d['time_min']} -> {d['time_max']}")
    # Fenetre : n'apparait QUE si un filtre --since/--until a ete demande, pour
    # qu'on ne confonde jamais une fenetre avec le total accumule. Rendu par
    # defaut (sans filtre) strictement inchange. `.get` : un dict de resume
    # construit a la main (ancien appelant) reste affichable.
    if d.get("filter_since") or d.get("filter_until"):
        L.append(f"Fenetre      : depuis {d.get('filter_since') or 'le debut'} "
                 f"jusqu'a {d.get('filter_until') or 'la fin'} "
                 f"(filtre demande ; {d['n_cycles']} cycles retenus sur "
                 f"{d.get('n_cycles_total', d['n_cycles'])} au total)")
    L.append(f"Cycles       : {d['n_cycles']}")
    if not d["n_cycles"]:
        L.append("Aucun cycle dans cette fenetre : les chiffres ci-dessous sont vides "
                 "(ce n'est PAS un resultat).")
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
            nom = WEEKDAY_NAMES[int(wd)] if 0 <= int(wd) < 7 else str(wd)
            L.append(f"  {nom:9s} : {c['cycles']:4d} / {c['trades']}")

    L.append("\n" + "-" * 60)
    L.extend(honesty_note().splitlines())
    L.append("-" * 60)
    return "\n".join(L)
