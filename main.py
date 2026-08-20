#!/usr/bin/env python3
"""
InsertYourCoin — point d'entree du systeme de trading crypto (Kraken).

Commandes :
  check       diagnostic d'installation + connexion Kraken (a lancer en premier)
  backtest    tester une stratégie sur l'historique
  compare     comparer toutes les stratégies
  optimize    meilleurs parametres AVEC validation hors-echantillon (train/test)
  walkforward optimisation glissante (test hors-echantillon le plus realiste)
  dashboard   tableau de bord HTML
  portfolio   backtester un panier de cryptos (diversification)
  paper       paper trading (argent fictif, temps reel)
  live        trading reel (dry-run par defaut, double confirmation)
  stats       synthese descriptive du CSV de stats (labo de stats)
  monitor     serveur web leger de suivi du paper trading en direct

Exemples :
  python main.py backtest  --strategy sma --stop-loss 8 --take-profit 20 --chart bt.png
  python main.py backtest  --strategy sma --trailing-stop 12 --position-sizing vol --target-vol 40
  python main.py walkforward --strategy sma --windows 4
  python main.py walkforward --source binance --days 2900 --strategy sma --fixed "fast=50,slow=200" --symbols BTC/USD,ETH/USD,SOL/USD
  python main.py walkforward --strategy sma --timeframe 1d --fixed "fast=50,slow=200"
  python main.py walkforward --strategy tsmom --timeframe 1d --fixed "lookback=365"
  python main.py walkforward --strategy sma --fixed "fast=50,slow=200" --holdout 20 --symbols BTC/USD,ETH/USD,SOL/USD
  python main.py walkforward --strategy sma --fixed "fast=50,slow=200" --holdout 20 --final
  python main.py portfolio --symbols BTC/USD,ETH/USD,SOL/USD --strategy sma --stop-loss 8 --take-profit 20
  python main.py dashboard --strategy sma --stop-loss 8 --take-profit 20
  python main.py paper     --strategy sma --timeframe 1h --stop-loss 5 --take-profit 10
  python main.py live      --strategy sma --execute
"""
import argparse
import os
import sys
from pathlib import Path

# Windows : forcer stdout/stderr en UTF-8 -- la console cp1252 ne peut pas encoder
# certains caracteres des sorties (sigma de Bollinger, fleches du walk-forward) et
# leve UnicodeEncodeError. Cf. SQA BUG-004. errors='replace' => jamais de crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import config
from trading.exchange import KrakenExchange
from trading.strategies import build_strategy, STRATEGIES
from trading.backtester import Backtester


def _frac(pct):
    return None if pct is None else pct / 100.0


def _parse_fixed(spec):
    """
    Parse une chaine "k1=v1,k2=v2" en dict (int si entier, sinon float).
    Ex: "fast=50,slow=200" -> {"fast": 50, "slow": 200} ;
        "lookback=365"     -> {"lookback": 365}.
    Retourne None si `spec` est None/vide (mode optimise par defaut).
    """
    if not spec:
        return None
    out = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            sys.exit(f"--fixed : '{part}' invalide (attendu k=v).")
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        try:
            out[k] = int(v)
        except ValueError:
            try:
                out[k] = float(v)
            except ValueError:
                sys.exit(f"--fixed : valeur non numerique pour '{k}' : '{v}'.")
    return out or None


def _bt_kwargs(args):
    ps = getattr(args, "position_sizing", "none")
    tv = getattr(args, "target_vol", None)
    return dict(
        stop_loss=_frac(args.stop_loss),
        take_profit=_frac(args.take_profit),
        trailing_stop=_frac(getattr(args, "trailing_stop", None)),
        position_sizing=(None if ps in (None, "none") else ps),
        target_vol=(tv / 100.0 if tv is not None else None),
    )


