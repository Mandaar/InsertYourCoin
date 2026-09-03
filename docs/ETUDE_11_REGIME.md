# Étude #11 — Détecteur de régime par VOTE de plusieurs horizons (étage 1, sans IA)

> Sujet : `docs/design/MODE_ADAPTATIF_SPEC.md` §3 **étage 1** (détecteur de régime, aucun
> paramètre optimisé, **vote d'un ensemble de lookbacks**) et §3 **étage 2** (réponse par
> régime). Point 3 du cap de `CLAUDE.md` (décidé le 2026-09-02).
> Juge : le walk-forward hors-échantillon, jamais le backtest (garde-fou n°1 de `CLAUDE.md`).
> **Le holdout sacré reste vierge** : aucun `--final`, aucun `--use-holdout`, coupe à la
> frontière gelée `config.HOLDOUT_REFERENCES`.

---

## 0. Critères gelés — écrits AVANT toute mesure

**Horodatage de gel : 2026-09-03 17:16 (heure locale, 15:16 UTC).**
À cet instant : `trading/regime.py` n'existait pas, aucun vote n'avait été calculé, aucun
walk-forward de cette étude n'avait été lancé. Les seules commandes déjà passées étaient
la suite `pytest` de référence (**811 passed**) et un chargement de données destiné à
vérifier que le segment de recherche est bien celui de l'étude #5 (BTC/ETH 2604 bougies
2017-08-17 → 2024-10-02, SOL 1732 bougies 2020-08-11 → 2025-05-08). Cette section est le
premier contenu écrit du fichier ; toute modification ultérieure est signalée en §7
(« Ce qui a bougé après coup »).

### 0.1 La cible (M2)

La cible est le **drawdown maximal hors-échantillon**, mesuré sur la **courbe d'équité OOS
continue** (convention de l'étude #5 §1 : un drawdown réel peut traverser une frontière de
fenêtre, donc on ne le mesure pas fenêtre par fenêtre). Comparaison à span **strictement
identique** pour tous les contendants.

Ne sont **pas** la cible et ne seront jamais invoqués comme succès : le rendement cumulé,
le Sharpe seul, le nombre de fenêtres profitables, le backtest in-sample. Le rendement
n'entre dans le verdict que comme **garde-fou de non-destruction** (critère R3) et comme
**prime d'assurance mesurée**, jamais comme preuve de réussite.

