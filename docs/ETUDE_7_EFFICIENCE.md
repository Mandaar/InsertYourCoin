# Etude #7 — Rendre l'application efficiente : ou est le levier reel

> Date : 2026-09-01. Demande de Mandar (verbatim) : « *j'ai besoin d'une vrais reflexion sur le
> sujet comment rendre l'application efficient tu peux chercher sur le net tu peux te renseigner
> faire des calcules proposer des choses !* »
> Doctrine : honnetete avant tout, le walk-forward hors-echantillon est le juge, jamais de survente.
> Sources : donnees paper reelles (22 j, 6 378 cycles), corpus d'etudes du projet (#1 a #6bis),
> recherche web (grille Kraken officielle + litterature academique).

---

## 1. La question, et la reponse en une ligne

**Le probleme n'est pas de trouver quoi faire — c'est ecrit et valide dans ce depot depuis juillet.
Le probleme est que rien de ce qui a ete valide ne tourne en production.**

| | Production (serveur eunivers) | Recherche validee (etudes #4, #5, panel) |
|---|---|---|
| Horizon | **5 minutes** | journalier |
| Strategie | SMA 20/50 croisement | TSMOM 365 j fige, ou SMA 50/200 |
| Ordres | 7 / jour | 3 a 5 / **an** |
| Validation OOS | aucune | walk-forward ~8 ans, 3 actifs |
| Resultat mesure | **-35,30 % en 11 j** | drawdown reduit **3 actifs / 3** |

---

## 2. Ce que les donnees disent (MESURE, 2026-08-09 -> 08-31, 6 378 cycles)

### 2.1 Les deux moities du forward test #6bis

| | AVANT `band=0` (11,06 j) | APRES `band=1.5` (11,16 j) |
|---|---|---|
| Ordres | 78 (7,05/j) | **0** |
| Frais | **4 707,03 $** (47 % du capital) | 0,00 $ |
| Equity | 10 000 -> 6 470,38 (**-35,30 %**) | 6 470,38 -> 6 470,38 (**0,00 %**) |
| Prix ETH | +19,52 % | **+7,95 %** |
| Exposition moyenne | 53,9 % | 0 % |

Le service a tourne **parfaitement** : 3 203 cycles pour 3 202 attendus (100,0 %), 287/jour tous les
jours pleins, zero trou, intervalle max 302 s. **Ce n'est pas une panne : la bande a refuse chaque
signal.** L'ecart SMA n'a jamais atteint le seuil de 2,43 % (max 2,154 %).

Verdict #6bis : la bande supprime 100 % du churn ET 100 % de la participation. Echantillon de
trades = 0 -> **elle ne prouve rien sur la rentabilite**, seulement qu'elle bloque.

### 2.2 Balayage de timeframes, split train/test (le juge)

| TF | Total net | Trades | Train | **TEST** |
|---|---|---|---|---|
| 5 min | -17,03 % | 153 | -4,45 % | **-13,18 %** |
| 15 min | +0,93 % | 49 | +9,23 % | **-8,89 %** |
| 30 min | +17,50 % | 25 | +16,47 % | **-3,11 %** |
| 60 min | +17,58 % | 12 | +19,16 % | **-4,82 %** |
| 120 min | +27,13 % | 4 | +22,59 % | **-2,37 %** |
| 240 min | +26,96 % | 2 | +22,62 % | **-1,36 %** |

**Toutes negatives au test. Buy & hold = +29,09 %, battu par aucune configuration.**

### 2.3 Y a-t-il un signal predictif ? (la demande « petite IA »)

Il existe une autocorrelation reelle et significative a 30 min (+0,120, p < 0,001) et 60 min
(+0,101, p = 0,02). A 5 min elle est **negative** (-0,073) : micro-reversion, l'inverse exact de ce
qu'une SMA suiveuse sait exploiter. Voila pourquoi le 5 min churne.

Edge reel = (gain sur signal fort) - (gain en etant simplement investi), car ETH monte de +29 % sur
la periode et le beta ne doit pas etre compte comme de l'alpha :

| TF | Detention | Signal fort | Sans signal | **EDGE** |
|---|---|---|---|---|
| 60 min | 24 h | +1,617 % | +1,232 % | **+0,385 %** |
| 60 min | 6 h | +0,672 % | +0,300 % | +0,372 % |
| 30 min | 6 h | +0,494 % | +0,297 % | +0,196 % |
| 240 min | 48 h | +2,532 % | +2,800 % | **-0,267 %** |

**Le meilleur edge n'est pas distinguable de zero** : 51 observations chevauchantes (~21 reellement
independantes), ecart-type des rendements 24 h = 4,40 %, **IC 95 % = [-0,822 % ; +1,591 %]**.