def _load_data(ex, symbol, timeframe, days, source="kraken"):
    # source="binance" : historique LONG pour la RECHERCHE (Binance USDT, sans cle ;
    # l'execution reelle reste Kraken USD). On mappe le symbole et on pagine depuis
    # le debut du listing. `ex` (Kraken) est ignore sur ce chemin -- le paper/live ne
    # passent jamais par source=binance.
    if source == "binance":
        from trading.history import fetch_long_ohlcv
        df = fetch_long_ohlcv(symbol, timeframe, since_days=days)
    else:
        # B11/FIX2) Router selon les BARRES ATTENDUES, pas les jours : en intraday
        # (--timeframe 1h --days 700), un fetch_ohlcv(limit=720) ne couvre que ~30
        # jours (720 bougies horaires) -- troncature silencieuse. On bascule sur la
        # pagination des qu'on attend plus de 720 bougies (qui, elle, avertit B11 si
        # la couverture reste courte). Sinon fetch_ohlcv simple suffit.
        expected_bars = (days * 86400 / KrakenExchange._timeframe_seconds(timeframe)) if days else 0
        if expected_bars > 720:
            df = ex.fetch_ohlcv_range(symbol, timeframe, since_days=days)
        else:
            df = ex.fetch_ohlcv(symbol, timeframe, limit=min(days or 720, 720))
    # B4) la DERNIERE bougie est potentiellement EN FORMATION (non close) : on
    # l'exclut de tout backtest/optimisation (convention unique backtest == paper ;
    # le paper fait SA propre exclusion dans sa boucle, ne pas la doubler ici ET la-bas).
    # Vaut pour les deux sources (Binance re-telecharge toujours sa derniere bougie).
    return df.iloc[:-1] if len(df) > 1 else df


def _load_basket(ex, symbols, timeframe, days, source="kraken"):
    # Herite de l'exclusion B4 (bougie en formation) via _load_data.
    data = {}
    for s in symbols:
        try:
            data[s] = _load_data(ex, s, timeframe, days, source=source)
        except Exception as e:
            print(f"  (ignore {s} : {e})")
    if not data:
        sys.exit("Aucun actif chargeable.")
    return data


def _run_all_strategies(df, **bt_kwargs):
    return [{"name": build_strategy(k).name,
             "metrics": Backtester(**bt_kwargs).run(df, build_strategy(k)).metrics}
            for k in STRATEGIES]


def _strategy_params(args):
    """--params "k=v,..." (meme format que --fixed du walk-forward) -> dict pour
    build_strategy. Permet au paper/live/backtest de tourner EXACTEMENT la
    config validee par le juge (ex. --params "fast=50,slow=200,band=2")."""
    return _parse_fixed(getattr(args, "params", None))


def cmd_backtest(args):
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days,
                    source=getattr(args, "source", "kraken"))
    result = Backtester(**_bt_kwargs(args)).run(df, build_strategy(args.strategy, _strategy_params(args)))
    print(result.summary())
    if args.chart:
        _save_chart(result, args.chart)


def cmd_compare(args):
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days,
                    source=getattr(args, "source", "kraken"))
    rows = _run_all_strategies(df, **_bt_kwargs(args))
    print(f"\nComparaison sur {args.symbol} ({args.timeframe}), "
          f"{df.index[0].date()} -> {df.index[-1].date()}")
    head = (f"\n{'Stratégie':24s} | {'Rendement':>10s} | {'Sharpe':>6s} | "
            f"{'DD max':>7s} | {'PF':>5s} | {'Trades':>6s} | {'Reussite':>8s}")
    print(head); print("-" * len(head))
    for r in rows:
        m = r["metrics"]
        pf = "∞" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"{r['name']:24s} | {m['total_return']*100:+9.1f}% | {m['sharpe']:6.2f} | "
              f"{m['max_drawdown']*100:6.1f}% | {pf:>5s} | {m['n_trades']:6d} | {m['win_rate']*100:7.0f}%")
    bh = df['close'].iloc[-1] / df['close'].iloc[0] - 1
    print("-" * len(head)); print(f"{'Buy & Hold (reference)':24s} | {bh*100:+9.1f}%")
    print("\nRappel : de bons chiffres passes ne garantissent jamais le futur.\n")


def cmd_optimize(args):
    from trading.optimizer import optimize, format_report
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days,
                    source=getattr(args, "source", "kraken"))
    res = optimize(df, args.strategy, train_frac=args.train_frac, metric=args.metric, **_bt_kwargs(args))
    print(format_report(res))


