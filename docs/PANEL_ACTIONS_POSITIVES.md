# PANEL D'ACTIONS POSITIVES — InsertYourCoin

> Synthese d'analyse : 8 familles de strategies de capitalisation crypto, recherchees
> puis verifiees de facon adversariale, croisees avec NOS contraintes (Kraken spot, pas
> de levier `MAX_FRACTION=1.0`, capital modeste, frais ~0.26%/ordre, live verrouille) et
> NOS donnees reelles (paper SMA 20/50 en 5m sur ETH : -5.99%, win-rate 0%, frais = 32%
> de la perte). Le **walk-forward hors-echantillon reste le seul juge** (jamais l'in-sample).
> Date : 2026-06-07. A capitaliser comme le reste (cf. `SQA.md`, `ENQUETE_ET_AMELIORATIONS.md`).

---

## 1. Synthese executive

Nos donnees confirment deux choses, mecaniquement, pas par opinion : (a) le trend-following
**naif en timeframe court (5m)** se fait **hacher** en range/baisse (win-rate 0%), et (b) les
**frais dominent** des qu'on sur-trade (319$ = 32% de la perte). La litterature converge avec
nous : **baisser la frequence et viser un edge structurel ou une reduction de risque**, pas un
alpha de scalping. Les directions les plus prometteuses pour NOUS, dans l'ordre :

1. **Trend-following LENT long/flat en DAILY** (MA 50/200 ou time-series momentum 12 mois) — meme
   famille que notre SMA, mais le passage 5m -> daily effondre le whipsaw et les frais. **Edge
   surtout en reduction de drawdown / Sharpe**, pas en rendement absolu.
2. **Filtre de regime + volatility targeting** par-dessus (1) — couche de robustesse ; ~80% deja
   code chez nous (le sizing `vol` existe). N'invente pas d'edge, **ameliore** un signal qui en a un.
3. **Capitalisation passive disciplinee** : equal-weight 1/N, DCA, stablecoin yield (USDC) comme
   parking du capital dormant. Pas de l'alpha, mais robuste, peu cher, honnete.
4. **Mean-reversion mono-actif daily/4h** (Bollinger, deja code) avec seuils larges + filtre de
   tendance — candidat testable, mais fragile aux frais : a falsifier au walk-forward.

**Tout le reste exige du short/futures/levier (interdit ici) ou de l'illiquide intradable, ou est
un artefact in-sample.** Ce sont des ecartes (section 4), explicitement.

---

## 2. Panel priorise (approches RETENUES)

Retenu = verdict **edge_reel ou conditionnel** ET fit **fort/moyen** pour notre contexte spot/sans-levier.
Trie par pertinence pour nous (du plus directement actionnable au plus accessoire).

| # | Approche | Edge (source) | Market-neutral ? | Sensib. frais | Levier/futures ? | Effort | Priorite |
|---|----------|---------------|------------------|---------------|------------------|--------|----------|
| 1 | **MA crossover LENT 50/200 daily, long/flat** | Reduction DD / Sharpe (Grayscale ; AQR "Century of Evidence") | Non (long/flat) | Faible | Non | Faible (param TF) | **HAUTE** |
| 2 | **TSMOM 12 mois, rebalance mensuel** | Anomalie la + documentee (Moskowitz-Ooi-Pedersen 2012 JFE ; Hurst-Ooi-Pedersen 2017) | Non (long/flat) | Faible | Non | Faible/Moyen | **HAUTE** |
| 3 | **Filtre de regime (prix>MA200) + vol-targeting** par-dessus 1/2 | +Sharpe, -queues (Harvey et al. 2018 ; Cederburg et al. 2020 sur momentum) | Non (couche) | Faible/Moyen | Non | Moyen (80% existe) | **HAUTE** |
| 4 | **Equal-weight 1/N panier + rebal basse freq** | 1/N dur a battre OOS (DeMiguel-Garlappi-Uppal 2009 RFS) | Non (long-only) | Faible | Non | Faible (portfolio existe) | MOYENNE |
| 5 | **Stablecoin yield USDC (parking capital dormant)** | Taux sans risque crypto-natif ~2-4% (taux Kraken Earn ; BCE 2025 "DeFiying the Fed") | Oui (USD) | Faible | Non | Faible | MOYENNE |
| 6 | **Mean-reversion mono-actif daily/4h (Bollinger) + filtre tendance** | Auto-correlation neg. intraday (Fil & Kristoufek 2020) | Non (long/flat) | Elevee | Non | Faible (existe) | MOYENNE |
| 7 | **XSMOM top-k + filtre de tendance marche** | Overlay trend > tri cross-sectionnel (Starkiller 2023 ; Han-Kang-Ryu 2023) | Non (long-only) | Moyenne | Non | Moyen | BASSE |
| 8 | **DCA periodique (deploiement, pas edge)** | Reduit sequence risk (Constantinides 1979 ; Vanguard 2012) | Non | Faible | Non | Faible | BASSE |
| 9 | **Rebalancing a seuil large (+/-15%) panier** | Controle du risque (AQR 2017 ; Crypto Research Report) | Non | Moyenne | Non | Moyen | BASSE |
| 10 | **Risk-parity / inverse-vol panier** | +Sharpe re-weighting (Man Group) | Non | Moyenne | Non | Moyen | BASSE |

> Note d'honnetete transversale : **aucune** de ces approches n'est market-neutral SAUF le
> stablecoin yield (#5), parce que le market-neutral crypto serieux (carry funding, pairs trading)
> exige de **shorter**, donc futures/levier — incompatible avec nos garde-fous. Toutes les autres
> subissent le **beta crypto** : en krach systemique (correlation BTC/ETH/SOL ~0.8 deja mesuree
> chez nous), elles baissent. Elles **lissent** le risque, elles ne **creent** pas de rendement.

---

## 3. Fiches detaillees (top 5)

### Fiche 1 — MA crossover LENT 50/200 en DAILY, long/flat **[PRIORITE HAUTE]**

**Ce que c'est.** Investi (100% ou fraction) quand la moyenne mobile 50 jours est au-dessus de la
200 jours ("golden cross"), cash sinon ("death cross"). C'est notre `SMACrossover` existante, mais
en **timeframe daily** au lieu de 5m. Mathematiquement un filtre de momentum lisse.

**Pourquoi un edge.** Famille trend-following validee sur un siecle (AQR Hurst-Ooi-Pedersen, "A
Century of Evidence", positif chaque decennie depuis 1880 :
https://fairmodel.econ.yale.edu/ec439/hurst.pdf). En crypto, Grayscale Research montre un Sharpe
ameliore vs buy-and-hold via crossover de MA
(https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals).
**Lucidite** : l'edge n'est PAS du rendement absolu (les 116%/an de Grayscale sont gonfles par
2012-2017, BTC x1000, non reproductible) — c'est une **reduction de drawdown** et un meilleur
Sharpe. En daily 50/200 : ~2 a 6 ordres/an -> les frais (notre probleme #2) deviennent negligeables.

**Comment l'implementer chez nous.** Quasi gratuit : c'est deja code.
```bash
python main.py backtest    --strategy sma --timeframe 1d --days 720
python main.py walkforward --strategy sma --timeframe 1d --windows 4 --metric calmar
```
Pour figer 50/200 (eviter le data-mining via l'optimizer qui teste 16 combos), instancier
`SMACrossover(50, 200)` directement, ou ajouter une entree au registre `STRATEGIES`. NE PAS
selectionner "la meilleure combo in-sample" : prendre les valeurs **canoniques** et les valider OOS.

**Risques.** Retard a l'entree ET a la sortie (on rend le haut et le bas du move). Sous-performe le
buy-and-hold en bull pur. Data-mining si on optimise les fenetres (50/200 est ultra-connu, donc
potentiellement crowdee). Echantillon crypto court (~10-15 ans = peu de cycles independants).

**Comment le VALIDER.** `walkforward` sur 4 fenetres, **critere Calmar ou Sharpe** (pas
total_return, qui flatte). Verdict attendu honnete : **Sharpe ameliore + drawdown reduit vs B&H**,
rendement absolu comparable ou legerement inferieur selon le regime. Si l'OOS est negatif -> rejeter.

---

### Fiche 2 — TSMOM 12 mois, rebalancement mensuel **[PRIORITE HAUTE]**

**Ce que c'est.** Time-series momentum : on est long si le rendement glissant 12 mois est positif,
cash sinon ; on ne reverifie qu'une fois par mois. Optionnel : fraction investie pilotee par la vol.

**Pourquoi un edge.** L'anomalie la plus documentee de la finance quant : Moskowitz, Ooi & Pedersen
(2012, JFE), Sharpe brut ~1.31 sur 58 futures avec vol-targeting
(https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum ;
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463). Positif chaque decennie depuis 1880
(Hurst-Ooi-Pedersen). **Lucidite** : les chiffres-phares portent sur un **panier multi-classes
long/short** ; sur BTC/ETH seul en long/flat, on herite surtout du **crisis-alpha + reduction de
drawdown**, pas du rendement absolu du papier. Turnover mensuel ultra-bas -> frais negligeables.

**Comment l'implementer chez nous.** Nouvelle strategie `TSMomentum(lookback_days=365)` : signal =
`(close > close.shift(lookback)).astype(int)`, a brancher dans `STRATEGIES`. Le rebalancement
mensuel = un signal qui ne change qu'aux bascules (le backtester gere deja le decalage t+1).
Combinable avec `--position-sizing vol` (deja code, strictement ex-ante via `frac.shift(1)`).

**Risques.** Signal lent -> rend une partie du gain aux retournements en V. Sur un seul actif, pas
de crisis-alpha de diversification (l'essentiel du Sharpe du papier vient du panier). Decay
post-publication (anomalie tres connue). Echantillon crypto court.

**Comment le VALIDER.** Necessite >= ~2-3 ans de daily (le lookback 12 mois mange 365 bougies).
Charger `--days` large (l'exchange supporte `fetch_ohlcv_range`). `walkforward` avec un lookback
**fige** (pas optimise) pour eviter l'overfit. Comparer DD et Sharpe vs B&H, pas le rendement brut.

---

### Fiche 3 — Filtre de regime + volatility targeting (couche par-dessus 1/2) **[PRIORITE HAUTE]**

**Ce que c'est.** PAS une strategie autonome : une **couche de robustesse**. Deux briques. (a)
**Filtre de tendance** : n'autoriser les achats que si prix > MA200 (ou momentum 12m > 0) -> ne pas
trader contre la grande tendance (reponse directe a notre lecon (a)). (b) **Vol-targeting** :
fraction investie inversement proportionnelle a la vol realisee -> de-leverage automatique dans les
krachs (la vol monte). C'est notre "prochaine etape 3" du CLAUDE.md.

**Pourquoi un edge.** Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, Van Hemert (2018, "The Impact
of Volatility Targeting", https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538) : le
vol-scaling ameliore le Sharpe et coupe les queues. Surtout, Cederburg, O'Doherty, Wang & Yan (2020,
JFE, https://www.lehigh.edu/~xuy219/research/COWY.pdf) montrent que le vol-management aide
**nettement le momentum** (et seulement lui parmi les facteurs : 53/103 portefeuilles gagnent
globalement = pile-ou-face, le momentum est l'exception). Barroso & Santa-Clara : risk-managed
momentum double quasi le Sharpe avec un turnover comparable au momentum brut (donc implementable
malgre les frais). **Lucidite cle** : la couche **n'invente pas d'edge** — elle ameliore un signal
qui en a deja un. Sur notre SMA 5m (walk-forward 0% de fenetres profitables), elle aurait juste
**lisse la perte**, pas cree de profit. Nos propres donnees l'ont prouve (vol/3, DD/2, sans profit).

**Comment l'implementer chez nous.** Le sizing `vol` existe (`_size_series`, ex-ante). Reste a
ajouter le **filtre de tendance long terme** : un wrapper de strategie qui `AND` le signal avec
`(close > sma(close, 200))`. ~30 lignes. Banding obligatoire (ne re-trader que si la fraction cible
bouge de > X points) pour ne pas re-scaler a chaque bougie et faire exploser les frais.

**Risques.** Sur-ingenierie : chaque parametre (fenetre vol, cible, longueur filtre) est un degre de
liberte = terrain de data-mining. Critique academique majeure : Cederburg et al. jugent les versions
vol-managed cherchant de l'alpha "not implementable in real time" — mais la version
**long-only-defensive** (jamais au-dessus de 100%, reduction de drawdown pure) est plus robuste car
elle ne parie pas sur une regression. Filtre trop strict = zero trade = zero edge. Lag de l'EMA aux
retournements (whipsaw en range).

**Comment le VALIDER.** A appliquer **UNIQUEMENT sur une strat 1/2 deja validee** au walk-forward,
jamais comme sauveur d'une strat morte. Tester chaque parametre ajoute en OOS : s'il n'ameliore pas
le Sharpe/DD hors-echantillon, le retirer (overfit deguise).

---

### Fiche 4 — Equal-weight 1/N panier + rebalancing basse frequence **[PRIORITE MOYENNE]**

**Ce que c'est.** Allouer 1/N a chaque actif d'un panier liquide (BTC, ETH, SOL...), rebalancer
periodiquement (trimestriel ou a seuil large) vers l'equiponderation. Aucun parametre a estimer.

**Pourquoi un edge.** DeMiguel, Garlappi & Uppal (2009, Review of Financial Studies, "Optimal Versus
Naive Diversification",
https://www.researchgate.net/publication/31210252_Optimal_Versus_Naive_Diversification) : sur 14
datasets, **aucune** strategie mean-variance optimisee ne bat systematiquement le 1/N hors-echantillon
en Sharpe (a cause de l'erreur d'estimation). Re-confirme en 2024. Zero parametre = zero overfitting,
ce qui colle a notre doctrine "walk-forward juge". **Lucidite** : l'edge est **relatif** (le 1/N bat
les optimiseurs), **PAS** un alpha absolu vs le marche — le rendement reste dirige par le beta crypto.

**Comment l'implementer chez nous.** La commande `portfolio` existe deja (equipondere +
correlation). Pour un vrai 1/N "buy & hold rebalance", il faut ajouter une logique de rebalancement
periodique (actuellement chaque actif est backteste independamment puis somme). Effort faible/moyen.

**Risques.** Beta de marche non couvert (long-only, on encaisse tout krach ; correlation ~0.8 deja
mesuree -> diversification faible). Le **choix de l'univers EST la decision cle** et n'est pas couvert
par la methode (1/N de mauvais actifs = mauvais resultat). Survivorship bias des etudes crypto
(coins morts exclus -> Sharpe publies optimistes). Sous-performe la concentration BTC en bear.

**Comment le VALIDER.** Backtest `portfolio` sur univers **fige a l'avance** (pas selectionne a
posteriori). Comparer Sharpe/DD vs detenir BTC seul et vs B&H equipondere. Rebalancement basse
frequence pour que les frais (x N paires) restent faibles.

---

### Fiche 5 — Stablecoin yield USDC : parking du capital dormant **[PRIORITE MOYENNE]**

**Ce que c'est.** Detenir des USDC et toucher une recompense (Kraken Earn) **entre deux signaux a
edge reel**, au lieu de laisser le cash inerte ou de sur-trader. Le seul element vraiment
market-neutral (expose en USD, pas au prix crypto).

**Pourquoi un edge... non, un RENDEMENT.** Soyons exacts : ce n'est **pas un edge de trading**,
c'est le **taux sans risque crypto-natif** (~2-4% USD) qui **suit la Fed** (etude BCE 2025
"DeFiying the Fed" : les taux stablecoin tracent la politique monetaire). Taux Kraken publies
(https://support.kraken.com/articles/stablecoin-rewards). Quasi sans frais (pas de 0.26% recurrent).
C'est le **meilleur usage du capital dormant** — mieux que l'inertie ou que nos 13 trades a
win-rate 0%.

**Comment l'implementer chez nous.** Hors perimetre du moteur de backtest (ce n'est pas une strat a
signaux). Cote operationnel : detenir USDC en spot ; l'inscription au programme Rewards passe par
l'API/UI Kraken Earn (pas une primitive ccxt standard). A traiter comme une **regle de tresorerie**,
pas comme une strategie.

**Risques (a respecter — garde-fou honnetete).** (1) **Risque geographique MAJEUR** : sous MiCA,
USDT/USDG sont restreints/delistes pour les clients EEA ; en France, **seul USDC est realiste**, et
le programme Rewards lui-meme peut etre indisponible selon juridiction -> **a verifier avant de
compter dessus**. (2) Risque de **depeg** (USDC = faible mais non nul : SVB mars 2023, $0.87
transitoire, recupere en 72h) -> ne jamais traiter 4% comme "sans risque". (3) Compression du
rendement si la Fed baisse. (4) Cout d'opportunite en bull. **Ne JAMAIS** confondre avec un edge.

**Comment le VALIDER.** Pas de walk-forward (pas un signal). Verification factuelle : taux net reel
apres commission Kraken, disponibilite du produit dans la juridiction de l'utilisateur, et clause
explicite "ceci n'est pas sans risque" dans toute communication.

---

## 4. Ecartees (et pourquoi) — honnetete

Approches jugees **douteux / marketing / non applicables** dans la verification adversariale, une
ligne chacune :

- **Cash-and-carry funding (long spot + short perp)** — edge market-neutral le mieux documente
  (BIS WP 1087), MAIS exige de **shorter un perp** = futures + levier, **interdit** (`MAX_FRACTION=1.0`),
  de facto bloque au retail France (AMF) ; et **decay** : Sharpe negatif en 2025.
- **Funding-rate timing (carry conditionnel)** — meme verrou short/futures ; pire, 60% des
  meilleures opportunites NE sont PAS rentables apres couts (ScienceDirect S2096720925000818).
- **Pairs trading / cointegration (BTC/ETH)** — exige le **short** ; source rigoureuse (Fil &
  Kristoufek 2020, IEEE Access) : **en perte a frais realistes** sur tous les regimes.
- **Ornstein-Uhlenbeck spread trading** — meme verrou short ; "may not be robust in the crypto
  market" (SSRN 5263475). Seul l'apport "seuil = f(frais)" est reutilisable dans la mean-reversion #6.
- **XSMOM market-neutral long/short (WML)** — exige le short ; l'edge vient surtout de la jambe
  short sur micro-caps illiquides intradables. Non applicable.
- **XSMOM top-quintile long-only hebdo** — **OOS negatif AVANT frais** (-2.35%, Starkiller),
  survivorship bias, sur-trading hebdo = notre erreur #2.
- **Short-term reversal cross-sectionnel** — l'edge vit dans l'**illiquide non-tradable** ; sur les
  majors liquides Kraken il **s'inverse** en momentum (Zhang et al.). Non exploitable a notre echelle.
- **sUSDe (Ethena) "stablecoin" delta-neutre** — "stable" trompeur : produit de **regime haussier**,
  risque de depeg superieur a USDC, rendement comprime (~9-12% en 2026, pas 18%). Micro-poche
  speculative au mieux.
- **ETH staking** — rendement reel (~2.5%) mais **directionnel** : un -10% d'ETH efface ~4 ans de
  staking ; ne resout aucun de nos 2 problemes cote rendement (utile seulement si HODL par conviction).
- **Market-making HFT (Avellaneda-Stoikov)** — l'arithmetique des frais retail tue tout : capturer
  un spread <5 bps en payant 25 bps x2 = perte garantie. Exige rebates + colocalisation. Notre erreur
  de sur-trading a la puissance N.
- **Grid trading** — seule source academique (Stevens FSC) **sans frais ni metriques** ; overfitting
  = piege #1 ; pas de stop naturel -> accumule un sac qui baisse (notre vecu ETH). A falsifier, pas un edge.
- **Signal de microstructure (order-flow imbalance) en taker** — edge reel mais **minuscule**
  (0.13%/an sur BTC) et concentre sur alts illiquides ; exige donnees L2 + latence qu'un stack
  ccxt/REST domestique n'a pas. Non capturable par nous.

---

## 5. Roadmap pour InsertYourCoin

Du plus simple/sur (s'appuie sur l'existant) au plus complexe. Chaque etape se valide au
**walk-forward** avant de passer a la suivante.

**Etape 0 — Hygiene de mesure (prealable, indispensable).**
- Aligner `config.FEE` sur le **taker reel Kraken** au palier debutant (~0.40%), ou au moins tester
  les deux. Le `0.0026` actuel **sous-estime** les frais et flatte tout backtest taker-pur. Si on
  passe en ordres LIMIT maker, modeliser ~0.16-0.25%.
- Acter que le backtester **ne modelise pas le slippage** (commentaire ligne 15) : tout resultat de
  type breakout/grid/microstructure est donc **optimiste** par construction. Ne pas conclure dessus.

**Etape 1 — Trend lent en DAILY (zero code neuf).**
- `python main.py walkforward --strategy sma --timeframe 1d --windows 4 --metric calmar`
- Comparer Sharpe/DD vs B&H. C'est le test le plus rentable : il rejoue notre SMA mais dans le
  regime ou il a une chance (daily, pas 5m). **Critere de succes : OOS non negatif + DD reduit.**

**Etape 2 — TSMOM 12 mois (nouvelle strategie, ~15 lignes).**
- Ajouter `TSMomentum(lookback)` au registre `STRATEGIES` + entree `DEFAULT_GRIDS` (ou lookback fige).
- Charger >= 2-3 ans de daily. `walkforward` avec lookback **fige**.

**Etape 3 — Couche robustesse sur la meilleure de 1/2.**
- Activer `--position-sizing vol --target-vol 40` sur la strat retenue (deja code).
- Ajouter le **filtre de tendance MA200** (wrapper ~30 lignes) avec banding. Valider que chaque
  brique ameliore le Sharpe/DD **en OOS**, sinon la retirer.

**Etape 4 — Capitalisation passive / portefeuille.**
- Etendre `portfolio` vers un vrai **1/N rebalance** (basse frequence) ; comparer vs BTC seul.
- Documenter la **regle de tresorerie** USDC pour le capital dormant (operationnel, hors moteur).

**Etape 5 — Mean-reversion daily (optionnel, fragile).**
- `python main.py walkforward --strategy bollinger --timeframe 4h --windows 4` avec seuils larges +
  filtre de tendance. A traiter comme **hypothese a falsifier**, pas comme edge acquis.

**Hors-scope tant que le projet reste spot/sans-levier** : carry funding, pairs trading, tout
market-neutral exigeant le short. A ne rouvrir que sur **decision explicite** d'elargir aux futures
(et meme la, l'edge carry est en decay 2025).

---

## 6. Garde-fous (rappel)

- **Le walk-forward hors-echantillon est le SEUL juge.** Jamais l'in-sample, jamais le paper seul,
  jamais un chiffre marketing (Grayscale 116%/an, Starkiller 93%/an, Sharpe 6+ carry = in-sample,
  survivorship, ou regime-dependant). `optimizer.py` rend deja un verdict + `pct_profitable` : s'y
  tenir. OOS negatif -> on ne trade pas.
- **Frais d'abord (lecon (b)).** 319$ = 32% de notre perte venaient du sur-trading 5m. **Privilegier
  la basse frequence** : 50/200 daily = ~2-6 ordres/an ; TSMOM mensuel = ~12-24/an. Aligner
  `config.FEE` sur le **vrai** taker (~0.40%) avant de juger un edge net.
- **Pas de hachage (lecon (a)).** Le trend-following naif en TF court se fait detruire en range.
  Daily + filtre de regime. Mean-reversion et grid sans filtre = meme piege a l'envers.
- **Pas de data-mining.** Figer les parametres canoniques (50/200, lookback 12m) plutot que
  selectionner "la meilleure combo in-sample". Chaque parametre ajoute doit gagner sa place en OOS.
- **Pas de levier, pas de short, live verrouille.** `MAX_FRACTION=1.0` ; toute approche exigeant le
  short est hors-scope par construction. Live reste dry-run + double confirmation.
- **Le risk-management LISSE, il ne CREE pas de profit.** Vol-targeting et diversification reduisent
  le drawdown et la vol — ils n'inventent pas d'alpha sur un signal mort. Nos donnees l'ont prouve.
- **Honnetete.** Aucune approche retenue ici n'est une machine a cash. Les meilleures (#1, #2, #3)
  promettent une **meilleure qualite de risque** (Sharpe/DD) avec un rendement absolu **modeste**,
  pas un revenu. Le seul vrai market-neutral accessible (#5 USDC) est un coupon ~2-4%, pas un edge.
- **Capitaliser.** Tout test significatif -> une ligne au registre (`SQA.md`) et a l'enquete
  (`ENQUETE_ET_AMELIORATIONS.md`), comme pour les bugs.

---

*Sources principales citees (verifiees dans la recherche adversariale)* :
AQR Time-Series Momentum (https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) ·
Hurst-Ooi-Pedersen "Century of Evidence" (https://fairmodel.econ.yale.edu/ec439/hurst.pdf) ·
Grayscale "The Trend is Your Friend" ·
Harvey et al. "Impact of Volatility Targeting" (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538) ·
Cederburg-O'Doherty-Wang-Yan 2020 JFE (https://www.lehigh.edu/~xuy219/research/COWY.pdf) ·
DeMiguel-Garlappi-Uppal 2009 RFS ·
Constantinides 1979 / Vanguard 2012 (DCA) ·
Fil & Kristoufek 2020 IEEE Access (pairs trading) ·
BIS WP 1087 "Crypto carry" (https://www.bis.org/publ/work1087.htm) ·
Starkiller Capital "Cross-sectional momentum" ·
BCE 2025 "DeFiying the Fed" · Taux Kraken Earn (https://support.kraken.com/articles/stablecoin-rewards).
