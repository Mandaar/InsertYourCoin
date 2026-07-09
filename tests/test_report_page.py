"""
Tests de trading/report_page.py (/report/<job_id>) : fonctions PURES de
rendu, aucun serveur ni reseau. Le rapport "done" reutilise un VRAI
BacktestResult (produit par le moteur reel sur donnees synthetiques) pour
verifier l'integration avec trading/dashboard.py render_dashboard_html.

Lot 5 : `render_result_done` GENERALISE le dispatch par `result["kind"]`
(compare/optimize/portfolio/backtest) -- teste separement en bas de fichier.
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


# --------------------------------------------------------------------------- #
#  Lot 5 -- render_result_done (dispatch generalise par result["kind"])       #
# --------------------------------------------------------------------------- #
def test_render_result_done_dispatches_backtest_to_dashboard(make_df):
    result = _real_result(make_df)  # kind absent -- compat Lot 4
    out = rep.render_result_done(result)
    assert out == rep.render_report_done(result)


def test_render_result_done_dispatches_explicit_backtest_kind(make_df):
    result = dict(_real_result(make_df), kind="backtest")
    out = rep.render_result_done(result)
    assert 'id="equity"' in out  # rendu dashboard, pas un des 3 autres ecrans


def test_render_result_done_dispatches_compare():
    result = {"kind": "compare", "rows": [], "buy_hold": 0.0,
             "context": {"symbol": "ETH/USD", "timeframe": "1d"}}
    out = rep.render_result_done(result)
    assert "Recherche &mdash; Comparer" in out


def test_render_result_done_dispatches_optimize(make_df):
    from trading.optimizer import optimize
    import numpy as np
    t = np.arange(600)
    df = make_df(100.0 + 20.0 * np.sin(t / 12.0))
    res = optimize(df, "sma", train_frac=0.6, metric="sharpe")
    result = {"kind": "optimize", "result": res,
             "context": {"symbol": "ETH/USD", "timeframe": "1d"}}
    out = rep.render_result_done(result)
    assert "Train (in-sample)" in out


def test_render_result_done_dispatches_portfolio(make_df):
    from trading.portfolio import backtest_portfolio
    import numpy as np
    t = np.arange(150)
    data = {"BTC/USD": make_df(100.0 + 20.0 * np.sin(t / 12.0)),
            "ETH/USD": make_df(50.0 + 10.0 * np.sin(t / 9.0))}
    res = backtest_portfolio(data, "sma")
    result = {"kind": "portfolio", "result": res, "ignored": [],
             "context": {"symbols": ["BTC/USD", "ETH/USD"], "timeframe": "1d",
                        "source": "kraken"}}
    out = rep.render_result_done(result)
    assert "corr-table" in out