def cmd_walkforward(args):
    from trading.optimizer import (walk_forward, format_walk_forward,
                                   walk_forward_multi, format_walk_forward_multi,
                                   holdout_check, format_holdout, holdout_split)
    fixed = _parse_fixed(getattr(args, "fixed", None))
    holdout_frac = (getattr(args, "holdout", 0.0) or 0.0) / 100.0
    if not (0.0 <= holdout_frac < 0.9):
        sys.exit("--holdout : pourcentage attendu dans [0, 90[.")
    if getattr(args, "final", False) and holdout_frac <= 0:
        sys.exit("--final exige --holdout > 0 (sans holdout, pas de segment sacre).")

    ex = KrakenExchange()
    source = getattr(args, "source", "kraken")
    if getattr(args, "symbols", None):
        # Multi-actifs : --symbols prime, --symbol est ignore.
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        data = _load_basket(ex, symbols, args.timeframe, args.days, source=source)
    else:
        data = {args.symbol: _load_data(ex, args.symbol, args.timeframe, args.days,
                                        source=source)}

    # B7) holdout SACRE : les dernieres bougies sont RETIREES avant tout --
    # ni l'optimisation ni les fenetres OOS du walk-forward ne les voient JAMAIS.
    research = {}
    for sym, df in data.items():
        if holdout_frac > 0:
            cut = holdout_split(len(df), holdout_frac)
            tag = f" [{sym}]" if len(data) > 1 else ""
            print(f"Holdout reserve{tag} : {len(df) - cut} bougies "
                  f"({args.holdout:g}% recents) -- JAMAIS utilises pour la recherche")
            research[sym] = df.iloc[:cut]
        else:
            research[sym] = df

    wf_kwargs = dict(n_windows=args.windows, train_frac=args.train_frac,
                     metric=args.metric, fixed_params=fixed, **_bt_kwargs(args))
    if len(data) > 1:
        res = walk_forward_multi(research, args.strategy, **wf_kwargs)
        print(format_walk_forward_multi(res))
    else:
        res = walk_forward(research[next(iter(data))], args.strategy, **wf_kwargs)
        print(format_walk_forward(res))

    if getattr(args, "final", False):
        # B7) evaluation UNIQUE sur le holdout (warm-up B1 etendu en amont).
        for sym, df in data.items():
            if len(data) > 1:
                print(f"\n--- {sym} ---")
            try:
                hres = holdout_check(df, holdout_frac, args.strategy,
                                     fixed_params=fixed, metric=args.metric,
                                     **_bt_kwargs(args))
                print(format_holdout(hres))
            except RuntimeError as e:
                print(f"Validation finale impossible pour {sym} : {e}")


def cmd_dashboard(args):
    from trading.dashboard import generate_dashboard
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days)
    kw = _bt_kwargs(args)
    detail = Backtester(**kw).run(df, build_strategy(args.strategy, _strategy_params(args)))
    comparison = _run_all_strategies(df, **kw)
    path = generate_dashboard(detail, comparison,
                              {"symbol": args.symbol, "timeframe": args.timeframe}, path=args.out)
    print(f"Tableau de bord genere : {path}")
    print("Ouvre-le dans ton navigateur (connexion internet requise pour les graphiques).")


def cmd_portfolio(args):
    from trading.portfolio import backtest_portfolio, format_portfolio
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    data = _load_basket(KrakenExchange(), symbols, args.timeframe, args.days)
    res = backtest_portfolio(data, args.strategy, **_bt_kwargs(args))
    print(format_portfolio(res))


def cmd_paper(args):
    from trading.paper_trader import PaperTrader
    PaperTrader(KrakenExchange(), build_strategy(args.strategy, _strategy_params(args)), symbol=args.symbol,
                timeframe=args.timeframe, **_bt_kwargs(args)).run()