> **Correction methodologique a retenir** (erreur commise puis corrigee dans la session) : l'edge se
> mesure **par periode de detention**, jamais « par bougie » via `amplitude x correlation` — ce
> calcul suppose un aller-retour a chaque bougie et sous-estime le brut d'un facteur ~47.

---

## 3. Le mur : les frais, chiffres

### 3.1 Cout annuel selon la frequence (frais reels `config.py` : 0,80 % taker)

| Configuration | Ordres/an | **Frais/an** |
|---|---|---|
| **Production actuelle (ETH/5m)** | 2 574 | **100 % du capital** |
| La meme en 1 h | 199 | 79,8 % |
| La meme en 4 h | 33 | 23,4 % |
| **SMA 50/200 daily** | 5 | **3,9 %** (1,98 % en maker) |
| **TSMOM 365 mensuel** | 3 | **2,4 %** (1,20 % en maker) |

**Passer au journalier divise le peage par ~30.** C'est le seul levier de cette etude dont l'effet
est arithmetique, immediat et garanti.

### 3.2 Grille Kraken — TRANCHE le 2026-09-01 : `config.py` est EXACT

Deux recherches independantes avaient donne des valeurs contradictoires (0,40/0,80 contre
0,25/0,40). **Lecture directe de la page officielle** https://www.kraken.com/features/fee-schedule
(2026-09-01), table « Crypto Spot » de Kraken Pro, palier le plus bas :

> **maker 0,40 % · taker 0,80 %**

**Les valeurs de `config.py:27-28` sont donc exactes** — ni obsoletes, ni conservatrices. La seconde
recherche se trompait. Aucune modification des taux n'est requise. Table distincte pour les paires
stablecoin / FX (USDT/USD, EUR/USD) : maker = taker = **0,20 %** — sans objet pour ETH/USD.

**Reserve** : c'est le tarif du **palier public le plus bas**. Le palier reel du compte de Mandar
n'a PAS pu etre lu (aucun `.env` dans ce worktree ni dans le depot principal — MESURE par `find`).
Statut : SUPPOSE palier 1, coherent avec un capital modeste. Pour le trancher : `fetch_trading_fees()`
(ccxt, lecture seule) depuis une machine disposant des cles, ou la page Fees du compte connecte.

Fait nouveau et actionnable (MESURE, support.kraken.com/articles/cross-platform-fee-tier-changes) :
depuis le **9 juillet 2026**, le palier est donne par le **meilleur des trois** — volume spot 30 j,
volume futures, ou **Assets on Platform** (valeur des avoirs simplement detenus chez Kraken).
Laisser du capital sur la plateforme baisse les frais sans trader davantage.

Aller-retour maker par palier (version A) vs edge estime de +0,385 % :

| Palier | Seuil | Maker | A/R | vs edge |
|---|---|---|---|---|
| 1 | 0 $ | 0,40 % | 0,805 % | -0,420 % |
| 3 | 10 000 $ | 0,22 % | 0,441 % | -0,056 % |
| 4 | 25 000 $ | 0,20 % | 0,401 % | -0,016 % |
| **5** | **50 000 $** | 0,15 % | 0,301 % | **+0,084 %** |

**Il faut le palier 5 (50 000 $) pour que le trading frequent devienne theoriquement viable.** Hors
de portee pour « du capital qu'on peut se permettre de perdre » — et on parierait sur un edge dont
l'IC contient zero.

### 3.3 Le bot est structurellement taker

`trading/exchange.py:132-140` n'expose que `create_market_buy` / `create_market_sell`. Aucun code
d'ordre limite. Passer en maker divise le peage par ~2 et supprime le slippage.
**Necessaire, pas suffisant** : a 0,80 % d'A/R maker, l'edge de +0,385 % reste perdant.

> Note de provenance : Mandar a mentionne le 2026-09-01 passer ses ordres manuels en limite, en
> reaction a une explication du vocabulaire maker/taker. C'est un **fait rapporte sur ses ordres**,
> pas une position technique qu'il aurait etablie — il ne doit pas etre cite comme appui de ce
> raisonnement. **L'argument tient seul, sur le code et la grille tarifaire mesures ci-dessus.**

---

## 4. Ce que dit la litterature externe (et elle converge avec nos mesures)

