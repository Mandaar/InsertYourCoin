"""
Tests de trading/report_page.py (Lot 4, /report/<job_id>) : fonctions PURES de
rendu, aucun serveur ni reseau. Le rapport "done" reutilise un VRAI
BacktestResult (produit par le moteur reel sur donnees synthetiques) pour
verifier l'integration avec trading/dashboard.py render_dashboard_html.
"""
from trading import report_page as rep
from trading.backtester import Backtester
from trading.strategies import STRATEGIES, build_strategy


def _real_result(make_df):
    closes = [100 + i * 0.5 for i in range(150)]
    df = make_df(closes)
    kw = dict(stop_loss=None, take_profit=None, trailing_stop=None,
             position_sizing=None, target_vol=None)
    detail = Backtester(**kw).run(df, build_strategy("sma"))
    comparison = [{"name": build_strategy(k).name,
                   "metrics": Backtester(**kw).run(df, build_strategy(k)).metrics}
                  for k in STRATEGIES]
    return {"detail": detail, "comparison": comparison,
            "context": {"symbol": "ETH/USD", "timeframe": "1d"}}


def test_render_report_unknown_links_back_to_form():
    out = rep.render_report_unknown()
    assert "introuvable" in out.lower()
    assert "/research/backtest" in out
    assert "<nav class='nav'>" in out


def test_render_report_pending_embeds_job_panel():
    out = rep.render_report_pending("d" * 32, "tok")
    assert "class='job-panel'" in out
    assert f"/report/{'d' * 32}" in out


def test_render_report_error_escapes_message():
    out = rep.render_report_error("<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "a echoue" in out


def test_render_report_error_handles_missing_message():
    out = rep.render_report_error(None)
    assert "Erreur inconnue" in out


def test_render_report_cancelled_shows_cancelled_message():
    out = rep.render_report_cancelled()
    assert "annulee" in out.lower()


def test_render_report_done_shows_in_sample_badge_and_dashboard(make_df):
    result = _real_result(make_df)
    out = rep.render_report_done(result)
    assert "IN-SAMPLE" in out
    assert "walk-forward est le juge" in out
    assert 'id="equity"' in out
    assert 'id="dd"' in out
    assert 'id="comp"' in out
    assert "/static/chart.umd.min.js" in out
    assert "<nav class='nav'>" in out          # coquille commune (page_shell)
    assert "ETH/USD" in out


def test_render_report_done_does_not_leak_dashboard_root_vars_globally(make_df):
    # Garde-fou anti-regression : le gabarit dashboard doit rester scope sur
    # .report-body (jamais un second `:root`/`body`) une fois embarque dans
    # page_shell -- sinon il ecrase les couleurs de la nav globale (cf.
    # trading/dashboard.py). page_shell a SA PROPRE regle `:root{...}`
    # (THEME_CSS) : on verifie qu'il n'y en a pas une 2e (celle du dashboard).
    result = _real_result(make_df)
    out = rep.render_report_done(result)
    assert out.count(":root{") == 1          # uniquement celle de page_shell/THEME_CSS
    assert out.count("\nbody{\n") == 1       # uniquement celle de page_shell/THEME_CSS
    assert ".report-body{" in out            # le scope attendu (dashboard) est bien present
