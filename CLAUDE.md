# CLAUDE.md — InsertYourCoin (trading crypto Kraken)

> Claude Code lit ce fichier au début de chaque session. Il fait foi pour tout le projet.

## Pourquoi (WHY)
Outil de trading algorithmique crypto sur Kraken. Objectif honnête : avec du
**capital qu'on peut se permettre de perdre**, tenter d'amortir au mieux les coûts
de développement du projet "Regnum". **Ce n'est PAS un revenu/salaire.** Pas de
promesse de gain régulier ni garanti.

## Quoi (WHAT)
Backtest de stratégies classiques, gestion du risque, diversification de portefeuille,
optimisation honnête (train/test + walk-forward), paper trading et live (verrouillé),
tableau de bord HTML. Connexion Kraken via `ccxt`.

## Comment (HOW)
CLI unique : `python main.py <commande> [options]`. Données publiques (prix/historique)
sans clés ; soldes et ordres réels via clés API dans `.env`. Voir `SETUP.md`.

---

## ⚠️ Garde-fous — NON négociables (maintenir cette ligne)
1. **Honnêteté avant tout.** Ne jamais survendre. Si une stratégie n'a pas d'edge,
   le dire. Le **walk-forward (perf hors-échantillon) est le juge** — pas le backtest in-sample.
2. **Risque d'abord.** Concevoir pour préserver le capital (stop, trailing, sizing,
   diversification) ; le rendement est second. Réduire le drawdown, pas viser le jackpot.
3. **Jamais de clés en dur.** Lues depuis `.env` (jamais commité — voir `.gitignore`).
4. **Live verrouillé.** `live` est en dry-run par défaut ; `--execute` exige une
   double confirmation ; plafonds dans `config.py`. Ne jamais relâcher ces garde-fous.
5. **`config.VERIFY_SSL = True`** sur cette machine. (Le `False` n'était qu'un
   contournement du proxy d'un bac à sable — ne jamais le commiter/réactiver ici.)
6. Pas de conseil en investissement personnalisé. Décisions et risque appartiennent à l'utilisateur.

---

## Architecture
```
main.py              CLI : backtest, compare, optimize, walkforward, dashboard, portfolio, paper, live
config.py            paramètres, risque (stop/trailing/sizing), garde-fous live
trading/
  indicators.py      SMA, EMA, RSI, MACD, Bollinger
  strategies.py      4 stratégies (long/flat) + registre STRATEGIES
  exchange.py        Kraken via ccxt (données, soldes, ordres)
  backtester.py      moteur event-driven : stop-loss/take-profit/trailing intra-bougie, sizing par vol
  optimizer.py       optimize (train/test) + walk_forward (glissant)
  portfolio.py       backtest multi-actifs équipondéré + corrélation
  dashboard.py       génération du tableau de bord HTML (Chart.js via CDN)
  paper_trader.py    paper trading + classe de base _Trader (boucle commune)
  live_trader.py     trading réel (hérite de _Trader)
```
Données : décision à la clôture de t, exécution à l'ouverture de t+1 (pas de lookahead).
Tout-ou-rien sauf sizing "vol". Frais Kraken 0,26 % pris en compte.

## Commandes utiles
```bash
python main.py backtest  --strategy sma --stop-loss 8 --take-profit 20 --chart bt.png
python main.py walkforward --strategy sma --windows 4        # le test honnête
python main.py portfolio --symbols BTC/USD,ETH/USD,SOL/USD --strategy sma --stop-loss 8 --take-profit 20
python main.py paper     --strategy sma --timeframe 1h --stop-loss 5 --take-profit 10
```

---

## État actuel (à jour)
- Backtest/optimize/walkforward/portfolio/dashboard : faits et testés sur données réelles Kraken.
- Paper/live : stop-loss + take-profit OK. **Trailing stop et sizing par vol PAS encore
  câblés dans paper/live** (présents dans le backtest seulement). → tâche prioritaire.
- **Constat honnête mesuré** : la stratégie SMA n'a **pas d'edge fiable** sur la crypto
  récente (walk-forward : 0 % de fenêtres profitables sur ETH). Les outils de risque
  **lissent** (vol ÷3, drawdown ÷2) mais ne **créent pas** de profit. Diversification
  BTC/ETH/SOL utile mais corrélation ~0,8 (lisse, ne protège pas d'un krach systémique).
  Ne pas raconter d'histoires là-dessus à l'utilisateur.

## Prochaines étapes (ordre suggéré)
1. Câbler trailing stop + sizing par volatilité dans `paper_trader.py` / `live_trader.py`.
2. Lancer le paper trading en continu sur vraies données et l'observer plusieurs semaines.
3. Filtre de tendance long terme (ne trader que dans le sens du marché).
4. Chercher une stratégie à edge réel — valider systématiquement au walk-forward.
5. Plus tard seulement : live avec petits montants, garde-fous serrés.

---

## Conventions & environnement (cette machine — vécu en sessions passées)
- **Langue** : travailler en anglais si plus efficace, mais **communiquer/expliquer en français**.
- **Fichiers** : pattern « index + sous-fichiers courts », viser ≤ 200 lignes/fichier.
- **Écritures FUSE/virtiofs** : le mount tronque parfois les écritures longues et ajoute
  des null bytes (`\x00`). Après chaque écriture critique : vérifier taille + null bytes +
  queue de fichier. Stratégie sûre : écrire d'abord dans `/tmp`, vérifier, puis copier.
  Pour > 200 lignes, découper. (Convention utilisateur : `scripts/fuse_safe_write.sh`.)
- **PowerShell 5.1** : lit les `.ps1` en cp1252 sans BOM → tout `.ps1` Windows en **ASCII pur**
  (pas d'accents, em-dash, flèches, emoji).
- **git** : un `.git/index.lock` orphelin peut subsister après crash ; le supprimer côté
  Windows si besoin. **Aucune opération destructive** (rm -rf, force-push, rebase de
  branche partagée) sans audit + confirmation. Conservation par défaut.
- **Cross-check fichiers** : en cas de doute sur l'état d'un fichier, croiser la lecture
  harness (vérité) avec `cat`/`git status` (cache bash agressif).
- **Signaler, pas masquer** : remonter tout comportement anormal ; doute = STOP + demander.
