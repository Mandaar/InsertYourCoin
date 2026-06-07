# AUDIT DU MOTEUR de backtest — synthese (2026-06-08)

> Audit multi-agents en LECTURE SEULE du moteur (`backtester.py`, `optimizer.py`,
> `strategies.py`, `exchange.py`, `portfolio.py`, `indicators.py`), avant de lui faire
> confiance pour juger des dizaines de strategies. Chaque biais recoupe au code (fichier:ligne).
> Note : 2 agents (axes *lookahead* et *costs*) n'ont pas rendu de sortie structuree -> ces 2
> axes sont couverts partiellement (par les autres dimensions + biais connus) et meritent une
> 2e passe. Le reste est solide.

## 1. Verdict global : OUI, AVEC CORRECTIONS BLOQUANTES

Le coeur mecanique est **sain** : pas de lookahead (signal `shift(1)`), frais appliques des
2 cotes, decoupage train/test sans fuite temporelle, drawdown / annualisation / CAGR corrects.

**MAIS** le moteur n'est PAS fiable EN L'ETAT pour COMPARER des strategies, pour 3 raisons
structurelles (ci-dessous B1-B3). Tant qu'elles ne sont pas corrigees, tout verdict OOS est
bruite ou biaise.

## 2. Biais confirmes (par priorite)

| # | Biais | Preuve | Impact | Fix | Priorite |
|---|---|---|---|---|---|
| **B1** | **Warm-up des indicateurs recalcule depuis zero sur CHAQUE fenetre OOS** : une tranche de ~90 bougies rend une SMA 200 quasi morte ; EMA/RSI/MACD redemarrent leur lissage | `optimizer.py:100,71` ; `backtester.py:101` ; `indicators.py:10,26` ; `strategies.py:44` | Fausse les CLASSEMENTS entre strategies (avantage periodes courtes vs longues). **Contamine notre verdict Etape 1 (SMA daily).** | Calculer les indicateurs UNE fois sur le df complet ; passer `df.iloc[test_start-warmup:test_end]` et ne compter equity/trades qu'a partir de `test_start` | **BLOQUANTE** |
| **B2** | **Selection sur metrique non bornee** : le "flat" (std=0 -> sharpe 0.0) bat toute strategie negative ; `profit_factor`/`calmar` = +inf gagnent sur 1-2 trades chanceux ; aucun minimum de trades | `optimizer.py:45,51` ; `backtester.py:194,196,198,204` | Biais de SELECTION : en bear, le moteur choisit l'inaction et la presente comme "robuste" (masque l'absence d'edge) | Exiger `n_trades >= 5-10` ; exclure/plafonner les `inf` ; renvoyer `NaN` (pas 0.0) pour metriques degenerees | **BLOQUANTE** |
| **B3** | **`optimizer.py` n'a AUCUN test** (le "juge" du projet sans garde-fou) | aucun `test_optimizer.py` dans `tests/` | Une fuite train/test reintroduite serait invisible | `tests/test_optimizer.py` : non-chevauchement des fenetres (`train.index.max() < test.index.min()`), reproductibilite, garde "pas assez de donnees" | **BLOQUANTE** |
| **B4** | **Bougie EN FORMATION non exclue cote backtest** alors que le paper l'exclut (`iloc[:-1]`) -> incoherence + barre non finale | `main.py:61-64` + `exchange.py:101-106` VS `paper_trader.py:100-103` | Negligeable en 1d/720 ; MATERIEL en intraday et sur la derniere fenetre WF | Centraliser `df = df.iloc[:-1]` dans `_load_data`/`_load_basket` (convention unique backtest == paper) | HAUTE |
| **B5** | **Re-optimisation de la grille sur chaque train = data-mining non penalise** : l'OOS mesure un meta-systeme "choisis le meilleur a chaque reglage", pas un bot a params fixes | `optimizer.py:99-101,19-27` | OPTIMISTE, croit avec la taille de grille | Comparer systematiquement au baseline "params figes" sur memes fenetres ; logguer nb combos + instabilite des best params | HAUTE |
| **B6** | **Slippage non modelise** (biais connu) ; l'optimisation privilegie le turnover | `backtester.py:15,134,141,159,163` | OPTIMISTE, fort en intraday, avantage les strategies a beaucoup de trades | Ajouter un param slippage (5-15 bps/cote au prix defavorable), brancher dans optimize/WF | HAUTE |
| **B7** | **Pas de holdout final ; `optimize()` retourne `'full'` (train+test confondus)** | `optimizer.py:62-63,72` | OPTIMISTE ; chiffre flatteur exploitable par erreur | Reserver un holdout final 15-20% jamais touche ; retirer/renommer `'full'` | HAUTE |
| **B8** | **Sortino : formule approximative** (`rets[rets<0].std()` au lieu de `sqrt(mean(min(r,0)^2))`) | `backtester.py:195-196` ; `portfolio.py:30,37` | Verif adversariale : sens INVERSE du soupcon initial -> le code SOUS-estime le Sortino pour une expo 30-50% (conservateur). Risque = classement non-monotone si `--metric sortino` | `neg=np.minimum(rets,0); downside=sqrt((neg**2).mean())` + test | MOYENNE |
| **B9** | **`profit_factor = inf` quand 0 perte** : selectionnable et casse `avg_window_metric` | `backtester.py:204` ; `optimizer.py:51,109` | OPTIMISTE sur fenetres courtes tous-gagnants | Renvoyer `NaN` (pas inf) quand pertes=0 ; l'exclure des moyennes | MOYENNE |
| **B10** | **`fetch_ohlcv_range` non re-trie + dedup `keep="first"`** : garde une barre partielle si timestamp duplique | `exchange.py:56,65-66` | Faible proba, "bombe a retardement" silencieuse | `df.sort_index()` + `keep="last"` + `assert is_monotonic_increasing` | MOYENNE |
| **B11** | **`fetch_ohlcv_range` : troncature silencieuse** au plafond `max_calls=20` (intraday) | `exchange.py:44-45,52` | Periode evaluee silencieusement raccourcie -> "Periode X->Y" trompeuse | `max_calls` dynamique, ou avertir si arret sur plafond ; logguer couverture reelle | MOYENNE |
| **B12+** | OOS sur tres peu de donnees (fenetres courtes), grilles crypto potentiellement pre-overfittees | (cf. transcript) | Faible robustesse statistique | Plus d'historique + Deflated Sharpe | FAIBLE |

