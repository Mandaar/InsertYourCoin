"""
Tests du labo de stats (trading/stats.py).

Aucun reseau, aucune cle API : on ecrit/relit des CSV via tmp_path et on
construit des donnees marche avec la fixture make_df.
"""
import numpy as np
import pandas as pd
import pytest

from trading.stats import (
    COLUMNS, StatsRecorder, market_features, load_stats, summarize, format_summary,
)


def _vol(n, seed=0):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))


# --------------------------------------------------------------------------- #
#  StatsRecorder : entete + append                                            #
# --------------------------------------------------------------------------- #
def test_recorder_writes_header_and_row(tmp_path):
    path = tmp_path / "s.csv"
    rec = StatsRecorder(str(path))
    assert not path.exists()                       # lazy : rien tant qu'on n'ecrit pas
    rec.record({"time": "t1", "symbol": "ETH/USD", "equity": 100.0, "action": "hold"})
    df = pd.read_csv(path)
    assert list(df.columns) == COLUMNS             # ordre EXACT des colonnes
    assert len(df) == 1


def test_recorder_appends_without_duplicate_header(tmp_path):
    path = tmp_path / "s.csv"
    rec = StatsRecorder(str(path))
    rec.record({"time": "t1", "equity": 100.0, "action": "hold"})
    rec.record({"time": "t2", "equity": 110.0, "action": "hold"})
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3                          # 1 entete + 2 lignes
    df = pd.read_csv(path)
    assert list(df["time"]) == ["t1", "t2"]


# --------------------------------------------------------------------------- #
#  Drawdown high-water-mark intra-session                                     #
# --------------------------------------------------------------------------- #
def test_recorder_drawdown_high_water_mark(tmp_path):
    path = tmp_path / "s.csv"
    rec = StatsRecorder(str(path))
    for eq in (100.0, 120.0, 90.0):
        rec.record({"time": "t", "equity": eq, "action": "hold"})
    dd = list(pd.read_csv(path)["drawdown"])
    assert dd[0] == pytest.approx(0.0)
    assert dd[1] == pytest.approx(0.0)
    assert dd[2] == pytest.approx(-0.25)            # 90/120 - 1


# --------------------------------------------------------------------------- #
#  market_features                                                            #
# --------------------------------------------------------------------------- #
def test_market_features_keys_and_finite(make_df):
    feats = market_features(make_df(_vol(80)))
    expected = {"sma_fast", "sma_slow", "rsi", "macd", "macd_signal",
                "boll_upper", "boll_lower", "vol_recent"}
    assert set(feats) == expected
    assert feats["sma_slow"] is not None            # serie assez longue (50)
    for k, v in feats.items():
        assert v is None or np.isfinite(v)


def test_market_features_short_series_no_crash(make_df):
    feats = market_features(make_df(_vol(10)))       # < 50 -> sma_slow indefinie
    assert feats["sma_slow"] is None                 # propre, pas de crash


# --------------------------------------------------------------------------- #
#  summarize / format_summary                                                 #
# --------------------------------------------------------------------------- #
def _build_csv(tmp_path):
    """CSV synthetique : 1 buy, montee, 1 sell gagnant, 1 sell perdant."""
    rec = StatsRecorder(str(tmp_path / "s.csv"))
    rows = [
        {"time": "2022-01-01 00:00:00", "hour": 0, "weekday": 0, "equity": 100.0,
         "exposure": 0.0, "action": "buy", "pnl": 0.0, "fee_paid": 0.26},
        {"time": "2022-01-01 01:00:00", "hour": 1, "weekday": 0, "equity": 120.0,
         "exposure": 1.0, "action": "sell", "pnl": 20.0, "fee_paid": 0.31},
        {"time": "2022-01-02 00:00:00", "hour": 0, "weekday": 1, "equity": 90.0,
         "exposure": 0.0, "action": "sell", "pnl": -10.0, "fee_paid": 0.20},
    ]
    for r in rows:
        rec.record(r)
    return tmp_path / "s.csv"


def test_summarize_metrics(tmp_path):
    d = summarize(load_stats(_build_csv(tmp_path)))
    assert d["n_cycles"] == 3
    assert d["n_trades"] == 3 and d["n_buy"] == 1 and d["n_sell"] == 2
    assert d["total_return"] == pytest.approx(90.0 / 100.0 - 1)   # -0.10
    assert d["max_drawdown"] == pytest.approx(90.0 / 120.0 - 1)   # -0.25
    assert d["win_rate"] == pytest.approx(0.5)                    # 1 sell gagnant / 2
    assert d["pnl_total"] == pytest.approx(10.0)                  # 20 - 10
    assert d["fees_total"] == pytest.approx(0.77)
    assert d["by_hour"][0]["cycles"] == 2
    assert d["by_weekday"][0]["trades"] == 2                      # buy + sell le jour 0


def test_format_summary_non_empty(tmp_path):
    out = format_summary(summarize(load_stats(_build_csv(tmp_path))))
    assert isinstance(out, str) and len(out) > 0
    assert "honnetete" in out.lower()                            # disclaimer present


# --------------------------------------------------------------------------- #
#  load_stats : fichier absent                                                #
# --------------------------------------------------------------------------- #
def test_load_stats_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_stats(tmp_path / "nope.csv")
