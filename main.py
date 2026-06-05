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
  python main.py portfolio --symbols BTC/USD,ETH/USD,SOL/USD --strategy sma --stop-loss 8 --take-profit 20
  python main.py dashboard --strategy sma --stop-loss 8 --take-profit 20
  python main.py paper     --strategy sma --timeframe 1h --stop-loss 5 --take-profit 10
  python main.py live      --strategy sma --execute
"""
import argparse
import sys

import config
from trading.exchange import KrakenExchange
from trading.strategies import build_strategy, STRATEGIES
from trading.backtester import Backtester


def _frac(pct):
    return None if pct is None else pct / 100.0


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


def _load_data(ex, symbol, timeframe, days):
    if days and days > 720:
        return ex.fetch_ohlcv_range(symbol, timeframe, since_days=days)
    return ex.fetch_ohlcv(symbol, timeframe, limit=min(days or 720, 720))


def _load_basket(ex, symbols, timeframe, days):
    data = {}
    for s in symbols:
        try:
            data[s] = _load_data(ex, s, timeframe, days)
        except Exception as e:
            print(f"  (ignore {s} : {e})")
    if not data:
        sys.exit("Aucun actif chargeable.")
    return data


def _run_all_strategies(df, **bt_kwargs):
    return [{"name": build_strategy(k).name,
             "metrics": Backtester(**bt_kwargs).run(df, build_strategy(k)).metrics}
            for k in STRATEGIES]


def cmd_backtest(args):
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days)
    result = Backtester(**_bt_kwargs(args)).run(df, build_strategy(args.strategy))
    print(result.summary())
    if args.chart:
        _save_chart(result, args.chart)


def cmd_compare(args):
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days)
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
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days)
    res = optimize(df, args.strategy, train_frac=args.train_frac, metric=args.metric, **_bt_kwargs(args))
    print(format_report(res))


def cmd_walkforward(args):
    from trading.optimizer import walk_forward, format_walk_forward
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days)
    res = walk_forward(df, args.strategy, n_windows=args.windows,
                       train_frac=args.train_frac, metric=args.metric, **_bt_kwargs(args))
    print(format_walk_forward(res))


def cmd_dashboard(args):
    from trading.dashboard import generate_dashboard
    df = _load_data(KrakenExchange(), args.symbol, args.timeframe, args.days)
    kw = _bt_kwargs(args)
    detail = Backtester(**kw).run(df, build_strategy(args.strategy))
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
    PaperTrader(KrakenExchange(), build_strategy(args.strategy), symbol=args.symbol,
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
        print(f"     Stratégie      : {build_strategy(args.strategy).name}")
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
    LiveTrader(KrakenExchange(), build_strategy(args.strategy), symbol=args.symbol,
               timeframe=args.timeframe, dry_run=dry_run, **_bt_kwargs(args)).run()


def cmd_stats(args):
    from trading.stats import load_stats, summarize, format_summary
    try:
        df = load_stats(args.file)
    except FileNotFoundError as e:
        sys.exit(str(e))
    print(format_summary(summarize(df)))


def cmd_monitor(args):
    from trading.monitor import run_monitor
    run_monitor(port=args.port, stats_path=args.stats,
                log_path=args.log, state_path=args.state)


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


def run_check(exchange, symbol):
    """
    Effectue le diagnostic. `exchange` est injecte (testable sans reseau).
    Retourne (ok: bool, lines: list[str]).
    """
    lines = ["Diagnostic InsertYourCoin", "-------------------------"]
    lines.append("Python      : " + sys.version.split()[0])
    for pkg in ("ccxt", "pandas", "numpy", "truststore"):
        lines.append(f"{pkg:11s} : {_version(pkg)}")
    try:
        import truststore  # noqa: F401
        lines.append("Protection antivirus/SSL (truststore) : active (magasin de certificats de l'OS).")
    except ImportError:
        lines.append("Protection antivirus/SSL (truststore) : INDISPONIBLE "
                     "(installe-la via pip install -r requirements.txt si un antivirus scanne le HTTPS).")
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
        sp.add_argument("--symbol", default=config.DEFAULT_SYMBOL)
        sp.add_argument("--timeframe", default=config.DEFAULT_TIMEFRAME,
                        help="1m,5m,15m,1h,4h,1d (defaut: 1d)")
        if days:
            sp.add_argument("--days", type=int, default=720)

    b = sub.add_parser("backtest"); common(b); _risk_args(b); _adv_risk_args(b)
    b.add_argument("--chart", metavar="FICHIER.png"); b.set_defaults(func=cmd_backtest)

    c = sub.add_parser("compare"); common(c); _risk_args(c); _adv_risk_args(c)
    c.set_defaults(func=cmd_compare)

    o = sub.add_parser("optimize"); common(o); _risk_args(o); _adv_risk_args(o)
    o.add_argument("--metric", default="sharpe",
                   choices=["sharpe", "sortino", "calmar", "total_return", "profit_factor"])
    o.add_argument("--train-frac", type=float, default=0.6)
    o.set_defaults(func=cmd_optimize)

    w = sub.add_parser("walkforward"); common(w); _risk_args(w); _adv_risk_args(w)
    w.add_argument("--metric", default="sharpe",
                   choices=["sharpe", "sortino", "calmar", "total_return", "profit_factor"])
    w.add_argument("--windows", type=int, default=4, help="nombre de fenetres hors-echantillon")
    w.add_argument("--train-frac", type=float, default=0.5, help="part initiale d'entrainement")
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

    st = sub.add_parser("stats")
    st.add_argument("--file", default="paper_stats.csv",
                    help="CSV de stats a analyser (defaut: paper_stats.csv)")
    st.set_defaults(func=cmd_stats)

    mo = sub.add_parser("monitor")
    mo.add_argument("--port", type=int, default=8765)
    mo.add_argument("--stats", default=None,
                    help="CSV de stats (defaut: paper_stats.csv a la racine)")
    mo.add_argument("--log", default=None,
                    help="journal du paper (defaut: paper_trades.log a la racine)")
    mo.add_argument("--state", default=None,
                    help="etat du paper (defaut: paper_state.json a la racine)")
    mo.set_defaults(func=cmd_monitor)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
