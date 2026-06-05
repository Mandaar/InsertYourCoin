"""
Tests du serveur de monitoring (trading/monitor.py).

Aucun reseau, aucune cle API, AUCUN serveur instancie (pas de bind reseau) : on
teste uniquement les fonctions PURES via des fichiers synthetiques (tmp_path).
"""
import json

from trading.monitor import (
    read_state, read_last_stats, tail_log, compute_view, build_html,
    render_fragment,
)


# --------------------------------------------------------------------------- #
#  read_state                                                                 #
# --------------------------------------------------------------------------- #
def test_read_state_ok(tmp_path):
    p = tmp_path / "paper_state.json"
    state = {"cash": 9000.0, "base_amount": 0.3, "invested": True,
             "entry_price": 100.0, "peak": 120.0, "trades": []}
    p.write_text(json.dumps(state), encoding="utf-8")
    out = read_state(p)
    assert out["invested"] is True
    assert out["cash"] == 9000.0


def test_read_state_missing_returns_none(tmp_path):
    assert read_state(tmp_path / "nope.json") is None


def test_read_state_unreadable_returns_none(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ pas du json", encoding="utf-8")
    assert read_state(p) is None


# --------------------------------------------------------------------------- #
#  read_last_stats                                                            #
# --------------------------------------------------------------------------- #
_CSV_HEADER = "time,price,equity,exposure,drawdown,action\n"


def test_read_last_stats_ok(tmp_path):
    p = tmp_path / "paper_stats.csv"
    p.write_text(
        _CSV_HEADER
        + "2022-01-01 00:00:00,100,10000,0,0,hold\n"
        + "2022-01-01 01:00:00,110,11000,1,0,buy\n",
        encoding="utf-8",
    )
    out = read_last_stats(p)
    assert out["n"] == 2
    assert out["first_time"] == "2022-01-01 00:00:00"
    assert out["last_time"] == "2022-01-01 01:00:00"
    assert out["row"]["price"] == "110"


def test_read_last_stats_missing_returns_none(tmp_path):
    assert read_last_stats(tmp_path / "nope.csv") is None


def test_read_last_stats_empty_returns_none(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    assert read_last_stats(p) is None


def test_read_last_stats_header_only_returns_none(tmp_path):
    p = tmp_path / "head.csv"
    p.write_text(_CSV_HEADER, encoding="utf-8")
    assert read_last_stats(p) is None


def test_read_last_stats_ignores_partial_last_line(tmp_path):
    """Derniere ligne tronquee (en cours d'ecriture) -> on prend la precedente."""
    p = tmp_path / "partial.csv"
    p.write_text(
        _CSV_HEADER
        + "2022-01-01 00:00:00,100,10000,0,0,hold\n"
        + "2022-01-01 01:00:00,110\n",  # ligne partielle (champs manquants)
        encoding="utf-8",
    )
    out = read_last_stats(p)
    assert out["n"] == 2
    assert out["row"]["time"] == "2022-01-01 00:00:00"  # ligne complete precedente


# --------------------------------------------------------------------------- #
#  tail_log                                                                   #
# --------------------------------------------------------------------------- #
def test_tail_log_ok(tmp_path):
    p = tmp_path / "paper_trades.log"
    p.write_text("\n".join(f"ligne {i}" for i in range(100)), encoding="utf-8")
    out = tail_log(p, n=5)
    assert out == ["ligne 95", "ligne 96", "ligne 97", "ligne 98", "ligne 99"]


def test_tail_log_missing_returns_empty(tmp_path):
    assert tail_log(tmp_path / "nope.log") == []


# --------------------------------------------------------------------------- #
#  compute_view                                                               #
# --------------------------------------------------------------------------- #
def _stats(row, n=1, last_time="2022-01-01 00:00:00"):
    return {"row": row, "n": n, "first_time": last_time, "last_time": last_time}


def test_compute_view_pnl_and_statut():
    state = {"invested": True, "trades": []}
    stats = _stats({"price": "110", "equity": "11000", "exposure": "1",
                    "drawdown": "-0.05"})
    v = compute_view(state, stats, [], 10000.0, "2022-01-01 00:00:30")
    assert v["statut"] == "INVESTI"
    assert v["price"] == 110.0
    assert v["pnl_total"] == 1000.0
    assert v["pnl_pct"] == 0.1
    assert v["exposure"] == 1.0


def test_compute_view_statut_cash():
    state = {"invested": False, "trades": []}
    stats = _stats({"price": "100", "equity": "10000", "exposure": "0",
                    "drawdown": "0"})
    v = compute_view(state, stats, [], 10000.0, "2022-01-01 00:00:30")
    assert v["statut"] == "CASH"
    assert v["pnl_total"] == 0.0


def test_compute_view_inactif_true_when_old():
    state = {"invested": False, "trades": []}
    stats = _stats({"price": "100", "equity": "10000", "exposure": "0"},
                   last_time="2022-01-01 00:00:00")
    # +10 min -> 600s > 360s -> inactif
    v = compute_view(state, stats, [], 10000.0, "2022-01-01 00:10:00")
    assert v["age_seconds"] == 600.0
    assert v["inactif"] is True


def test_compute_view_inactif_false_when_recent():
    state = {"invested": False, "trades": []}
    stats = _stats({"price": "100", "equity": "10000", "exposure": "0"},
                   last_time="2022-01-01 00:00:00")
    v = compute_view(state, stats, [], 10000.0, "2022-01-01 00:01:00")  # 60s
    assert v["age_seconds"] == 60.0
    assert v["inactif"] is False


def test_compute_view_trades_truncated_to_8():
    trades = [{"time": f"t{i}", "side": "buy", "price": 100 + i} for i in range(12)]
    state = {"invested": False, "trades": trades}
    stats = _stats({"price": "100", "equity": "10000"})
    v = compute_view(state, stats, [], 10000.0, "2022-01-01 00:00:30")
    assert len(v["trades"]) == 8
    assert v["trades"][0]["time"] == "t4"   # les 8 plus recents
    assert v["trades"][-1]["time"] == "t11"


def test_compute_view_no_data():
    v = compute_view(None, None, [], 10000.0, "2022-01-01 00:00:00")
    assert v["has_data"] is False
    assert v["n_cycles"] == 0
    assert v["age_seconds"] is None


# --------------------------------------------------------------------------- #
#  render_fragment                                                            #
# --------------------------------------------------------------------------- #
def test_render_fragment_with_data():
    state = {"invested": True, "trades": [{"time": "t1", "side": "buy", "price": 100.0}]}
    stats = _stats({"price": "99.50", "equity": "11000", "exposure": "1",
                    "drawdown": "-0.05"})
    v = compute_view(state, stats, ["[t] cycle ok"], 10000.0, "2022-01-01 00:00:30")
    frag = render_fragment(v)
    assert isinstance(frag, str) and len(frag) > 0
    assert "99.50" in frag
    assert "P&amp;L" in frag
    assert "auto-refresh" in frag    # horodatage present dans le fragment


def test_render_fragment_no_data_shows_waiting():
    v = compute_view(None, None, [], 10000.0, "2022-01-01 00:00:00")
    frag = render_fragment(v)
    assert "En attente" in frag
    assert "auto-refresh" in frag    # horodatage toujours present


# --------------------------------------------------------------------------- #
#  build_html                                                                 #
# --------------------------------------------------------------------------- #
def test_build_html_contains_price_and_labels():
    state = {"invested": True, "trades": [{"time": "t1", "side": "buy", "price": 100.0}]}
    stats = _stats({"price": "123.45", "equity": "11000", "exposure": "1",
                    "drawdown": "-0.05"})
    v = compute_view(state, stats, ["[t] CASH | prix 123.45"], 10000.0,
                     "2022-01-01 00:00:30")
    out = build_html(v)
    assert isinstance(out, str) and len(out) > 0
    assert "123.45" in out
    assert "P&amp;L" in out          # libelle P&L (HTML-escape)
    assert "Equity" in out


def test_build_html_no_meta_refresh():
    """La page complete ne doit PAS contenir de meta http-equiv refresh (rechargement bloque)."""
    state = {"invested": False, "trades": []}
    stats = _stats({"price": "100", "equity": "10000", "exposure": "0", "drawdown": "0"})
    v = compute_view(state, stats, [], 10000.0, "2022-01-01 00:00:30")
    out = build_html(v)
    # Ni 'http-equiv' ni la balise meta de rechargement automatique ne doivent apparaitre.
    assert "http-equiv" not in out.lower()


def test_build_html_has_content_div_and_fetch():
    """La page doit contenir id='content' et fetch('/fragment') pour le JS partiel."""
    state = {"invested": False, "trades": []}
    stats = _stats({"price": "100", "equity": "10000", "exposure": "0", "drawdown": "0"})
    v = compute_view(state, stats, [], 10000.0, "2022-01-01 00:00:30")
    out = build_html(v)
    assert "id='content'" in out or 'id="content"' in out
    assert "fetch('/fragment'" in out or 'fetch("/fragment"' in out


def test_build_html_marks_error_log_lines():
    state = {"invested": False, "trades": []}
    stats = _stats({"price": "100", "equity": "10000"})
    v = compute_view(state, stats, ["[t] Erreur cycle [reseau] : timeout"],
                     10000.0, "2022-01-01 00:00:30")
    out = build_html(v)
    assert "logerr" in out           # ligne contenant 'Erreur' marquee en rouge


def test_build_html_no_data_shows_waiting():
    v = compute_view(None, None, [], 10000.0, "2022-01-01 00:00:00")
    out = build_html(v)
    assert "En attente" in out