| Piste | Support | Chiffre net de frais |
|---|---|---|
| Croisement MM intraday | **inexistant** | -2 a -18 % vs B&H a 0,1 % de frais ; **mort au-dela de 0,36-0,40 %/transaction** (arXiv 2602.10785, walk-forward, code reproductible) |
| RSI / MACD / Bollinger isoles | **inexistant** | aucune mesure serieuse publiee — **uniquement du contenu promotionnel** |
| Optimisation sur historique court | **documente nuisible** | Sharpe OOS negatif attendu (Bailey-Borwein-Lopez de Prado-Zhu) |
| TSMOM horizons longs | **modere, fragile** | signal fort, mais frais + liquidations annulent les profits (Han-Kang-Ryu 2023) |
| Momentum cross-sectional | **faible net de frais** | facteur reel, profits annules en pratique ; exige des small caps illiquides |
| Funding / cash-and-carry | **solide mais REFERME** | Sharpe 6,45 plein echantillon -> **4,06 en 2024** -> **negatif en 2025** (Borri-Liu-Tsyvinski-Wu) |
| DCA | **solide, CONTRE le DCA** | le lump sum gagne 62-74 % du temps, +2,3 % (Vanguard) |
| Vol targeting | solide hors crypto, **non etabli en crypto** | Sharpe +, rendement inchange, **turnover +** (donc frais) |
| **Buy & hold** | **le benchmark que rien n'a battu** | +29,09 % sur nos 22 j ; ~0,4 %/an de frais ; **DD -89,8 %** |

Points durs a retenir :

- **Notre cout (0,81 %/transaction) est 2 a 2,3x au-dessus du seuil de rupture publie** pour
  exactement notre famille de strategie. **Le -35 % n'est pas un bug de reglage, c'est le
  comportement attendu.**
- Hudson & Urquhart (Annals of OR 2019, 15 000 regles, correction data-snooping) : sur le seul test
  vraiment hors-echantillon, BTC donne **-0,10 % annualise, Sharpe -0,05**. Bitcoin est la crypto la
  **moins** rentable a trader techniquement, *parce qu'*elle est la plus liquide et la plus regardee.
- Borri et al. (2026, hebdo 2014-2025) : **Sharpe hebdo crypto 0,12 vs actions 0,07** — meilleur,
  mais pas d'un ordre de grandeur, paye par **-89,8 % de drawdown max**.
- Le seul avantage structurel du petit capital est **l'absence de contrainte de capacite**. Le seul
  desavantage structurel est **les frais** (facteur 8 vs un acteur de taille).

**Conclusion de la revue** : sur ETH/USD spot, long/flat, avec des frais retail, **aucune approche
documentee ne bat le buy & hold net de frais de facon robuste**. Nos mesures (0 % de fenetres WF
profitables, aucune TF positive OOS, IC englobant zero) sont **en accord exact avec la
litterature**. Il n'y a pas de configuration cachee a trouver.

---

## 5. Propositions, par ordre de rapport valeur / cout

### P1 — Arreter le 5 minutes (GRATUIT, effet garanti, aujourd'hui)

Le 5 min est arithmetiquement condamne : 98,6 % des signaux portent un mouvement plus petit que
l'aller-retour, et l'autocorrelation y est **negative** (contraire au suivi de tendance). C'est la
seule action de cette etude dont l'effet est certain sans aucune hypothese.

### P2 — Ordres limite maker (petit lot)

Ajouter `create_limit_buy/sell` avec `postOnly`, gestion du non-remplissage (timeout -> annulation
-> re-decision au cycle suivant), et basculer `config.FEE` sur `FEE_MAKER`. Aligne le bot sur la
**Divise le peage par ~2, ne cree aucun edge.**

### P3 — Hygiene de mesure (petit lot)

`paper --reset` qui **archive** l'etat au lieu de l'ecraser, et `stats --since`. Sans ca, le P&L
affiche restera pollue par l'ancien et aucun A/B ne sera lisible. (Constat : le -35,30 % affiche
aujourd'hui est **integralement** l'heritage d'avant le 20/08.)

### P4 — Mettre en production ce qui est deja valide (lot moyen)

Passer le serveur sur **TSMOM 365 j fige, rebalancement mensuel** (ou SMA 50/200 daily), sur donnees
journalieres. Deja code, deja valide OOS sur ~8 ans. Frais : 1,20 %/an en maker. **Attente honnete :
drawdown reduit, PAS de sur-performance** — l'etude #5 est formelle, l'avantage est du crisis-alpha.

### P5 — Etage 1 du mode adaptatif (lot moyen, spec deja ecrite)