def cmd_live(args):
    from trading.live_trader import LiveTrader
    if not config.KRAKEN_API_KEY or not config.KRAKEN_API_SECRET:
        sys.exit("Cles API manquantes. Renseigne .env (voir .env.example) avant le mode live.")
    dry_run = not args.execute
    if args.execute:
        print("\n" + "=" * 64)
        print("  ⚠️  MODE REEL : des ordres vont etre passes avec de l'ARGENT REEL.")
        print(f"     Paire          : {args.symbol}")
        print(f"     Stratégie      : {build_strategy(args.strategy, _strategy_params(args)).name}")
        print(f"     Stop / Objectif: {args.stop_loss or '—'}% / {args.take_profit or '—'}%")
        if args.trailing_stop:
            print(f"     Trailing stop  : {args.trailing_stop}%")
        if args.position_sizing == "vol":
            tv = args.target_vol if args.target_vol is not None else config.TARGET_VOL * 100
            print(f"     Sizing         : volatilite cible {tv:g}%")
        print(f"     Ordre max      : {config.MAX_TRADE_VALUE_USD} $ | Exposition max : {config.MAX_POSITION_VALUE_USD} $")
        print("=" * 64)
        if input('  Tape exactement  OUI JE CONFIRME  pour continuer : ').strip() != "OUI JE CONFIRME":
            sys.exit("Annule. (Aucun ordre envoye.)")
    trader = LiveTrader(KrakenExchange(), build_strategy(args.strategy, _strategy_params(args)), symbol=args.symbol,
                        timeframe=args.timeframe, dry_run=dry_run, **_bt_kwargs(args))
    # BUG-017 (P0, gate Lot 8B FAIL-1) : reconcile() AVANT run(), sinon une
    # position ouverte reprise apres un restart tourne SANS stop ni trailing
    # (_risk_overlay sort immediatement si entry_price est None). reconcile()
    # ne passe JAMAIS d'ordre (purement defensif) et l'exchange fait foi.
    trader.reconcile()
    trader.run()


def _live_root(args):
    """Racine des donnees pour les commandes live conteneur (--root, defaut
    le repertoire courant -- le service `live` fixe working_dir: /data,
    docs/design/LOT8B_LIVE_CONTENEUR_SPEC.md §4)."""
    return Path(args.root) if getattr(args, "root", None) else Path.cwd()


def _live_arm_params(args):
    """
    Params destines a live/armed.json (trading/live_control.write_armed_
    marker) -- MEMES UNITES que build_live_command (pourcentages bruts, PAS
    des fractions) : `args.stop_loss` vaut par ex. 5 pour 5%, identique a ce
    que parse_live_params (flux web local) produit deja. Ne PAS reutiliser
    _bt_kwargs ici (il convertit en fractions pour le backtester -- unite
    differente, cf. LOT8B §2.2 et research_page.parse_risk_fields).
    """
    ps = getattr(args, "position_sizing", "none")
    return {
        "strategy": args.strategy, "symbol": args.symbol, "timeframe": args.timeframe,
        "stop_loss": args.stop_loss, "take_profit": args.take_profit,
        "trailing_stop": getattr(args, "trailing_stop", None),
        "position_sizing": (None if ps in (None, "none") else ps),
        "target_vol": getattr(args, "target_vol", None),
    }


def cmd_live_arm(args):
    """
    `main.py live-arm` -- armement CLI interactif, one-shot (LOT8B §2.3).
    Ecrit UNIQUEMENT le marqueur live/armed.json ; ne trade JAMAIS lui-meme
    (le superviseur `live-run`, deja tournant sous Docker restart:unless-
    stopped, (re)lance/reprend `main.py live [--execute]`). `cmd_live`
    (mode local, main.py:259) reste INCHANGE -- ce chemin est SEPARE, pas un
    refactor de cmd_live.
    """
    from trading import live_control
    from trading.options import keys_configured
    root = _live_root(args)

    if args.dry:
        # Marqueur mode=dry : AUCUNE phrase exigee (aucun ordre possible en
        # dry-run, live_trader.py `_rebalance` ne passe jamais d'ordre reel).
        params = _live_arm_params(args)
        live_control.write_armed_marker(root, params, mode="dry",
                                        armed_via="cli-interactive-dry")
        print(f"Marqueur DRY ecrit ({live_control.armed_marker_path(root)}).")
        print("Le superviseur (live-run) demarrera en simulation des le "
              "prochain cycle (~2s).")
        return

    if not keys_configured():
        sys.exit("Cles API manquantes. Renseigne .env (voir .env.example) avant le mode live.")

    print("\n" + "=" * 64)
    print("  ⚠️  ARMEMENT REEL : le superviseur (live-run) va passer de VRAIS")
    print("     ordres des que ce marqueur existe, et le RELANCERA")
    print("     AUTOMATIQUEMENT (Docker restart:unless-stopped inclus) tant")
    print("     que tu ne le desarmes pas (live-disarm ou bouton web Arreter).")
    print(f"     Paire          : {args.symbol}")
    print(f"     Stratégie      : {build_strategy(args.strategy).name}")
    print(f"     Stop / Objectif: {args.stop_loss or '—'}% / {args.take_profit or '—'}%")
    if args.trailing_stop:
        print(f"     Trailing stop  : {args.trailing_stop}%")
    print(f"     Ordre max      : {config.MAX_TRADE_VALUE_USD} $ | Exposition max : {config.MAX_POSITION_VALUE_USD} $")
    print("=" * 64)
    if input('  Tape exactement  OUI JE CONFIRME  pour armer : ').strip() != "OUI JE CONFIRME":
        sys.exit("Annule. (Aucun marqueur ecrit.)")

    params = _live_arm_params(args)
    live_control.write_armed_marker(root, params, mode="reel", armed_via="cli-interactive")
    print(f"Marqueur REEL ecrit ({live_control.armed_marker_path(root)}).")
    print("Le superviseur (live-run) demarrera/relancera le live des le "
          "prochain cycle (~2s).")


