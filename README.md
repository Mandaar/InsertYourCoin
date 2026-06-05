# InsertYourCoin

> 🪙 *Insère ta pièce, lance la partie.* — système de trading crypto algorithmique sur Kraken.

Système de trading algorithmique multi-crypto, connecté à **Kraken** via `ccxt`.
Stratégies classiques, gestion du risque (stop-loss / take-profit / trailing stop),
dimensionnement par volatilité, **diversification de portefeuille**, optimisation
honnête (train/test + walk-forward) et tableau de bord web.

Progression recommandée :
> **Backtest** → **Optimize / Walk-forward** → **Paper trading** → **Live** (verrouillé par défaut)

---

## ⚠️ À lire avant tout

- Le trading de crypto comporte un **risque réel de perte**, potentiellement totale.
- **Ceci n'est pas un conseil en investissement.** Les décisions et le risque restent les tiens.
- Les performances passées **ne préjugent jamais** des résultats futurs.
- L'objectif sain : **gestion du risque** (préserver le capital), avec de l'argent qu'on peut se permettre de perdre — pas un revenu garanti.
- Optimiser sur le passé crée du **sur-apprentissage** : `optimize` et `walkforward` le mesurent.
- En **intraday**, les frais (0,26 %/ordre) mangent vite les gains.
- La diversification crypto **lisse** mais ne protège pas d'un krach systémique (tout est corrélé ~0,7–0,8).

---

## Installation

```bash
python -m venv .venv                        # environnement isolé (recommandé)
# Windows : .\.venv\Scripts\Activate.ps1    |  macOS/Linux : source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py check                        # vérifie l'install + la connexion Kraken
cp .env.example .env                         # clés Kraken (inutiles pour backtest/optimize/portfolio)
```
Conseil : crée une clé Kraken **sans permission de retrait** (coche seulement *Query* + *Trade*).

