"""
Vue Rapport (/report/<job_id>) -- fonctions PURES de rendu (testables sans
serveur), cf. docs/UI_UX_WEBAPP_SPEC.md §4.8. Affiche le resultat d'un job de
backtest (trading/research_runners.run_backtest) EN LIGNE, en reutilisant
integralement trading/dashboard.py render_dashboard_html -- aucune logique de
rendu de graphiques dupliquee ici.

`trading/monitor.py` route GET /report/<job_id> choisit LEQUEL de ces rendus
appeler selon `JobManager.status(job_id)` :
- id inconnu / evince de l'historique -> render_report_unknown()
- pending/running                     -> render_report_pending() (panneau job)
- error                               -> render_report_error(message)
- cancelled                           -> render_report_cancelled()
- done + resultat                     -> render_report_done(result)
"""
import html

from .dashboard import render_dashboard_html
from .webui import job_panel_html, page_shell

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.muted { color: #6b7787; }
.navlink { color: #6cb6ff; text-decoration: none; font-size: 13px; }
.navlink:hover { text-decoration: underline; }
.card { background: #171c24; border: 1px solid #232b36; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; }
.result-error { background: #3a1d12; border: 1px solid #e5534b; color: #ffb4ad; }
.result-cancelled { background: #3a2a12; border: 1px solid #f0b429; color: #ffd98a; }
.in-sample-badge { display: flex; align-items: center; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; background: #3a2a12; border: 1px solid #f0b429;
  color: #ffd98a; border-radius: 8px; padding: 10px 16px; margin-bottom: 14px;
  font-size: 13px; font-weight: 600; }
.in-sample-badge .wf-link { color: #6b7787; font-weight: 400; font-size: 12px; }
"""


def _esc(s):
    return html.escape("" if s is None else str(s))


def _wrap(title, body_html) -> str:
    return page_shell(title, "research", f"<style>{_CSS}</style>" + body_html)


def render_report_unknown() -> str:
    """Job introuvable (jamais soumis, ou evince de l'historique retenu par
    JobManager -- cf. trading/jobs.py max_history) : lien de retour, jamais
    une erreur brute."""
    body = (
        "<div class='head'><h1>Rapport</h1>"
        "<a class='navlink' href='/research/backtest'>&larr; Nouvelle analyse</a></div>"
        "<div class='card'>Analyse introuvable (lien expire ou jamais lancee "
        "sur ce serveur). <a class='navlink' href='/research/backtest'>"
        "Relance un backtest.</a></div>"
    )
    return _wrap("Rapport introuvable - InsertYourCoin", body)


def render_report_pending(job_id, csrf_token) -> str:
    """Job pas encore termine : reaffiche le meme panneau de progression que
    juste apres le lancement (utile si l'utilisateur arrive directement sur
    l'URL /report/<id>, ex. onglet rouvert) -- redirige tout seul a la fin."""
    body = (
        "<div class='head'><h1>Rapport en cours</h1>"
        "<a class='navlink' href='/research/backtest'>&larr; Formulaire</a></div>"
        "<div class='card'>"
        + job_panel_html(job_id, csrf_token, result_url=f"/report/{job_id}")
        + "</div>"
    )
    return _wrap("Rapport en cours - InsertYourCoin", body)


def render_report_error(error_message) -> str:
    """Job termine en erreur (donnees indisponibles, cf.
    research_runners.ResearchError) : message actionnable, jamais de trace
    technique brute ni de donnee sensible (deja garanti par JobManager, qui ne
    retient que str(exc))."""
    msg = error_message or "Erreur inconnue."
    body = (
        "<div class='head'><h1>Rapport</h1>"
        "<a class='navlink' href='/research/backtest'>&larr; Nouvelle analyse</a></div>"
        f"<div class='card result-error'>Le backtest a echoue : {_esc(msg)}</div>"
    )
    return _wrap("Erreur - Rapport - InsertYourCoin", body)


def render_report_cancelled() -> str:
    body = (
        "<div class='head'><h1>Rapport</h1>"
        "<a class='navlink' href='/research/backtest'>&larr; Nouvelle analyse</a></div>"
        "<div class='card result-cancelled'>Analyse annulee.</div>"
    )
    return _wrap("Analyse annulee - InsertYourCoin", body)


def render_report_done(result) -> str:
    """
    Rapport pret : bandeau IN-SAMPLE (honnetete, spec §4.3/§4.8 -- "le
    walk-forward est le juge") + rendu integral de dashboard.py
    render_dashboard_html (memes cartes/graphiques/tableaux que la CLI
    `dashboard`, servi INLINE -- plus de fichier .html a ouvrir).

    `result` = payload de research_runners.run_backtest :
    {"detail": BacktestResult, "comparison": [...], "context": {...}}.
    """
    detail = result["detail"]
    comparison = result["comparison"]
    context = result["context"]

    badge = (
        "<div class='in-sample-badge'>"
        "<span>IN-SAMPLE &mdash; non valide hors-echantillon. De bons chiffres "
        "passes ne garantissent jamais le futur.</span>"
        "<span class='wf-link'>Le walk-forward est le juge "
        "(bientot dans l'app : /research/walkforward)</span>"
        "</div>"
    )
    content = render_dashboard_html(detail, comparison, context)
    symbol = context.get("symbol") or "?"
    title = f"Rapport - {symbol} - InsertYourCoin"
    return _wrap(title, badge + content)