Le drawdown par fenêtre (convention de l'étude #8) est publié **en plus**, pour rendre
les deux études comparables — il n'arbitre rien.

### 0.2 Le protocole, chiffré

| Élément | Valeur gelée |
|---|---|
| Source de données | `binance` daily (`1d`), historique long depuis le listing |
| Actifs | BTC/USD, ETH/USD, SOL/USD |
| Segment utilisable | bougies **antérieures à la frontière de holdout gelée** (`config.HOLDOUT_REFERENCES` → `optimizer.holdout_start`) : BTC/ETH < 2024-10-03, SOL < 2025-05-09 |
| Fenêtres walk-forward | **4**, `train_frac = 0.5` — mêmes fenêtres que les études #5 et #8 |
| Paramètres | **FIGÉS**, aucune optimisation de grille (`n_trials = 1`) |
| Horizons du vote | **180 / 270 / 365 / 450 / 540**, imposés par la spec — non choisis, non optimisés, jamais retirés a posteriori |
| Règle de vote | **majorité stricte** : 3 voix sur 5 → RISK-ON ; sinon RISK-OFF (cash) |
| Frais du verdict | **maker 0,40 %/côté** (`config.FEE_MAKER`, le serveur passe en ordres limite) + slippage 5 bps/côté |
| Frais de la vérification croisée | **taker 0,80 %/côté** (`config.FEE`), pour reproduire les études #5 et #8 |
| Risque | aucun stop / take-profit / trailing / sizing (défauts `config`) — on juge le SIGNAL |
| Comparateur « sans T » n°1 (M22) | **détention simple** (buy & hold), même moteur, mêmes fenêtres, net de frais |
| Comparateur « sans T » n°2 (M22) | **TSMOM 365 seul** (référence validée étude #5) |
| Comparateurs de dispersion | TSMOM **180, 270, 365, 450, 540** seuls, chacun sur les mêmes fenêtres |

### 0.3 Budget de configurations — déclaré à l'avance

**Une seule configuration est testée : le vote des 5 horizons imposés, majorité 3/5.**
Aucun balayage, aucun seuil ajusté, aucune variante « améliorée » ne sera essayée après
avoir vu un résultat. Si une deuxième configuration devait exister, elle serait écrite en
§7 avec sa raison et le verdict resterait prononcé sur celle-ci.

Les 5 horizons seuls ne sont pas des configurations concurrentes : ce sont des
**mesures de dispersion**, publiées intégralement, jamais un menu où choisir le meilleur
(interdiction explicite de la spec §6 et de l'étude #5 §4).

### 0.4 Ce qui compte comme RÉUSSITE (les quatre à la fois)

- **R0 — pas de lookahead.** La causalité est prouvée par test : réécrire les données après
  la bougie k ne change aucun signal ≤ k. Si ce test échoue, **tous les chiffres de l'étude
  sont nuls et non avenus**, quel que soit leur contenu.
- **R1 — protection (la cible).** Drawdown max OOS du vote **≤ drawdown max de la détention
  simple − 5 points**, sur **3 actifs sur 3**.
  *Provenance du seuil de 5 points* : la référence validée (TSMOM 365, étude #5 §2) réduit
  le drawdown de **23,5 pts** (BTC), **22,1 pts** (ETH) et **6,9 pts** (SOL) ; son maillon
  faible est SOL à 6,9 pts. Le seuil est posé **sous** ce maillon faible (marge pour le
  changement de régime de frais taker → maker), et il reste au-dessus du bruit : moins de
  5 points d'écart de drawdown sur ~3,5 ans ne se distingue pas d'un décalage de calendrier.
  Le seuil vient donc d'une mesure **antérieure** à cette étude, pas des points testés ici.
- **R2 — robustesse (la raison d'être du vote).** Sur **3 actifs sur 3**, le vote doit faire
  **au moins aussi bien que le PIRE des 5 horizons seuls**, sur les deux axes :
  drawdown max OOS et rendement net OOS. Formellement :
  `DD(vote) ≤ max_pire(DD des 5)` et `ret(vote) ≥ min(ret des 5)`.
  C'est le test de la spec §3 : si tout dépend d'un membre, c'est du 365 déguisé.
- **R3 — coût accepté, et pas de destruction.** Le vote a le droit de rendre du rendement
  face à la détention simple : c'est la **prime d'assurance**, connue et mesurée (étude #5
  §3 : +43 % contre +122 % sur la fenêtre de rebond). Ce qui n'est pas accepté :
  - **R3a** : rendement cumulé OOS net **≥ 0 sur 3 actifs sur 3** (un protecteur qui détruit
    du capital en nominal n'est pas un protecteur ; c'est exactement ce qui arrive à TSMOM
    180 et 540 sur BTC, étude #5 §4) ;
  - **R3b** : coût en frais du vote **≤ 2× celui de TSMOM 365** sur chaque actif, et nombre
    d'allers-retours compté et publié (spec §4.3).

### 0.5 Ce qui compte comme ÉCHEC (un seul suffit)

- **E0** — le test de causalité échoue → étude nulle.
- **E1** — R1 tombe : le vote ne réduit pas le drawdown d'au moins 5 points sur au moins un
  des trois actifs.
- **E2** — R2 tombe : le vote fait **pire que le pire** de ses membres sur au moins un actif
  (drawdown ou rendement) → l'ensemble ne stabilise rien.
- **E3** — R3a tombe : rendement net OOS négatif sur au moins un actif.
- **E4** — la vérification croisée échoue : le harness ne reproduit pas TSMOM 365 des études
  #5/#8 à 0,0 point près (BTC +55,9 %, ETH +98,2 % au régime taker) → le harness n'est pas
  fiable et **rien de ce qu'il produit ne vaut**.

### 0.6 Les trois verdicts possibles — sans ambiguïté

1. **VERDICT A — SUCCÈS.** R0 + R1 + R2 + R3 tous tenus. Le vote protège et il est robuste :
   l'étage 1 peut passer au **lot D de la spec** (paper en mode observation, sans agir),
   jamais directement en live.
2. **VERDICT B — ÉCHEC UTILE : « 365 était un accident de ce cycle ».** Le vote échoue (E1
   ou E2) **alors que TSMOM 365 seul, mesuré sur les mêmes fenêtres, tient R1**. C'est la
   preuve, écrite noir sur blanc, que le résultat de l'étude #5 tenait à une valeur unique
   encadrée de perdantes, et non à un mécanisme robuste. **On ne construit rien dessus** —
   ni paper, ni live. Ce verdict est un **succès de l'étude** (l'information est obtenue
   avant d'avoir risqué de l'argent) et un **rejet du mécanisme**.
3. **VERDICT C — INDÉCIS.** Tout le reste (ni tous les R, ni un E franc ; par exemple R1
   tenu sur 2 actifs sur 3, ou R2 tenu de justesse sur un seul axe). Traité comme un échec
   pour la décision d'usage : la phrase écrite est **« ça n'apporte rien de démontrable »**,
   jamais « prometteur, à affiner ». Aucun passage au lot D.

### 0.7 Ce que cette étude ne fera pas

- pas de `--final`, pas de `--use-holdout` : le holdout ne se reconstitue pas (étude #5 §7.6) ;
- pas de retrait, d'ajout ou de repondération d'un horizon après avoir vu les résultats ;
- pas de seuil de volatilité, de pente ou de drawdown ajusté « pour que ça passe » ;
- pas de stop / take-profit / trailing ajoutés pour rattraper un vote qui perd ;
- aucun serveur, aucune fenêtre, aucun navigateur : ligne de commande uniquement.

---

## 1. Ce qui a été construit

- **`trading/regime.py`** — `RegimeVoteStrategy`, enregistrée dans `STRATEGIES` sous la clé
  **`regime`** (donc `build_strategy("regime")`, walk-forward et pages web y ont accès comme
  à n'importe quelle autre stratégie). Cinq voix, **une par horizon**, chacune étant
  littéralement `TSMomentum(L)` — la brique validée de l'étude #5, réutilisée telle quelle
  et non ré-écrite (test dédié : chaque colonne du vote est égale au signal de `TSMomentum`).
  Régime = **majorité stricte calculée** (`len(lookbacks) // 2 + 1` = 3/5) : ce n'est pas un
  paramètre, il n'y a rien à régler. `warmup_bars = 600` (540 + 60) est **déclaré** et lu par
  `optimizer._declared_warmup`, sinon le membre le plus lent passerait chaque fenêtre
  hors-échantillon muet.
- **`trading/strategies.py`** — 10 lignes : le même enregistrement tolérant que `predictive`
  (les deux ordres d'import aboutissent au même registre). Aucune autre modification.
- **`scripts/etude11_regime.py`** — le juge : chargement Binance, troncature à la frontière de
  holdout **gelée**, walk-forward à paramètres figés, 8 contendants sur **exactement** les
  mêmes fenêtres, double mesure avec et sans frais, drawdown continu **et** par fenêtre,
  application automatique des critères gelés (les FAIL sont imprimés en premier).
- **`tests/test_regime.py`** — 30 tests, sans réseau ni clés.

### 1.1 L'état NEUTRE (exposition ½) de l'étage 2 n'est PAS implémenté — raison mesurée

Deux faits du code existant, tous deux **hors du périmètre de cette mission** :

1. `trading/backtester.py` fait `signal = strategy.generate_signals(df).astype(int)` puis teste
   `desired[i] == 1` / `== 0`. Un signal 0,5 serait **tronqué à 0** : le NEUTRE deviendrait
   silencieusement du cash — pire que de ne pas l'implémenter.
2. `tests/test_strategies.py::test_signal_shape` exige, pour **chaque** clé du registre,
   `set(sig.unique()).issubset({0, 1})`.

Le NEUTRE se branche donc **côté moteur** (là où `Backtester._size_series` calcule déjà une
fraction de capital pour le sizing par volatilité), pas côté stratégie. Le point d'extension
existe et est nommé : `RegimeVoteStrategy.vote_counts()` expose le nombre de voix (0 à 5), qui
est exactement la grandeur dont une exposition graduée aurait besoin. C'est un lot séparé,
avec ses propres critères gelés — et le §4 ci-dessous montre qu'il n'y a, en l'état, aucune
raison de le lancer.

### 1.2 Les trois autres entrées de la spec ne sont pas non plus dans cet étage

La spec §3 étage 1 liste aussi la pente de la moyenne longue, la volatilité réalisée rapportée
à sa médiane et le drawdown courant. Elles ne sont **pas** implémentées ici, volontairement :
cette étude mesure **le vote**, et une seule chose à la fois (M22). Ajouter une entrée en même
temps rendrait le résultat non attribuable. Chacune devra gagner sa place seule, avec ses
propres critères gelés — et des seuils de bon sens nommés, jamais issus d'un balayage.

---

## 2. Vérification croisée — le harness reproduit les études #5 et #8 (critère E4)

Régime **taker** (celui des études #5 et #8), mêmes fenêtres, paramètres figés :

| Actif | TSMOM 365 — ce script | `walk_forward` du projet | Publié étude #5 §2 | Écart |
|---|---:|---:|---:|---:|
| BTC/USD | **+55,9 %** | +55,9 % | +55,9 % | **0,0000 pt** |
| ETH/USD | **+98,2 %** | +98,2 % | +98,2 % | **0,0000 pt** |
| SOL/USD | **+264,6 %** | +264,6 % | +264,6 % | **0,0000 pt** |

Drawdowns continus, même régime taker — reproduits eux aussi **au dixième de point** :

| Actif | TSMOM 365 mesuré | publié #5 | B&H mesuré | publié #5 |
|---|---:|---:|---:|---:|
| BTC/USD | −53,1 % | −53,1 % | −76,6 % | −76,6 % |
| ETH/USD | −57,2 % | −57,2 % | −79,3 % | −79,3 % |
| SOL/USD | −52,9 % | −52,9 % | −59,8 % | −59,8 % |

Et le vote lui-même, régime maker : script **+34,1 / +66,7 / +187,9 %** contre
`trading.optimizer.walk_forward` **+34,1 / +66,7 / +187,9 %** — écart **0,0000 pt** sur les
trois actifs. Le script n'a donc pas son propre moteur.

**E4 n'est pas déclenché : les chiffres qui suivent valent.**

---

## 3. Résultats hors-échantillon — frais **maker 0,40 %/côté** + slippage 5 bps

Fenêtres OOS identiques pour les 8 contendants. `DDcont` = drawdown max sur la courbe OOS
continue (**la cible**) ; `DDfen` = pire drawdown à l'intérieur d'une fenêtre (indicatif) ;
`frais` = points de rendement perdus en frais, mesurés par soustraction (net vs brut).

### 3.1 BTC/USD — OOS 2021-03-11 → 2024-10-02 (4 × ~325 bougies)

| Contendant | Net | Brut | Frais | **DDcont** | DDfen | Sharpe cont. | Ordres |
|---|---:|---:|---:|---:|---:|---:|---:|
| Détention simple (B&H) | +6,6 % | +8,6 % | 1,9 pts | **−76,6 %** | −66,7 % | 0,32 | 4 |
| **TSMOM 365 seul** | **+60,4 %** | +65,5 % | 5,1 pts | **−53,1 %** | −53,1 % | 0,50 | 5 |
| TSMOM 180 seul | −14,5 % | +0,1 % | 14,6 pts | −67,6 % | −62,7 % | 0,12 | 18 |
| TSMOM 270 seul | +76,5 % | +88,0 % | 11,5 pts | −53,1 % | −53,1 % | 0,55 | 8 |
| TSMOM 450 seul | +55,1 % | +63,0 % | 7,9 pts | −53,1 % | −53,1 % | 0,48 | 7 |
| TSMOM 540 seul | −30,8 % | −29,2 % | 1,6 pts | −66,9 % | −53,1 % | 0,05 | 4 |
| **VOTE 5 horizons (3/5)** | **+34,1 %** | +43,5 % | 9,4 pts | **−53,4 %** | −53,1 % | 0,40 | 9 |

### 3.2 ETH/USD — OOS 2021-03-11 → 2024-10-02 (4 × ~325 bougies)

| Contendant | Net | Brut | Frais | **DDcont** | DDfen | Sharpe cont. | Ordres |
|---|---:|---:|---:|---:|---:|---:|---:|
| Détention simple (B&H) | +29,3 % | +31,7 % | 2,4 pts | **−79,3 %** | −71,7 % | 0,48 | 4 |
| **TSMOM 365 seul** | **+110,5 %** | +125,2 % | 14,7 pts | **−57,2 %** | −57,2 % | 0,64 | 9 |
| TSMOM 180 seul | +70,8 % | +110,1 % | 39,4 pts | −57,2 % | −57,2 % | 0,55 | 24 |
| TSMOM 270 seul | +70,9 % | +87,0 % | 16,1 pts | −61,8 % | −57,2 % | 0,55 | 11 |
| TSMOM 450 seul | +10,9 % | +19,7 % | 8,8 pts | −65,7 % | −57,2 % | 0,37 | 10 |
| TSMOM 540 seul | −35,1 % | −29,3 % | 5,8 pts | −79,3 % | −71,7 % | 0,17 | 11 |
| **VOTE 5 horizons (3/5)** | **+66,7 %** | +86,5 % | 19,9 pts | **−57,2 %** | −57,2 % | 0,54 | 14 |

### 3.3 SOL/USD — OOS 2022-12-25 → 2025-05-08 (4 × ~216 bougies)

| Contendant | Net | Brut | Frais | **DDcont** | DDfen | Sharpe cont. | Ordres |
|---|---:|---:|---:|---:|---:|---:|---:|
| Détention simple (B&H) | +1 310,7 % | +1 336,3 % | 25,7 pts | **−59,8 %** | −59,8 % | 1,66 | 4 |
| **TSMOM 365 seul** | +282,6 % | +303,9 % | 21,3 pts | **−51,6 %** | −51,6 % | 1,14 | 7 |
| TSMOM 180 seul | +290,5 % | +339,1 % | 48,6 pts | −57,3 % | −57,3 % | 1,12 | 14 |
| TSMOM 270 seul | +299,5 % | +341,1 % | 41,6 pts | −61,4 % | −61,4 % | 1,17 | 12 |
| TSMOM 450 seul | +258,2 % | +263,0 % | 4,9 pts | −59,8 % | −59,8 % | 1,09 | 3 |
| TSMOM 540 seul | +157,7 % | +163,6 % | 5,9 pts | −59,8 % | −59,8 % | 0,91 | 4 |
| **VOTE 5 horizons (3/5)** | +187,9 % | +212,2 % | 24,3 pts | **−63,6 %** | −63,6 % | 0,97 | 10 |

### 3.4 La dispersion que le vote était censé absorber — elle est énorme

Rendement net OOS des 5 horizons **voisins**, régime maker :

| Actif | 180 | 270 | 365 | 450 | 540 | Écart max−min | Moyenne des 5 | **VOTE** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC/USD | −14,5 % | +76,5 % | +60,4 % | +55,1 % | −30,8 % | **107 pts** | +29,3 % | **+34,1 %** |
| ETH/USD | +70,8 % | +70,9 % | +110,5 % | +10,9 % | −35,1 % | **146 pts** | +45,6 % | **+66,7 %** |
| SOL/USD | +290,5 % | +299,5 % | +282,6 % | +258,2 % | +157,7 % | 142 pts | +257,7 % | **+187,9 %** |

Deux lectures, toutes deux mesurées :
- l'instabilité de l'étude #5 est **confirmée et aggravée** : à frais maker, cinq horizons
  voisins d'un même signal produisent jusqu'à **146 points** d'écart, et deux d'entre eux
  restent négatifs sur BTC comme sur ETH ;
- le vote se comporte **comme une moyenne**, pas comme une sélection du meilleur : il atterrit
  près de la moyenne des cinq sur BTC/ETH, et **en dessous** sur SOL (+187,9 % contre +257,7 %
  de moyenne). Un ensemble moyenne ; il n'hérite pas de la protection du meilleur membre.

---

## 4. Verdict contre les critères gelés — **VERDICT B**

### 4.1 Les échecs, d'abord

| Critère | Actif | Mesure | Exigé |
|---|---|---|---|
| **R1 protection** | **SOL/USD** | DD vote **−63,6 %** vs B&H **−59,8 %** → **−3,8 pts** (le vote creuse **plus** que la détention simple) | ≥ +5 pts évités |
| **R2 robustesse** | **SOL/USD** | DD vote **−63,6 %** vs **pire** de ses 5 membres **−61,4 %** | pas plus profond que le pire membre |

**E1 et E2 sont tous deux déclenchés.** Le rendement n'est pas en cause : sur SOL le vote fait
+187,9 %, au-dessus du pire membre (+157,7 %). C'est bien la **cible** — le drawdown — qui tombe.

### 4.2 Ce qui passe

- **R1 tenu sur BTC (+23,2 pts évités) et ETH (+22,1 pts)** — le vote protège réellement sur
  ces deux actifs, c'est mesuré et ce n'est pas rien.
- **R2 tenu sur BTC et ETH** (DD −53,4 % vs pire membre −67,6 % ; −57,2 % vs −79,3 %).
- **R3a tenu 3/3** : +34,1 %, +66,7 %, +187,9 % — le vote ne détruit pas de capital en nominal.
- **R3b tenu 3/3** : frais du vote 9,4 / 19,9 / 24,3 pts contre 5,1 / 14,7 / 21,3 pts pour
  TSMOM 365 — plus cher, mais sous le plafond de 2×. Le vote fait 9 / 14 / 10 ordres OOS.
- **R0 tenu** : causalité prouvée par test, dans les deux sens (futur ×4 et ÷4), et le test
  est prouvé capable de **mordre** (une stratégie tricheuse fabriquée exprès est détectée).

### 4.3 Le point qui décide

| | BTC | ETH | SOL | Bilan |
|---|---:|---:|---:|---|
| Points de drawdown évités — **TSMOM 365 seul** | +23,5 | +22,1 | **+8,2** | **R1 : 3/3** |
| Points de drawdown évités — **VOTE** | +23,2 | +22,1 | **−3,8** | **R1 : 2/3** |

Sur les **mêmes fenêtres**, avec les **mêmes frais** : **TSMOM 365 seul protège sur 3 actifs
sur 3, le vote sur 2 sur 3.** Le vote ne fait mieux que 365 seul **sur aucun actif**, ni en
drawdown, ni en rendement (+34,1 contre +60,4 ; +66,7 contre +110,5 ; +187,9 contre +282,6),
et il coûte davantage de frais partout.

C'est exactement la situation décrite par la spec §3 : *« Si le résultat de l'ensemble
s'effondre alors que 365 seul brillait, c'est la preuve que 365 était un accident de ce
cycle. »* Le résultat de 365 n'est pas transférable à un mécanisme voisin : diluer
l'horizon dans un vote de ses voisins **détruit la protection**, parce que ces voisins
n'ont pas la même protection à apporter (180 et 540 sont négatifs sur BTC et ETH, et sur
SOL aucun membre n'est protecteur sauf 365).

> **VERDICT B — ÉCHEC UTILE. Le vote de 5 horizons est REJETÉ.**
> On ne le branche ni en paper ni en live. Le lot D de la spec n'est pas ouvert.
> L'information obtenue est plus précieuse que le mécanisme perdu : **le crisis-alpha
> mesuré à 365 j dans l'étude #5 tient à cette valeur unique et ne survit pas à sa propre
> généralisation.** Ce constat arrive avant tout risque d'argent, ce qui était le but.

---

## 5. Ce que le vote fait réellement, minute par minute (diagnostic)

Mesuré sur les mêmes courbes OOS continues, frais maker :

| Actif | Contendant | Exposition moyenne | Creux max | Du → au |
|---|---|---:|---:|---|
| BTC | B&H | 100 % | −76,6 % | 2021-11-08 → 2022-11-21 |
| BTC | TSMOM 365 | 62 % | −53,1 % | 2021-04-13 → 2021-07-20 |
| BTC | VOTE | 67 % | −53,4 % | 2021-11-08 → **2023-06-14** |
| ETH | TSMOM 365 | 69 % | −57,2 % | 2021-05-11 → 2021-07-20 |
| ETH | VOTE | 68 % | −57,2 % | 2021-05-11 → 2021-07-20 |
| SOL | B&H | 100 % | −59,8 % | 2025-01-18 → 2025-04-08 |
| SOL | TSMOM 365 | 59 % | −51,6 % | 2025-01-18 → 2025-05-07 |
| SOL | VOTE | 60 % | **−63,6 %** | 2025-01-18 → 2025-05-07 |

Le vote est investi ~60-68 % du temps, comme TSMOM 365 — **il n'est pas plus prudent, il est
prudent au mauvais moment**. Sur SOL, exposé 60 % du temps, il réussit à creuser **plus** que
l'actif détenu à 100 % : il ressort après les rebonds et rentre après les reprises, et la
perte de chaque aller-retour raté s'ajoute au creux. Sur BTC, son creux s'étale sur **19 mois**
(2021-11 → 2023-06) là où celui de 365 tient en 3 mois : même profondeur, saignée beaucoup
plus longue.

Le nombre moyen de voix haussières est de **3,15 / 3,35 / 3,17 sur 5** (BTC / ETH / SOL) :
le vote passe son temps **à la frontière de la majorité**, ce qui explique à la fois le
surcroît d'ordres et son comportement de moyenne.

---

## 6. Ce que ça change pour le cap

- Le point 3 du cap (`CLAUDE.md`) demandait « un détecteur de régime sans IA, vote de
  plusieurs horizons pour ne dépendre d'aucun ». **Il est construit, testé et mesuré : il ne
  tient pas sa promesse.** Ne pas le mettre sur le serveur.
- La seule protection encore debout après cette étude reste **TSMOM 365 seul** — et elle
  arrive maintenant avec une fragilité **doublement** documentée : sensible au lookback
  (étude #5 §4) et **non généralisable à ses propres voisins** (ici). Toute mise en service
  de ce mécanisme doit être présentée comme un pari sur une valeur unique, pas comme un
  système robuste.
- L'étage 2 (exposition graduée) et l'étage 3 (« petite IA ») **ne doivent pas être lancés** :
  la spec dit « on ne passe au suivant que si le précédent a passé le walk-forward ». Il ne
  l'a pas passé.
- Ce qui reste ouvert, et qui n'est pas dans cette étude : les trois autres entrées de la
  spec (pente, volatilité vs médiane, drawdown courant), testables **une par une** avec la
  même mécanique. Rien ne dit qu'elles marcheront ; l'historique du projet (dix études) dit
  plutôt le contraire.
- **À rapprocher de l'étude #10**, publiée le même jour (point 2 du cap, commit `21f9498`) :
  le SMA 200 j mensuel évite 14,6 points de drawdown, mais le seul choix du **jour de
  décision** en déplace 27,8 — « on mesure un calendrier, pas une protection ». Sa conclusion
  disait « le point 3 en sort renforcé ». **La présente étude EST le point 3, et il ne passe
  pas.** Les deux résultats disent la même chose sous deux angles : la protection mesurée sur
  ce corpus est **du même ordre de grandeur que sa propre incertitude** — le choix du jour
  (#10) ou celui de l'horizon (#11) la font apparaître et disparaître.

---

## 7. Ce qui a bougé après coup — transparence

1. **Bug de signe dans l'évaluateur de critères, trouvé et corrigé AVANT le verdict.** La
   première implémentation de `verdict()` calculait « points évités » comme
   `dd_bh − dd_vote` (drawdowns **négatifs** : formule inversée) et prenait le « pire
   membre » avec `max()` au lieu de `min()`. Symptôme qui a mis la puce à l'oreille : le run
   annonçait « −23,2 pts évités » sur BTC là où le vote protégeait manifestement. Corrigé
   dans `scripts/etude11_regime.py`, re-run complet, et **résultat recalculé à la main sur les
   trois actifs pour recoupement**. Les critères eux-mêmes (§0.4) n'ont pas été touchés — seul
   le code qui les applique.
2. **Notation de R2 clarifiée.** Le texte gelé dit en toutes lettres « le vote doit faire au
   moins aussi bien que le PIRE des 5 horizons seuls » ; la formule abrégée qui suivait
   (`DD(vote) ≤ max_pire(...)`) était ambiguë sur le signe. Lecture appliquée, conforme aux
   mots : **le creux du vote ne doit pas être plus profond que celui du pire membre**
   (`dd_vote ≥ min(dd_membres)`). Aucun assouplissement : c'est le critère le plus permissif
   des deux lectures possibles, et il **tombe quand même** sur SOL.
3. **Chevauchement B / C dans le texte gelé.** Le verdict C cite « R1 tenu sur 2 actifs sur
   3 » comme exemple, or c'est aussi une condition d'entrée du verdict B lorsque TSMOM 365
   seul tient R1 sur 3/3 — ce qui est le cas ici. B est la règle **spécifique** (elle nomme
   l'échec **et** le comportement de la référence), C est le résidu (« tout le reste »), donc
   B s'applique. **La conséquence pratique est identique dans les deux cas** : rejet, aucun
   passage au lot D. Seule l'explication diffère. Cette ambiguïté de rédaction est signalée
   ici plutôt que résolue en silence.
4. **Aucun horizon n'a été retiré, ajouté ou repondéré** après avoir vu les résultats. Aucune
   deuxième configuration n'a été essayée. Le budget déclaré en §0.3 est tenu.

---

## 8. Caveats — à relire avant toute décision

1. **Le holdout est intact.** Aucun `--final`, aucun `--use-holdout` ; coupe à la frontière
   gelée (BTC/ETH < 2024-10-03, SOL < 2025-05-09), vérifiée par le nombre de bougies de
   recherche identique à l'étude #5 (2604 / 2604 / 1732).
2. **Placement des fenêtres.** Comme dans l'étude #5, l'OOS de BTC/ETH démarre près d'un
   sommet (krach à éviter, favorable au suiveur de tendance) et celui de SOL au creux absolu
   (aucun krach majeur, favorable à la détention). L'échec du vote sur SOL est donc **en
   partie** un effet de placement — mais TSMOM 365 seul, sur **le même** placement, protège
   quand même (+8,2 pts). L'argument « c'est la faute de la fenêtre » ne sauve pas le vote.
3. **Le régime de frais a changé** par rapport aux études #5/#8 (maker 0,40 % au lieu de taker
   0,80 %), conformément au passage aux ordres limite. Cela **avantage** mécaniquement les
   stratégies qui tournent beaucoup, donc le vote : il échoue malgré cet avantage.
4. **Un cycle et demi, trois majors liquides.** Le drawdown maximal est un estimateur très
   instable : une seule séquence de marché le décide. Les chiffres sont des ordres de
   grandeur, jamais des cibles (étude #5 §7.2).
5. **Ce qui n'est pas testé ici** : le vote sur d'autres actifs, en cadence hebdomadaire ou
   mensuelle, avec un délai de confirmation, ou pondéré autrement que par majorité simple.
   Rien de tout cela n'a été mesuré, donc rien n'en est affirmé.
6. **USDT vs USD** : recherche sur Binance USDT, exécution réelle sur Kraken USD (écarts réels
   mais mineurs en daily).

---

## 9. Reproduire

```bash
# Le juge (sortie terminal, aucune fenêtre, holdout jamais chargé) :
E:\Projets\InsertYourCoin\.venv\Scripts\python.exe scripts/etude11_regime.py

# Les tests (sans réseau ni clés) :
E:\Projets\InsertYourCoin\.venv\Scripts\python.exe -m pytest tests/test_regime.py -q
```