`docs/design/MODE_ADAPTATIF_SPEC.md` : detecteur de regime risk-on / neutre / risk-off, **sans IA**,
avec **vote d'un ensemble de lookbacks** (180/270/365/450/540) pour ne pas dependre du seul 365 —
l'etude #5 a montre que 365 est encadre de deux valeurs perdantes. Si l'ensemble s'effondre alors
que 365 brillait, **c'est la preuve que 365 etait un accident de ce cycle**, et on veut le savoir
avant de risquer de l'argent.

### P6 — Realigner la promesse du projet (gratuit, mais c'est une decision)

Tout converge : ce logiciel **ne peut pas promettre du rendement**. Il peut **reduire le drawdown**.
C'est le garde-fou n.2 du projet (« risque d'abord »), et c'est le seul mecanisme mesure comme
fonctionnant. L'interface et la doc doivent le dire.

### Ecarte, explicitement

- **Modele predictif de prix** : rapport signal/bruit, non-stationnarite, trop peu de donnees, et
  surtout l'edge accessible est **sous les frais**. Ecarte tant que P1-P4 ne sont pas faits.
- **Short / levier** : hors garde-fous actuels (`MAX_FRACTION=1.0`, pas de marge). Frais de marge
  Kraken faibles (rollover 0,01-0,04 % / 4 h) mais **liquidation forcee 2 %** et perte non plafonnee.
- **HFT / market making / arbitrage de latence** : aucune litterature ne soutient l'accessibilite
  retail. Inaccessible.
- **Funding / cash-and-carry** : le seul edge **structurel** identifie (prime payee par des acheteurs
  a levier), mais Sharpe negatif en 2025, exige un compte derives et un capital sur deux jambes.

---

## 6. Ce qui n'est PAS etabli (a ne pas oublier)

1. **Le palier reel du compte** — la grille publique est tranchee (§3.2), mais le palier applique au
   compte de Mandar n'a pas pu etre lu (pas de `.env` accessible). SUPPOSE palier 1.
2. **Le seuil « Assets on Platform » par palier** apres le changement du 9 juillet 2026.
3. **Frommel & Deprez (IRFA 2024)**, qui conclut que les regles techniques *battent* le B&H
   hors-echantillon sur BTC : **non auditable** (403 sur SSRN et ScienceDirect). C'est le
   contre-exemple le plus serieux a la conclusion du §4 et il reste ouvert.
4. **Vol targeting mesure sur crypto seule, net de frais retail** : non etabli.
5. **Timing BTC par moyenne 200 j en mensuel** : aucune etude serieuse trouvee. **Le backtester
   maison peut le trancher en interne** — c'est le seul test qui manque au dossier, et il est gratuit.
6. **Le HOLDOUT RESTE VIERGE.** Aucun `--final`. C'est une cartouche unique, decision explicite de
   Mandar, a ne pas gaspiller sur une hypothese non preparee.

---

## 7. Etat des decisions

> **Regle de lecture** : ce document est ecrit par Claude. Les mesures sont verifiables (§2, §3),
> les recommandations sont **les siennes** et engagent leur auteur, pas Mandar. Rien ici ne doit
> etre presente comme une position que Mandar aurait prise. Ce qui suit trace ce qui a ete
> effectivement decide PAR LUI, verbatim, et ce qui reste ouvert.

| | Statut |
|---|---|
| Verifier la grille de frais | **FAIT** 2026-09-01 : `config.py` exact (maker 0,40 / taker 0,80). Palier reel du compte non lu (cf. §6.1) |
| Lots P2 + P3 (maker, reset, --since) | **AUTORISES** par Mandar (2026-09-01 : « *met en place la strategie d'integration du coup de ce qui manque et du reste* ») |
| Bascule production TSMOM 365 daily (P4) | **AUTORISEE** par Mandar (2026-09-01 : « *Passe en TSMOM 365 daily sur le serveur si tu veux* ») |
| Arret du 5 min (P1) | consequence directe de P4 — le 5 min disparait avec la bascule |
| Realignement de la promesse du projet (P6) | **OUVERT** — recommandation de Claude, non soumise a Mandar avec les elements permettant d'en juger |

**Ce qui reste a decider, et ce qu'il faut pour le decider** : P6 demande de trancher si le projet
affiche « reduction de drawdown » plutot que « rendement ». Ce n'est pas une question technique
mais une question de ce qu'on attend de l'outil. Elle ne doit etre posee qu'accompagnee, en langage
clair, de ce que chaque option promet et de ce qu'elle renonce a promettre.
