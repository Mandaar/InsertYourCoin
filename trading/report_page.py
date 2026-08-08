"""
Vue Rapport / Resultat (/report/<job_id>) -- fonctions PURES de rendu
(testables sans serveur), cf. docs/UI_UX_WEBAPP_SPEC.md §4.8. Affiche le
resultat d'UN JOB DE RECHERCHE EN LIGNE, quel que soit son type (Lot 5 :
`render_result_done` GENERALISE ce qui n'affichait au Lot 4 que le backtest).

`trading/monitor.py` route GET /report/<job_id> choisit LEQUEL de ces rendus
appeler selon `JobManager.status(job_id)` :
- id inconnu / evince de l'historique -> render_report_unknown()
- pending/running                     -> render_report_pending() (panneau job)
- error                               -> render_report_error(message)
- cancelled                           -> render_report_cancelled()
- done + resultat                     -> render_result_done(result)

`render_result_done` (Lot 5, etendu Lot 6) lit `result["kind"]` (cf.
trading/research_runners.py) et delegue au rendu du bon ecran :
- "compare"/"optimize"/"portfolio" -> trading/compare_page.py,
  optimize_page.py, portfolio_page.py (Lot 5, ecrans dedies : tableau,
  panneaux train/test, heatmap de correlation -- pas de dashboard.py, qui
  reste specifique a un SEUL backtest).
- "walkforward" -> trading/walkforward_page.py render_walkforward_done
  (Lot 6, LE JUGE : bandeau verdict, holdout sacre, fenetres OOS par actif).
- "backtest" (ou absent, compat Lot 4)  -> render_report_done ci-dessous,
  qui reutilise integralement trading/dashboard.py render_dashboard_html --
  AUCUNE logique de rendu de graphiques dupliquee ici. Le champ "kind" a ete
  ajoute au payload de run_backtest au Lot 5 ; l'absence (payload plus
  ancien/externe) retombe sur ce meme rendu backtest, jamais une erreur.
"""
import html

from .dashboard import render_dashboard_html
from .webui import job_panel_html, page_shell

_CSS = """
.head { display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.muted { color: #8b97a6; }
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
.in-sample-badge .wf-link { color: #8b97a6; font-weight: 400; font-size: 12px; }
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
        "<div class='card'>Analyse introuvable (lien expiré ou jamais lancée "
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
        f"<div class='card result-error'>Le backtest a échoué : {_esc(msg)}</div>"
    )
    return _wrap("Erreur - Rapport - InsertYourCoin", body)


def render_report_cancelled() -> str:
    body = (
        "<div class='head'><h1>Rapport</h1>"
        "<a class='navlink' href='/research/backtest'>&larr; Nouvelle analyse</a></div>"
        "<div class='card result-cancelled'>Analyse annulée.</div>"
    )
    return _wrap("Analyse annulée - InsertYourCoin", body)


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
        "<span>IN-SAMPLE &mdash; non valide hors-échantillon. De bons chiffres "
        "passés ne garantissent jamais le futur.</span>"
        "<span class='wf-link'>Le walk-forward est le juge -- "
        "<a class='navlink' href='/research/walkforward'>lance-le ici</a></span>"
        "</div>"
    )
    content = render_dashboard_html(detail, comparison, context)
    symbol = context.get("symbol") or "?"
    title = f"Rapport - {symbol} - InsertYourCoin"
    return _wrap(title, badge + content)


def render_result_done(result) -> str:
    """
    Dispatcher GENERALISE (Lot 5, etendu Lot 6) du rendu "job termine avec
    resultat" : LE SEUL point que trading/monitor.py `_report_get` appelle
    pour l'etat 'done' -- quel que soit le type d'analyse. Lit `result.get("kind")`
    (cf. trading/research_runners.py, contrat pose au Lot 5) :
        "compare"     -> trading/compare_page.py     render_compare_done
        "optimize"    -> trading/optimize_page.py    render_optimize_done
        "portfolio"   -> trading/portfolio_page.py   render_portfolio_done
        "walkforward" -> trading/walkforward_page.py render_walkforward_done
        "backtest" / absent (compat Lot 4)  -> render_report_done (ci-dessus)

    Import PARESSEUX des modules Lot 5/6 : evite tout risque de cycle
    d'import avec ce module (compare_page/optimize_page/portfolio_page/
    walkforward_page n'importent pas report_page, mais rester coherent avec
    la convention d'imports paresseux deja en place dans
    trading/research_runners.py).
    """
    kind = (result or {}).get("kind") or "backtest"
    if kind == "compare":
        from .compare_page import render_compare_done
        return render_compare_done(result)
    if kind == "optimize":
        from .optimize_page import render_optimize_done
        return render_optimize_done(result)
    if kind == "portfolio":
        from .portfolio_page import render_portfolio_done
        return render_portfolio_done(result)
    if kind == "walkforward":
        from .walkforward_page import render_walkforward_done
        return render_walkforward_done(result)
    return render_report_done(result)