> **Derrière un antivirus/proxy qui scanne le HTTPS** (Avast, Kaspersky, proxy d'entreprise…) :
> géré automatiquement via `truststore` (magasin de certificats de l'OS), **sans** désactiver la
> vérification SSL. Si `python main.py check` affiche un prix, tout va bien. Détails et dépannage :
> **[SETUP.md](SETUP.md)**.

---

## Commandes

| Commande | Rôle |
|---|---|
| `check` | Diagnostic install + connexion Kraken (à lancer en premier) |
| `backtest` | Tester une stratégie sur l'historique |
| `compare` | Comparer toutes les stratégies |
| `optimize` | Meilleurs paramètres **avec validation train/test** |
| `walkforward` | Optimisation glissante (test hors-échantillon le plus réaliste) |
| `dashboard` | Tableau de bord HTML |
| `portfolio` | Backtester un **panier** de cryptos (diversification) |
| `paper` | Paper trading (argent fictif, temps réel) |
| `live` | Trading réel (dry-run par défaut) |
| `stats` | Synthèse descriptive du CSV accumulé en paper/live (labo de stats) |

**Options de risque** (sur backtest/compare/optimize/walkforward/dashboard/portfolio
**et désormais paper/live**) :
`--stop-loss PCT` · `--take-profit PCT` · `--trailing-stop PCT` ·
`--position-sizing vol --target-vol PCT`.

### Exemples

```bash
python main.py backtest  --strategy sma --stop-loss 8 --take-profit 20 --chart bt.png
python main.py backtest  --strategy sma --trailing-stop 12 --position-sizing vol --target-vol 40
python main.py walkforward --strategy sma --windows 4
python main.py portfolio --symbols BTC/USD,ETH/USD,SOL/USD --strategy sma --stop-loss 8 --take-profit 20
python main.py dashboard --strategy sma --stop-loss 8 --take-profit 20
python main.py paper     --strategy sma --timeframe 1h --stop-loss 5 --take-profit 10
python main.py paper     --strategy sma --timeframe 1h --trailing-stop 12 --position-sizing vol --target-vol 40
python main.py live      --strategy sma --stop-loss 8 --take-profit 20            # dry-run
python main.py live      --strategy sma --stop-loss 8 --take-profit 20 --execute  # réel
python main.py stats                                                              # synthèse du paper_stats.csv
```

---

## Stratégies

| `--strategy` | Type | Idée |
|---|---|---|
| `sma` | Tendance | Croisement de moyennes mobiles |
| `macd` | Tendance | Croisement MACD / signal |
| `rsi` | Retour à la moyenne | Achat <30, vente >70 |
| `bollinger` | Retour à la moyenne | Achat sous bande basse, sortie au retour vers la moyenne |

## Gestion du risque

- **Stop-loss** : coupe à `−X %` de l'entrée. **Take-profit** : gain pris à `+Y %`.
- **Trailing stop** : stop suiveur à `X %` sous le plus haut atteint (verrouille les gains).
- **Sizing par volatilité** (`--position-sizing vol`) : investit moins quand le marché est agité, plus quand il est calme → lisse la courbe.
- Stops vérifiés en intra-bougie ; pas de réentrée tant que le signal n'est pas retombé puis remonté.

## Diversification (`portfolio`)

Applique la stratégie à chaque actif d'un panier, équipondéré, additionne les courbes,
et compare au buy & hold du panier + affiche la **corrélation**. Sur données récentes,
un panier BTC/ETH/SOL réduit fortement volatilité et drawdown vs buy & hold — mais
corrélation ~0,8 : ça lisse, ça ne protège pas d'un krach général. XRP est le moins
corrélé du groupe (~0,63).

## Comprendre `optimize` et `walkforward`

- `optimize` : coupe l'historique en **train** (passé) / **test** (futur jamais vu). Si la perf s'effondre sur le test → sur-apprentissage.
- `walkforward` : re-optimise périodiquement et trade la période suivante, en avançant. Le verdict porte sur la **performance cumulée hors-échantillon** — le test le plus proche de la réalité.

---

## Garde-fous du mode live (`config.py`)

| Paramètre | Rôle | Défaut |
|---|---|---|
| `MAX_TRADE_VALUE_USD` | Montant max d'un ordre | 100 $ |
| `MAX_POSITION_VALUE_USD` | Exposition max | 500 $ |
| `MIN_TRADE_INTERVAL_SEC` | Délai min entre ordres | 3600 s |

`--execute` exige de taper `OUI JE CONFIRME`. Tout est journalisé dans `live_trades.log`.

---

## Structure

```
InsertYourCoin/
├── main.py              # CLI (10 commandes)
├── config.py            # paramètres + risque + garde-fous
├── requirements.txt
├── .env.example
├── dashboard.html       # exemple de tableau de bord
└── trading/
    ├── indicators.py    # SMA, EMA, RSI, MACD, Bollinger
    ├── strategies.py    # les 4 stratégies
    ├── exchange.py      # connexion Kraken
    ├── backtester.py    # moteur event-driven + stop/trailing/sizing
    ├── optimizer.py     # optimize (train/test) + walk_forward
    ├── portfolio.py     # backtest multi-actifs (diversification)
    ├── dashboard.py     # tableau de bord HTML
    ├── paper_trader.py  # paper trading + boucle commune
    ├── live_trader.py   # trading réel (verrouillé par défaut)
    └── stats.py         # labo de stats : enregistreur CSV + synthèse
```

## Pistes pour la suite (dans Claude Code, sur ta machine)

- ✅ Trailing stop + sizing volatilité **dans le paper/live** (fait — aligné sur le backtest, couvert par `tests/`).
- ✅ Labo de stats : `paper`/`live` enregistrent un CSV horodaté ; `python main.py stats` en fait la synthèse.
- Filtre de tendance long terme (ne trader que dans le sens du marché).
- Pondération du portefeuille par risque (risk parity).
- Recherche d'une stratégie à vrai edge (le walk-forward reste juge).