def cmd_live_disarm(args):
    """`main.py live-disarm` (LOT8B §2.5) : supprime le marqueur. Le
    superviseur termine l'enfant en cours SANS vendre (arreter n'est pas
    liquider) et n'en relance aucun tant qu'il n'est pas re-arme."""
    from trading import live_control
    root = _live_root(args)
    live_control.remove_armed_marker(root)
    print("Marqueur d'armement supprime.")
    print("Le superviseur (live-run) terminera l'enfant en cours (si un "
          "vit) sous ~2s -- SANS vendre. La position ouverte sur Kraken, "
          "le cas echeant, reste : gere-la sur Kraken si besoin.")


def cmd_live_run(args):
    """`main.py live-run` -- command du service `live` (LOT8B §2.4).
    Bloquant : boucle tant que le conteneur tourne, arret propre sur SIGTERM
    (Docker `restart: unless-stopped` + `init: true` -> propagation correcte)."""
    from trading import live_supervisor
    root = Path(args.root) if getattr(args, "root", None) else None
    kwargs = {}
    if getattr(args, "check_interval", None) is not None:
        kwargs["check_interval"] = args.check_interval
    sys.exit(live_supervisor.run_supervisor(root=root, **kwargs))


def cmd_stats(args):
    from trading.stats import load_stats, summarize, format_summary
    try:
        df = load_stats(args.file)
    except FileNotFoundError as e:
        sys.exit(str(e))
    print(format_summary(summarize(df)))


def _resolve_allowed_hosts(cli_hosts):
    """
    Fusionne les hotes additionnels CLI (--allowed-host, repetable) et la
    variable d'env IYC_ALLOWED_HOSTS (liste separee par virgules) --
    deploiement derriere un reverse-proxy EXISTANT (SWAG/serveur mutualise,
    cf. docs/DEPLOY_DOCKER.md). Les deux sources s'AJOUTENT (jamais de
    remplacement) ; vide des deux cotes -> tuple vide -> host_allowed()
    retombe sur son defaut strict (127.0.0.1/localhost), comportement
    INCHANGE pour tout usage local qui ne definit ni l'un ni l'autre.
    """
    hosts = list(cli_hosts or [])
    env_val = os.environ.get("IYC_ALLOWED_HOSTS", "")
    for h in env_val.split(","):
        h = h.strip()
        if h:
            hosts.append(h)
    return tuple(hosts)


def cmd_monitor(args):
    from trading.monitor import run_monitor
    run_monitor(port=args.port, host=args.host, stats_path=args.stats,
                log_path=args.log, state_path=args.state,
                allowed_hosts=_resolve_allowed_hosts(args.allowed_host),
                live_root=args.live_root)