## 3. Ce qui est SAIN (verifie, rassurant)
- **Pas de lookahead** : le signal est decale (`shift(1)`), execution a t+1.
- **Frais des 2 cotes** (achat ET vente), y compris sur sizing partiel.
- **Train precede strictement test** dans le walk-forward (pas de fuite temporelle).
- **Drawdown, annualisation, CAGR** corrects.
- **Sizing par volatilite** strictement ex-ante (`frac.shift(1)`).

## 4. Recommandations pour le harness (Phase 2)
1. Corriger **B1** (warm-up) — prerequis absolu a toute comparaison de strategies.
2. Corriger **B2** (garde `n_trades`, pas de `inf`/`0.0` selectionnable) + **B3** (tests optimizer).
3. Ajouter **slippage** (B6), **holdout final** (B7), **bougie en formation exclue** (B4).
4. Ajouter un mode **walk-forward a parametres FIGES** (B5) pour separer "edge" de "overfit d'optimisation".
5. Ajouter le **Deflated / Probabilistic Sharpe Ratio** (penalise le nombre d'essais).
6. **Multi-actifs** (BTC/ETH/SOL) pour la robustesse.

## 5. Impact sur le verdict Etape 1 (SMA daily)
Le verdict d'hier ("**-13.6% hors-echantillon -> ne pas trader**") est **CONTAMINE par B1**
(la SMA etait amputee de son warm-up sur chaque fenetre) et **B2** (selection possible du flat).
**Il n'est donc pas fiable** : a RE-JUGER apres correction du moteur. On ne peut pas encore
conclure "SMA daily n'a pas d'edge".

---
*Audit produit par orchestration multi-agents (lecture seule), verifie de facon adversariale.
Detail complet : transcript du run. A capitaliser dans `SQA.md` (bugs) et au fil des corrections.*
