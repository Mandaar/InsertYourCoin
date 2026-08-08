"""
Tests du rendu pur du Labo de stats (trading/stats_page.py).

Aucun reseau, aucun serveur : on construit un `summary` via trading.stats
(reutilise tel quel, comme en prod) et on verifie le HTML produit.
"""
import html

from trading.stats import StatsRecorder, honesty_note, load_stats, summarize
from trading.stats_page import render_stats_page


def _build_summary(tmp_path):
    rec = StatsRecorder(str(tmp_path / "paper_stats.csv"))
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
    return summarize(load_stats(tmp_path / "paper_stats.csv"))


# --------------------------------------------------------------------------- #
#  Etat vide (message exact de load_stats)                                    #
# --------------------------------------------------------------------------- #
def test_render_stats_page_empty_shows_exact_message(tmp_path):
    csv_path = tmp_path / "paper_stats.csv"
    try:
        load_stats(csv_path)
        assert False, "load_stats devrait lever sur un fichier absent"
    except FileNotFoundError as exc:
        message = str(exc)

    out = render_stats_page("paper_stats.csv", [], None, empty_message=message)
    assert "Aucune donnée" in out
    assert message.replace("'", "&#x27;") in out or message in out
    # Nav commune + honnetete restent presentes meme sans donnees.
    assert "<nav class='nav'>" in out
    assert "Labo de stats" in out
    assert "DESCRIPTIVES" in out


def test_render_stats_page_empty_without_message_has_fallback():
    out = render_stats_page("paper_stats.csv", [], None, empty_message=None)
    assert "Aucune donnée" in out


# --------------------------------------------------------------------------- #
#  Donnees presentes : metriques + ventilation + honnetete                    #
# --------------------------------------------------------------------------- #
def test_render_stats_page_with_data_shows_key_metrics(tmp_path):
    summary = _build_summary(tmp_path)
    out = render_stats_page("paper_stats.csv", ["paper_stats.csv"], summary)

    assert "2022-01-01 00:00:00" in out
    assert "2022-01-02 00:00:00" in out
    assert "Cycles" in out and ">3<" in out
    assert "Rendement" in out
    assert "Drawdown max" in out
    assert "Réussite" in out
    assert "PnL total" in out
    assert "Exposition moy." in out


def test_render_stats_page_highlights_fees_share(tmp_path):
    summary = _build_summary(tmp_path)
    out = render_stats_page("paper_stats.csv", ["paper_stats.csv"], summary)
    assert "card stat fees" in out
    assert "Frais" in out


def test_render_stats_page_shows_hour_and_weekday_bars(tmp_path):
    summary = _build_summary(tmp_path)
    out = render_stats_page("paper_stats.csv", ["paper_stats.csv"], summary)
    assert "Par heure" in out
    assert "Par jour" in out
    assert "lundi" in out
    assert "mardi" in out
    assert "barfill" in out


def test_render_stats_page_honesty_verbatim(tmp_path):
    """L'encart d'honnetete doit reprendre MOT POUR MOT trading.stats.honesty_note()
    (source unique partagee avec le rendu CLI format_summary) -- compare apres
    html.escape (meme transformation que _esc, XSS-safe par construction)."""
    summary = _build_summary(tmp_path)
    out = render_stats_page("paper_stats.csv", ["paper_stats.csv"], summary)
    for line in honesty_note().splitlines():
        assert html.escape(line) in out


# --------------------------------------------------------------------------- #
#  Selecteur de fichier (HTML seulement -- la securite est testee cote        #
#  monitor.py resolve_stats_path, cf. tests/test_monitor_server.py)           #
# --------------------------------------------------------------------------- #
def test_file_picker_hidden_when_single_file(tmp_path):
    summary = _build_summary(tmp_path)
    out = render_stats_page("paper_stats.csv", ["paper_stats.csv"], summary)
    assert "<select" not in out
    assert "paper_stats.csv" in out


def test_file_picker_shown_when_multiple_files(tmp_path):
    summary = _build_summary(tmp_path)
    out = render_stats_page(
        "paper_stats.csv", ["paper_stats.csv", "old_stats.csv"], summary
    )
    assert "<select id='file' name='file'>" in out
    assert "<label for='file'>" in out
    assert "old_stats.csv" in out
    assert "selected" in out