def diagnose_error(exc):
    """
    Classe une exception de connexion en (categorie, message actionnable FR).
    Fonction pure (pas de reseau) -> testable directement.
    """
    text = str(exc)
    low = text.lower()
    if "certificate_verify_failed" in low or "certificate verify failed" in low:
        return ("ssl",
                "Interception SSL detectee (antivirus/proxy qui re-signe le HTTPS, ex. Avast).\n"
                "  truststore est cense regler ca via le magasin de certificats de l'OS.\n"
                "  -> Verifie l'installation dans le venv : pip install -r requirements.txt\n"
                "  -> Voir SETUP.md, section Antivirus/SSL.\n"
                "  Ne PAS desactiver VERIFY_SSL (la verification doit rester active).")
    short = text if len(text) <= 200 else text[:200] + "..."
    return ("network",
            "Connexion a Kraken impossible (reseau ou indisponibilite du service).\n"
            "  -> Verifie ta connexion internet, puis reessaie.\n"
            "  Detail : " + short)


def _version(pkg):
    """Version d'un paquet installe, ou 'absent' s'il n'est pas trouve."""
    import importlib.metadata
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return "absent"


def truststore_active() -> bool:
    """Vrai si truststore est installe/importable (aucune valeur sensible ici).
    Reutilise par diagnostic_static_lines() ET par l'ecran web Accueil/Diagnostic
    (trading/diagnostics_web.py) pour afficher l'etat sans appel reseau."""
    try:
        import truststore  # noqa: F401
        return True
    except ImportError:
        return False


def diagnostic_static_lines() -> list:
    """
    Lignes de diagnostic SANS RESEAU : version Python, versions des paquets,
    etat truststore. Extrait de run_check() pour etre reutilisable tel quel par
    l'ecran web /check (etat affiche AVANT tout clic, donc AVANT tout appel
    Kraken -- cf. trading/diagnostics_web.py et trading/check_page.py).
    """
    lines = ["Diagnostic InsertYourCoin", "-------------------------"]
    lines.append("Python      : " + sys.version.split()[0])
    for pkg in ("ccxt", "pandas", "numpy", "truststore"):
        lines.append(f"{pkg:11s} : {_version(pkg)}")
    if truststore_active():
        lines.append("Protection antivirus/SSL (truststore) : active (magasin de certificats de l'OS).")
    else:
        lines.append("Protection antivirus/SSL (truststore) : INDISPONIBLE "
                     "(installe-la via pip install -r requirements.txt si un antivirus scanne le HTTPS).")
    return lines


def run_check(exchange, symbol):
    """
    Effectue le diagnostic. `exchange` est injecte (testable sans reseau).
    Retourne (ok: bool, lines: list[str]).
    """
    lines = diagnostic_static_lines()
    lines.append("")
    try:
        price = exchange.fetch_price(symbol)
        lines.append(f"OK : connexion Kraken fonctionnelle ({symbol} = {price})")
        return (True, lines)
    except Exception as exc:  # noqa: BLE001 -- on classe toute erreur en message actionnable
        category, message = diagnose_error(exc)
        lines.append(f"ECHEC connexion Kraken [{category}] :")
        lines.append("  " + message.replace("\n", "\n  "))
        return (False, lines)


def cmd_check(args):
    ok, lines = run_check(KrakenExchange(), args.symbol)
    print("\n".join(lines))
    sys.exit(0 if ok else 1)


def _save_chart(result, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    df = result.df
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7), height_ratios=[3, 1], sharex=True)
    a1.plot(df.index, df["equity"], label="Stratégie", linewidth=1.6)
    a1.plot(df.index, df["buy_hold"], label="Buy & Hold", linewidth=1.2, alpha=.7)
    a1.set_title(f"Backtest — {result.strategy_name}")
    a1.set_ylabel("Portefeuille ($)"); a1.legend(); a1.grid(alpha=.3)
    a2.fill_between(df.index, df["drawdown"] * 100, 0, color="crimson", alpha=.4)
    a2.set_ylabel("Drawdown (%)"); a2.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(path, dpi=130)
    print(f"Graphique enregistre : {path}")


def _source_arg(sp):
    """Source de donnees pour l'ANALYSE (backtest/compare/optimize/walkforward).

    'kraken' (defaut) = donnees Kraken (~720 bougies max, l'exchange d'execution).
    'binance' = historique LONG pour la RECHERCHE (Binance USDT, sans cle, depuis
    2017-08 en daily) -- l'execution reelle reste Kraken USD (ecart minime affiche).
    Le paper/live ne sont PAS concernes (100% Kraken).
    """
    sp.add_argument("--source", choices=["kraken", "binance"], default="kraken",
                    help="source de donnees d'analyse : 'kraken' (defaut) ou 'binance' "
                         "(historique long pour la recherche, sans cle)")


