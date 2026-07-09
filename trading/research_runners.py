"""
Runners de recherche (Lots 4-5) : fonctions potentiellement LONGUES executees
DANS un job asynchrone (trading/jobs.py, thread worker), jamais sur le thread
HTTP qui sert une requete (cf. docs/UI_UX_WEBAPP_SPEC.md §7.2).

Contrat JobManager (trading/jobs.py) : `run_xxx(params, progress)` logge via
`progress.log(...)`, observe `progress.cancelled` entre les etapes couteuses,
et retourne un payload recupere ensuite via `manager.result(job_id)`. Depuis
le Lot 5, CHAQUE payload porte un champ `"kind"` (`"backtest"|"compare"|
"optimize"|"portfolio"`) -- c'est ce que `trading/report_page.py
render_result_done` lit pour choisir le rendu (generalisation Lot 5, cf.
trading/monitor.py `_report_get`).

Import PARESSEUX de `main` (meme raison que trading/diagnostics_web.py :
main.py importe trading.* au chargement -- un import top-level depuis
trading/ risquerait un cycle a l'execution `python main.py monitor`).

Testable SANS RESEAU : `_load_ohlcv(params, progress)` (mono-actif) et
`_load_basket_ohlcv(params, progress)` (multi-actifs, portfolio) sont les
SEULS points d'acces aux donnees externes -- les tests les monkeypatchent
pour injecter un DataFrame OHLCV synthetique (cf. conftest.make_ohlcv), sans
jamais appeler Kraken/Binance.
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


def _load_basket_ohlcv(params, progress):
    """
    Point d'acces UNIQUE aux donnees de marche MULTI-ACTIFS (runner
    run_portfolio). Reutilise main._load_data PAR SYMBOLE (meme routage
    Kraken/Binance, meme exclusion B4) plutot que main._load_basket -- cette
    derniere `print()` ses erreurs sur stdout du process serveur, alors qu'ici
    on doit les faire remonter dans `progress.log` ET dans le payload retourne
    (etat "actif ignore", cf. spec §4.7) au lieu de les avaler silencieusement.

    Retourne (data: {symbole: DataFrame}, ignored: [{"symbol", "error"}]).
    Un symbole en echec est SIGNALE, jamais masque (cf. rules/vigilance.md).
    """
    import main
    from .exchange import KrakenExchange

    symbols = params.get("symbols") or []
    timeframe = params.get("timeframe") or "1d"
    days = params.get("days") or 720
    source = params.get("source") or "kraken"
    ex = KrakenExchange()
    data, ignored = {}, []
    for sym in symbols:
        if progress.cancelled:
            return data, ignored
        progress.log(f"Chargement {sym} ({timeframe}, {days}j, source={source})...")
        try:
            data[sym] = main._load_data(ex, sym, timeframe, days, source=source)
        except Exception as exc:  # noqa: BLE001 -- signale, jamais masque (un actif en echec n'arrete pas les autres)
            progress.log(f"  (ignore {sym} : {exc})")
            ignored.append({"symbol": sym, "error": str(exc)})
    return data, ignored


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
        "kind": "backtest",
        "detail": detail,
        "comparison": comparison,
        "context": {
            "symbol": params.get("symbol"),
            "timeframe": params.get("timeframe") or "1d",
        },
    }


def run_compare(params, progress):
    """
    Runner du job POST /research/compare (Lot 5, spec §4.4). `params` = dict
    deja VALIDE cote route (trading/compare_page.py parse_compare_params) :
    symbol/timeframe/days/source + risque -- PAS de strategie unique, toutes
    sont comparees (equivalent `main.cmd_compare`, reutilise le meme calcul).

    Retourne {"kind": "compare", "rows": [...], "buy_hold": float,
    "context": {...}} consomme par trading/compare_page.py render_compare_done.
    """
    try:
        df = _load_ohlcv(params, progress)
    except ResearchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ResearchError(
            "Donnees indisponibles pour ce symbole/timeframe/source. "
            f"Detail : {exc}"
        ) from exc

    if df is None or len(df) < 2:
        raise ResearchError(
            "Pas assez de bougies chargees pour lancer la comparaison "
            "(symbole/timeframe/jours a verifier)."
        )

    if progress.cancelled:
        return None

    progress.log(f"Comparaison des {len(STRATEGIES)} strategies (reference Buy & Hold incluse)...")
    kw = _bt_kwargs(params)
    rows = []
    for key in STRATEGIES:
        if progress.cancelled:
            return None
        rows.append({
            "name": build_strategy(key).name,
            "metrics": Backtester(**kw).run(df, build_strategy(key)).metrics,
        })

    buy_hold = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)

    progress.log("Termine.")
    return {
        "kind": "compare",
        "rows": rows,
        "buy_hold": buy_hold,
        "context": {
            "symbol": params.get("symbol"),
            "timeframe": params.get("timeframe") or "1d",
            "period": (df.index[0], df.index[-1]),
        },
    }


def run_optimize(params, progress):
    """
    Runner du job POST /research/optimize (Lot 5, spec §4.5). `params` = dict
    deja VALIDE cote route (trading/optimize_page.py parse_optimize_params) :
    strategy/symbol/timeframe/days/source/metric/train_frac + risque
    (equivalent `main.cmd_optimize`, reutilise trading.optimizer.optimize).

    Retourne {"kind": "optimize", "result": {...}, "context": {...}} --
    `result` = EXACTEMENT le dict de trading.optimizer.optimize (best_params,
    train, test, full, train_period, test_period), aucune re-derivation.
    """
    strategy_key = (params.get("strategy") or "").lower()
    if strategy_key not in STRATEGIES:
        raise ResearchError(f"Strategie inconnue : {strategy_key or '(vide)'!r}.")

    try:
        df = _load_ohlcv(params, progress)
    except ResearchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ResearchError(
            "Donnees indisponibles pour ce symbole/timeframe/source. "
            f"Detail : {exc}"
        ) from exc

    if df is None or len(df) < 2:
        raise ResearchError(
            "Pas assez de bougies chargees pour optimiser "
            "(symbole/timeframe/jours a verifier)."
        )

    if progress.cancelled:
        return None

    from .optimizer import optimize

    metric = params.get("metric") or "sharpe"
    train_frac = params.get("train_frac")
    if train_frac is None:
        train_frac = 0.6
    progress.log(f"Optimisation {build_strategy(strategy_key).name} (critere {metric})...")
    kw = _bt_kwargs(params)
    try:
        res = optimize(df, strategy_key, train_frac=train_frac, metric=metric, **kw)
    except RuntimeError as exc:
        # Gardes de l'optimizer ("Aucune combinaison valide.") -- message repris
        # tel quel, deja actionnable (spec §4.5 : "pas assez de donnees").
        raise ResearchError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ResearchError(f"Optimisation impossible : {exc}") from exc

    if progress.cancelled:
        return None

    progress.log("Termine.")
    return {
        "kind": "optimize",
        "result": res,
        "context": {
            "symbol": params.get("symbol"),
            "timeframe": params.get("timeframe") or "1d",
        },
    }


def run_portfolio(params, progress):
    """
    Runner du job POST /research/portfolio (Lot 5, spec §4.7). `params` = dict
    deja VALIDE cote route (trading/portfolio_page.py parse_portfolio_params) :
    symbols(list)/strategy/timeframe/days/source + risque (equivalent
    `main.cmd_portfolio`, reutilise trading.portfolio.backtest_portfolio).

    Retourne {"kind": "portfolio", "result": {...}, "ignored": [...],
    "context": {...}} -- `result` = EXACTEMENT le dict de
    trading.portfolio.backtest_portfolio (per_asset/portfolio/portfolio_bh/
    correlation/equity), aucune re-derivation. `ignored` liste les symboles
    non chargeables (spec §4.7 : "actif ignore", jamais masque en silence).
    """
    strategy_key = (params.get("strategy") or "").lower()
    if strategy_key not in STRATEGIES:
        raise ResearchError(f"Strategie inconnue : {strategy_key or '(vide)'!r}.")

    symbols = params.get("symbols") or []
    if not symbols:
        raise ResearchError("Aucun symbole fourni.")

    data, ignored = _load_basket_ohlcv(params, progress)
    if progress.cancelled:
        return None
    if not data:
        raise ResearchError(
            "Aucun actif chargeable (tous les symboles ont echoue) : "
            + "; ".join(f"{i['symbol']} ({i['error']})" for i in ignored)
        )

    progress.log(f"Backtest portefeuille {build_strategy(strategy_key).name} en cours...")
    kw = _bt_kwargs(params)
    try:
        from .portfolio import backtest_portfolio
        res = backtest_portfolio(data, strategy_key, **kw)
    except Exception as exc:  # noqa: BLE001
        raise ResearchError(f"Backtest portefeuille impossible : {exc}") from exc

    if progress.cancelled:
        return None

    progress.log("Termine.")
    return {
        "kind": "portfolio",
        "result": res,
        "ignored": ignored,
        "context": {
            "symbols": symbols,
            "timeframe": params.get("timeframe") or "1d",
            "source": params.get("source") or "kraken",
        },
    }
