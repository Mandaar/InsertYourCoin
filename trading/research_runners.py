"""
Runners de recherche (Lot 4) : fonctions potentiellement LONGUES executees
DANS un job asynchrone (trading/jobs.py, thread worker), jamais sur le thread
HTTP qui sert une requete (cf. docs/UI_UX_WEBAPP_SPEC.md §7.2).

Contrat JobManager (trading/jobs.py) : `run_backtest(params, progress)` logge
via `progress.log(...)`, observe `progress.cancelled` entre les etapes
couteuses, et retourne un payload quelconque recupere ensuite via
`manager.result(job_id)`.

Import PARESSEUX de `main` (meme raison que trading/diagnostics_web.py :
main.py importe trading.* au chargement -- un import top-level depuis
trading/ risquerait un cycle a l'execution `python main.py monitor`).

Testable SANS RESEAU : `_load_ohlcv(params, progress)` est le SEUL point
d'acces aux donnees externes -- les tests le monkeypatchent
(`research_runners._load_ohlcv`) pour injecter un DataFrame OHLCV synthetique
(cf. conftest.make_ohlcv), sans jamais appeler Kraken/Binance.
"""
from .backtester import Backtester
from .strategies import STRATEGIES, build_strategy


class ResearchError(Exception):
    """Erreur de recherche lisible (donnees indisponibles, parametre invalide).
    Le message ne contient jamais de secret -- il devient `error_message` du
    job (cf. trading/jobs.py JobManager._run) puis le texte affiche par
    trading/report_page.py render_report_error()."""


def _frac(pct):
    return None if pct is None else pct / 100.0


def _bt_kwargs(params):
    """Traduit les params du formulaire web en kwargs Backtester -- meme
    convention que main._bt_kwargs (pourcentages -> fractions)."""
    ps = params.get("position_sizing") or "none"
    tv = params.get("target_vol")
    return dict(
        stop_loss=_frac(params.get("stop_loss")),
        take_profit=_frac(params.get("take_profit")),
        trailing_stop=_frac(params.get("trailing_stop")),
        position_sizing=(None if ps == "none" else ps),
        target_vol=(tv / 100.0 if tv is not None else None),
    )


def _load_ohlcv(params, progress):
    """
    Point d'acces UNIQUE aux donnees de marche (source reelle Kraken/Binance).
    Fonction SEPAREE pour rester monkeypatchable dans les tests (injection
    d'un DataFrame synthetique, zero reseau). Reutilise main._load_data (meme
    routage Kraken/Binance, meme exclusion B4 de la bougie en formation) au
    lieu de le reecrire.
    """
    import main
    from .exchange import KrakenExchange

    symbol = params["symbol"]
    timeframe = params.get("timeframe") or "1d"
    days = params.get("days") or 720
    source = params.get("source") or "kraken"
    progress.log(f"Chargement {symbol} ({timeframe}, {days}j, source={source})...")
    return main._load_data(KrakenExchange(), symbol, timeframe, days, source=source)


def run_backtest(params, progress):
    """
    Runner du job POST /research/backtest (Lot 4, spec §4.3). `params` = dict
    deja VALIDE cote route (trading/research_page.py parse_backtest_params) :
    strategy/symbol/timeframe/days/source + risque (stop_loss/take_profit/
    trailing_stop/position_sizing/target_vol, en POURCENTAGES ou None).

    Retourne un payload consomme par trading/report_page.py render_report_done
    -> trading/dashboard.py render_dashboard_html (memes objets que la CLI
    `dashboard`, aucune re-derivation) :
        {"detail": BacktestResult, "comparison": [...], "context": {...}}

    Leve `ResearchError` (message actionnable, sans donnee sensible) si les
    donnees sont indisponibles ou insuffisantes -- JobManager convertit toute
    exception en etat 'error' (cf. trading/jobs.py JobManager._run).
    """
    strategy_key = (params.get("strategy") or "").lower()
    if strategy_key not in STRATEGIES:
        raise ResearchError(f"Strategie inconnue : {strategy_key or '(vide)'!r}.")

    try:
        df = _load_ohlcv(params, progress)
    except ResearchError:
        raise
    except Exception as exc:  # noqa: BLE001 -- classee en message actionnable, jamais de crash de job
        raise ResearchError(
            "Donnees indisponibles pour ce symbole/timeframe/source. "
            f"Detail : {exc}"
        ) from exc

    if df is None or len(df) < 2:
        raise ResearchError(
            "Pas assez de bougies chargees pour lancer le backtest "
            "(symbole/timeframe/jours a verifier)."
        )

    if progress.cancelled:
        return None

    progress.log(f"Backtest {build_strategy(strategy_key).name} en cours...")
    kw = _bt_kwargs(params)
    detail = Backtester(**kw).run(df, build_strategy(strategy_key))

    if progress.cancelled:
        return None

    progress.log("Comparaison des strategies (reference Buy & Hold incluse)...")
    comparison = []
    for key in STRATEGIES:
        if progress.cancelled:
            return None
        comparison.append({
            "name": build_strategy(key).name,
            "metrics": Backtester(**kw).run(df, build_strategy(key)).metrics,
        })

    progress.log("Termine.")
    return {
        "detail": detail,
        "comparison": comparison,
        "context": {
            "symbol": params.get("symbol"),
            "timeframe": params.get("timeframe") or "1d",
        },
    }