def _risk_args(sp):
    sp.add_argument("--stop-loss", type=float, default=None, metavar="PCT",
                    help="stop-loss en %% (ex: 8)")
    sp.add_argument("--take-profit", type=float, default=None, metavar="PCT",
                    help="take-profit en %% (ex: 20)")


def _adv_risk_args(sp):
    """Options de risque avancees (analyse + paper/live)."""
    sp.add_argument("--trailing-stop", type=float, default=None, metavar="PCT",
                    help="stop suiveur en %% (ex: 12)")
    sp.add_argument("--position-sizing", choices=["none", "vol"], default="none",
                    help="'vol' = dimensionnement par volatilite")
    sp.add_argument("--target-vol", type=float, default=None, metavar="PCT",
                    help="volatilite annuelle cible en %% si --position-sizing vol (ex: 40)")


def build_parser():
    p = argparse.ArgumentParser(description="Systeme de trading crypto (Kraken)")
    sub = p.add_subparsers(dest="command", required=True)

    ch = sub.add_parser("check")
    ch.add_argument("--symbol", default=config.DEFAULT_SYMBOL)
    ch.set_defaults(func=cmd_check)

    def common(sp, days=True):
        sp.add_argument("--strategy", default="sma", choices=list(STRATEGIES))
        sp.add_argument("--params", default=None, metavar="K=V,...",
                        help='parametres de la strategie, meme format que --fixed '
                             '(ex. "fast=50,slow=200,band=2" -- band en multiples '
                             'du cout de frais aller-retour, etude #6)')
        sp.add_argument("--symbol", default=config.DEFAULT_SYMBOL)
        sp.add_argument("--timeframe", default=config.DEFAULT_TIMEFRAME,
                        help="1m,5m,15m,1h,4h,1d (defaut: 1d)")
        if days:
            sp.add_argument("--days", type=int, default=720)

    b = sub.add_parser("backtest"); common(b); _source_arg(b); _risk_args(b); _adv_risk_args(b)
    b.add_argument("--chart", metavar="FICHIER.png"); b.set_defaults(func=cmd_backtest)

    c = sub.add_parser("compare"); common(c); _source_arg(c); _risk_args(c); _adv_risk_args(c)
    c.set_defaults(func=cmd_compare)

    o = sub.add_parser("optimize"); common(o); _source_arg(o); _risk_args(o); _adv_risk_args(o)
    o.add_argument("--metric", default="sharpe",
                   choices=["sharpe", "sortino", "calmar", "total_return", "profit_factor"])
    o.add_argument("--train-frac", type=float, default=0.6)
    o.set_defaults(func=cmd_optimize)

    w = sub.add_parser("walkforward"); common(w); _source_arg(w); _risk_args(w); _adv_risk_args(w)
    w.add_argument("--metric", default="sharpe",
                   choices=["sharpe", "sortino", "calmar", "total_return", "profit_factor"])
    w.add_argument("--windows", type=int, default=4, help="nombre de fenetres hors-echantillon")
    w.add_argument("--train-frac", type=float, default=0.5, help="part initiale d'entrainement")
    w.add_argument("--fixed", default=None, metavar="k=v,...",
                   help="parametres FIGES (sans optimisation, anti-data-mining). "
                        "Ex: --fixed \"fast=50,slow=200\" ou --fixed \"lookback=365\"")
    w.add_argument("--holdout", type=float, default=0.0, metavar="PCT",
                   help="%% de bougies RECENTES reservees (holdout sacre, jamais vues "
                        "par la recherche). Ex: 20")
    w.add_argument("--final", action="store_true",
                   help="VALIDATION FINALE unique sur le holdout (exige --holdout ; de "
                        "preference avec --fixed). A ne faire qu'UNE fois par strategie.")
    w.add_argument("--symbols", default=None, metavar="A,B,C",
                   help="plusieurs paires separees par des virgules (robustesse "
                        "multi-actifs ; ignore --symbol). Ex: BTC/USD,ETH/USD,SOL/USD")
    w.set_defaults(func=cmd_walkforward)

    d = sub.add_parser("dashboard"); common(d); _risk_args(d); _adv_risk_args(d)
    d.add_argument("--out", default="dashboard.html"); d.set_defaults(func=cmd_dashboard)

    pf = sub.add_parser("portfolio"); common(pf); _risk_args(pf); _adv_risk_args(pf)
    pf.add_argument("--symbols", default="BTC/USD,ETH/USD,SOL/USD",
                    help="paires separees par des virgules")
    pf.set_defaults(func=cmd_portfolio)

    pa = sub.add_parser("paper"); common(pa, days=False); _risk_args(pa); _adv_risk_args(pa)
    pa.set_defaults(func=cmd_paper)

    li = sub.add_parser("live"); common(li, days=False); _risk_args(li); _adv_risk_args(li)
    li.add_argument("--execute", action="store_true",
                    help="DESACTIVE le dry-run et passe de VRAIS ordres (double confirmation)")
    li.set_defaults(func=cmd_live)

    # --- Lot 8B : live conteneurise (superviseur + armement persistant) ---
    la = sub.add_parser("live-arm", help="arme le live conteneurise (one-shot, interactif)")
    common(la, days=False)
    _risk_args(la); _adv_risk_args(la)
    la.add_argument("--dry", action="store_true",
                    help="arme en SIMULATION (aucune phrase exigee, aucun ordre reel possible)")
    la.add_argument("--root", default=None,
                    help="racine des donnees (defaut: repertoire courant -- "
                         "le service `live` fixe working_dir: /data)")
    la.set_defaults(func=cmd_live_arm)

    ld = sub.add_parser("live-disarm", help="desarme le live conteneurise (supprime le marqueur)")
    ld.add_argument("--root", default=None)
    ld.set_defaults(func=cmd_live_disarm)

    lr = sub.add_parser("live-run", help="superviseur du live conteneurise (command du service `live`)")
    lr.add_argument("--root", default=None)
    lr.add_argument("--check-interval", type=float, default=None,
                    help="cadence de surveillance marqueur/sentinelle en secondes (defaut: 2)")
    lr.set_defaults(func=cmd_live_run)

    st = sub.add_parser("stats")
    st.add_argument("--file", default="paper_stats.csv",
                    help="CSV de stats a analyser (defaut: paper_stats.csv)")
    st.set_defaults(func=cmd_stats)

    mo = sub.add_parser("monitor")
    mo.add_argument("--port", type=int, default=8765)
    mo.add_argument("--host", default="127.0.0.1",
                    help="adresse d'ecoute (defaut: 127.0.0.1, local uniquement). "
                         "0.0.0.0 = accessible depuis le reseau -- a n'utiliser "
                         "QUE derriere un reverse proxy TLS+auth (ex. deploiement "
                         "Docker) ; jamais expose nu sur internet.")
    mo.add_argument("--stats", default=None,
                    help="CSV de stats (defaut: paper_stats.csv a la racine)")
    mo.add_argument("--log", default=None,
                    help="journal du paper (defaut: paper_trades.log a la racine)")
    mo.add_argument("--state", default=None,
                    help="etat du paper (defaut: paper_state.json a la racine)")
    mo.add_argument("--allowed-host", action="append", default=[],
                    help="hote HTTP additionnel accepte (anti DNS-rebinding), "
                         "en plus de 127.0.0.1/localhost -- repetable. Utile "
                         "derriere un reverse-proxy EXISTANT (ex. SWAG) qui "
                         "transmet un Host different (ex. iyc.eunivers.net). "
                         "Se cumule avec la variable d'env IYC_ALLOWED_HOSTS "
                         "(liste separee par virgules). Vide par defaut -> "
                         "comportement inchange.")
    mo.add_argument("--live-root", default=None,
                    help="racine des fichiers live (armed.json, live_state.json, "
                         "live_trades.log, live_stats.csv -- Lot 8B, deploiement "
                         "conteneurise du service `live`, ex. /data). Absent -> "
                         "comportement local INCHANGE (repertoire du projet).")
    mo.set_defaults(func=cmd_monitor)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
