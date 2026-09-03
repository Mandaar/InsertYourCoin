# Étude #10 — Timing BTC par SMA 200 j en cadence MENSUELLE

> Le dernier test du dossier de recherche (`CLAUDE.md` §Le cap, point 2).
> Protocole **gelé** dans `docs/ETUDE_9_ALLOCATION.md` §4.4 — recopié intégralement au §1
> ci-dessous, **non modifié**. Juge : le walk-forward hors-échantillon.
> **Holdout sacré INTACT** : aucun `--final`, aucun `--use-holdout`, coupe à la frontière
> gelée `optimizer.holdout_start`, exactement comme l'étude #8.

---

## 0. Critères gelés — écrits AVANT toute mesure

**Horodatage de gel : 2026-09-03, avant le premier backtest de cette étude.**
Aucun chiffre de SMA 200 mensuel n'existait quand cette section a été écrite ; le script
`scripts/etude10_sma200_mensuel.py` n'avait pas encore été exécuté une seule fois. Toute
modification ultérieure de cette section est signalée explicitement au §6.

### 0.1 La question, et la consigne qui arbitre (M24)

Deux consignes se contredisent partiellement sur ce test, et il faut le dire avant de mesurer :

| Consigne | Ce qu'elle exige |
|---|---|
| **Protocole gelé, étude #9 §4.4 point 8** | « battre le buy & hold **net de frais** en hors-échantillon. Un drawdown réduit sans rendement supérieur est un **échec** au regard de la question posée » |
| **`CLAUDE.md` §WHY + §Le cap point 2** (réécrits le 2026-09-02, « Go » de Mandar) | le projet ne cherche **plus** de rendement ; il cherche à savoir si la méthode **protège**. « S'il confirme *protection, pas rendement*, le dossier de recherche est CLOS » |

**La consigne qui arbitre le verdict principal est `CLAUDE.md` §Le cap point 2** : la cible
est la **PROTECTION** (drawdown évité), le rendement net étant un **coût** à borner, pas un
objectif. Le critère de l'étude #9 §4.4 point 8 n'est **pas** supprimé : il est mesuré et
publié comme **axe secondaire « rendement »**, avec son propre verdict, au §4.2. Les deux
verdicts sont donnés séparément ; aucun des deux n'est choisi après avoir vu les chiffres.

### 0.2 La cible (M2)

La cible est le couple **(drawdown maximal hors-échantillon, rendement cumulé NET DE FRAIS
hors-échantillon)**, comparé à **ne rien faire** (buy & hold passé par le même moteur, mêmes
frais, mêmes fenêtres). Ne sont **pas** des cibles et ne seront jamais invoqués comme succès :
le rendement brut, le backtest in-sample, la volatilité seule, le nombre de fenêtres positives,
le taux de bonnes décisions.

### 0.3 Le protocole, chiffré

| Élément | Valeur gelée |
|---|---|
| Source de données | `binance` daily (`1d`), historique long depuis le listing (cache `data/history/`) |
| Actif du verdict | **BTC seul** (protocole §4.4 point 1) |
| Actifs de robustesse (hors verdict) | ETH, SOL — publiés séparément au §3.3, ne peuvent ni sauver ni condamner le verdict |
| Segment utilisable | bougies **antérieures à la frontière de holdout gelée** (`optimizer.holdout_start`) : BTC/ETH < 2024-10-03, SOL < 2025-05-09. Dernière bougie (en formation) exclue avant coupe |
| Fenêtres walk-forward | **4**, `train_frac = 0.5` — mêmes réglages que les études #5 et #8 |
| Signal | `close > SMA(200 jours)` évalué **uniquement** aux jours de décision mensuels ; position **tenue inchangée** entre deux décisions ; flat tant que la SMA 200 n'est pas amorcée |
| Exécution | à l'**ouverture de la barre suivante** (`signal.shift(1)` du moteur — convention du projet, pas de lookahead) |
| Frais — mesure **primaire** | **0,40 % par jambe** (`config.FEE_MAKER`, ordres limite), + slippage `config.SLIPPAGE` = 5 bps/côté |
| Frais — mesure **de continuité** | 0,80 % par jambe (`config.FEE_TAKER`) + 5 bps — le régime des études #5 et #8, publié en parallèle pour que les chiffres restent comparables |
| Risque | aucun stop / take-profit / trailing / sizing (défauts `config`) — on juge le SIGNAL |
| Comparateur n°1 (« ne rien faire ») | buy & hold net de frais, **mêmes fenêtres, même moteur** |
| Comparateur n°2 | TSMOM 365 j, paramètres figés (validé étude #5), mêmes fenêtres |
| Optimisation | **aucune**. Période 200 figée, `n_trials = 1`. Aucune grille, aucun réglage après résultat |

### 0.4 Les 4 tranches — définition gelée, sans ambiguïté

Protocole §4.4 point 5 : quatre sous-portefeuilles de 25 %, décidant respectivement en
semaine 1, 2, 3 et 4 du mois. Définition opérationnelle **gelée ici** :

> Soit `M` l'ensemble des **derniers jours de chaque mois calendaire** présents dans la série.
> La tranche `k` (k parmi 0, 7, 14, 21) décide aux dates `d + k jours`, pour chaque `d` de `M`
> (repli sur la dernière barre disponible inférieure ou égale à cette date).
> — `k = 0` : décision en fin de mois (la cadence canonique de Faber) ;
> — `k = 7 / 14 / 21` : décision ~le 7 / le 14 / le 21 du mois suivant.
> Les quatre tranches couvrent donc les quatre semaines du mois, chacune à cadence
> strictement mensuelle (une décision tous les ~30 jours).

Le résultat publié pour « SMA 200 mensuel » est la **moyenne arithmétique des 4 tranches**
(portefeuille 4 x 25 %). Les 4 valeurs individuelles et leur **dispersion** (max - min) sont
publiées systématiquement à côté. **Aucune tranche n'est choisie, ni écartée, après coup.**

### 0.5 Le critère de PROTECTION — le verdict principal

Référence gelée (étude #5 §2, mesurée) : sur BTC, TSMOM 365 fait **-53,1 %** de drawdown max
contre **-76,6 %** pour le buy & hold, soit **-23,5 points** de drawdown évité.

- **P1 — ampleur** : réduction du drawdown max OOS sur BTC >= **15,0 points** par rapport au
  buy & hold, **sur la moyenne des 4 tranches**.
  *Justification du 15 :* c'est **~2/3 de la référence TSMOM mesurée (23,5 pts)**. On n'exige
  pas de faire mieux que TSMOM (ce serait un seuil dérivé du résultat qu'on espère), mais on
  exige d'être du même ordre de grandeur. En dessous, la « protection » n'est plus
  distinguable de l'effet mécanique d'être hors marché une partie du temps.
- **P2 — robustesse au calendrier** : le critère P1 doit être vérifié sur **au moins 3 des 4
  tranches** prises individuellement.
- **P3 — la protection doit dépasser le bruit de calendrier** : la réduction de drawdown
  (moyenne des tranches) doit être **strictement supérieure à la dispersion inter-tranches du
  drawdown** (max - min sur les 4 tranches). Si changer le jour de décision déplace le
  drawdown plus que la stratégie ne le réduit, ce qu'on mesure est un calendrier, pas une
  protection (étude #9 §4.2 point 2).
- **P4 — le modèle doit décider** : au moins **4 ordres** au total sur les 4 fenêtres OOS,
  en moyenne des tranches. En dessous, il n'y a pas de stratégie à juger.

### 0.6 Le critère de COÛT — la prime acceptable

La protection se paie en rendement manqué. Prime **maximale acceptable**, gelée :

- **C1** : rendement cumulé OOS net sur BTC **>= 0 %** (moyenne des 4 tranches). Un outil de
  protection qui **détruit** du capital sur la période où il protège n'est pas une assurance,
  c'est une perte.
- **C2** : rendement cumulé OOS net sur BTC **>= (buy & hold - 20 points)** (moyenne des 4
  tranches). Sur un span OOS de ~3,6 ans, 20 points cumulés font ~**5,3 points par an** de
  prime d'assurance — l'ordre de grandeur au-delà duquel on paie la protection plus cher que
  ce qu'un krach coûte en espérance.

### 0.7 Ce qui compte comme quoi — sans ambiguïté

| Verdict | Condition exacte |
|---|---|
| **PROTÈGE** | P1 **et** P2 **et** P3 **et** P4 **et** C1 **et** C2, tous les six |
| **NE PROTÈGE PAS** | au moins un de : réduction de drawdown moyenne **< 8,0 points** ; **P3 violé** (dispersion >= réduction) ; **C1 violé** (rendement net moyen < 0) ; test de non-lookahead en échec (auquel cas toute l'étude est nulle et non avenue) |
| **INDÉTERMINÉ** | tout le reste (typiquement : réduction entre 8 et 15 points, dispersion maîtrisée, coût tenu) |

**INDÉTERMINÉ est traité comme un échec pour toute décision d'usage** (doctrine étude #8
§0.5) : on ne confie pas de capital à une piste indécise. La phrase écrite dans le verdict
sera alors « ça ne se distingue pas assez de ne rien faire », **jamais** « prometteur, à
affiner ».

### 0.8 Ce que cette étude ne fera pas

- pas de `--final`, pas de `--use-holdout` : le holdout est une **cartouche unique** et sa
  consommation est une décision explicite de Mandar (étude #5 §7 point 6) ;
- pas d'autre période que 200, pas d'autre cadence que mensuelle, pas de stop/take-profit
  « pour rattraper » ;
- aucun ajout ni modification dans `trading/` : la stratégie mensuelle est définie **dans le
  script d'étude**, pas dans le registre `STRATEGIES` (un autre chantier est en cours sur ces
  fichiers) ;
- aucun serveur, aucune fenêtre, aucun navigateur : ligne de commande et fichiers seulement.

### 0.9 Vérification croisée obligatoire (L2)

Le harness doit reproduire les chiffres TSMOM 365 des études #5 / #8 — **BTC +55,9 %,
ETH +98,2 %, SOL +264,6 %** (frais 0,80 % + 5 bps) — à **0,0 point** près, et coïncider avec
`trading.optimizer.walk_forward` sur les mêmes réglages. **Si l'écart n'est pas nul, aucun
chiffre de cette étude ne vaut** et le verdict n'est pas prononcé.

---

## 1. Le protocole gelé, recopié (étude #9 §4.4, non modifié)

> 1. **Un seul actif : BTC.** Pas de panier, pas de moyenne sur plusieurs actifs — sinon on
>    mélange l'effet du signal et l'effet de la diversification.
> 2. **Signal : SMA 200 jours, évaluée au dernier jour de chaque mois.** Cadence mensuelle
>    stricte — c'est le point du dossier qui n'a jamais été testé, ne pas dériver vers du
>    journalier.
> 3. **Exécution à l'ouverture de la barre suivante** (convention du projet : décision à la
>    clôture de t, exécution à l'ouverture de t+1, pas de lookahead).
> 4. **Frais : 0,40 % par jambe** (grille réelle maker vérifiée — le code `config.py` fait foi,
>    jamais un taux cité dans la doc).
> 5. **ÉTALEMENT DU JOUR DE DÉCISION SUR 4 TRANCHES HEBDOMADAIRES.** Quatre sous-portefeuilles
>    de 25 % chacun, décidant respectivement la semaine 1, 2, 3 et 4 du mois, puis moyenne des
>    quatre. **Sans cet étalement, jusqu'à 220 bps de CAGR sont du pur bruit de calendrier et
>    le résultat ne veut rien dire** (§4.2 point 2). C'est la condition la plus facile à
>    oublier et la plus fatale.
> 6. **Comparateur unique : buy & hold sur le même actif, même période, frais inclus à
>    l'entrée.** Aucun autre comparateur. Pas de comparaison à une version optimisée de soi-même.
> 7. **Correction d'exposition** : reporter l'exposition moyenne du modèle (% du temps investi)
>    à côté du résultat, faute de quoi la comparaison au buy & hold à 100 % est biaisée
>    (§4.2 point 3).
> 8. **Critères de succès gelés AVANT de lancer**, écrits dans le dépôt, sur la vraie cible :
>    battre le buy & hold **net de frais** sur la période de test hors-échantillon. Un drawdown
>    réduit sans rendement supérieur est un **échec** au regard de la question posée — c'est
>    déjà mesuré trois fois dans ce dépôt.
> 9. **Historique le plus long disponible** (>= 8 ans), split train/test déclaré d'avance.

**Écart assumé, déclaré ici : le point 6.** Le protocole n'autorise qu'un seul comparateur
(buy & hold). TSMOM 365 est **quand même** publié, parce que le §0.5 de cette étude ancre son
seuil de protection sur les chiffres mesurés de TSMOM : un seuil dont on cacherait la
référence ne serait pas vérifiable (V3). TSMOM n'entre dans **aucun** critère de décision ;
il sert de repère chiffré, jamais de barre à franchir.
Le point 8 est traité au §0.1 (deux axes, deux verdicts séparés, la consigne qui arbitre est
nommée). Tous les autres points sont appliqués tels quels.

---

## 2. Ce qui a été construit, et la preuve que le harness est bon

- `scripts/etude10_sma200_mensuel.py` — le juge. La stratégie mensuelle y est définie
  **localement** (`MonthlySMA`) et **n'est pas enregistrée** dans `trading/strategies.py` :
  aucun fichier de `trading/` n'a été touché.
- `tests/test_etude10_sma200_mensuel.py` — **20 tests**, sans réseau ni clés.

### 2.1 Vérification croisée — MESURÉE, pas supposée

| Grandeur publiée ailleurs | Valeur publiée | Valeur du harness | Écart |
|---|---:|---:|---:|
| TSMOM 365 OOS, BTC (étude #5 §2, étude #8 §2.1) | +55,9 % | **+55,9 %** | 0,02 pt (arrondi de la publication) |
| TSMOM 365 OOS, ETH | +98,2 % | **+98,2 %** | 0,03 pt |
| TSMOM 365 OOS, SOL | +264,6 % | **+264,6 %** | 0,00 pt |
| `optimizer.walk_forward` sur les 3 actifs | — | identique | **0,0000 pt** |
| Buy & hold OOS net, BTC / ETH / SOL (étude #8) | +4,9 / +27,3 / +1 288,1 % | **+4,9 / +27,3 / +1 288,1 %** | 0,0 pt |
| Drawdown max B&H, BTC / ETH / SOL (étude #5) | −76,6 / −79,3 / −59,8 % | **−76,6 / −79,3 / −59,8 %** | 0,0 pt |
| Drawdown max TSMOM 365, BTC / ETH / SOL (étude #5) | −53,1 / −57,2 / −52,9 % | **−53,1 / −57,2 / −52,9 %** | 0,0 pt |

**12 chiffres publiés indépendamment sont reproduits.** Le harness ne réinvente ni le moteur,
ni le découpage des fenêtres (un test le prouve en comparant les bornes de fenêtre à celles
que renvoie `optimizer.walk_forward`).

### 2.2 Convention de mesure (identique à l'étude #5)

- **Rendement** = composé par fenêtre (le chiffre officiel du projet, celui de `walk_forward`).
- **Drawdown et Sharpe** = courbe OOS **continue** sur l'union des fenêtres — un drawdown réel
  traverse une frontière de fenêtre. C'est la convention dont sortent les chiffres de
  référence gelés au §0.5 (−53,1 % / −76,6 %). Le « pire drawdown par fenêtre » (convention
  d'affichage de l'étude #8) est publié à part au §3.2.

### 2.3 Un défaut trouvé par les tests, et corrigé avant publication

La première version de `month_end_positions` prenait le maximum par (année, mois) : la
dernière barre d'un mois **incomplet** (fin de série, fin de tranche de walk-forward) passait
pour une fin de mois, produisant deux décisions à 4 jours d'écart. Deux tests de cadence l'ont
attrapé. Correctif : un mois n'est clos que lorsqu'une barre du mois **suivant** existe.
**Effet mesuré sur les résultats : nul** — cette barre étant la dernière de sa tranche, le
décalage d'exécution `shift(1)` ne l'exécutait jamais. L'étude a été rejouée avant et après :
**toutes les valeurs des tableaux §3.1 à §3.4 sont identiques au dixième de point** (comparaison
ligne à ligne des deux sorties). Deux exécutions consécutives après correctif donnent en outre
un `diff` **vide** — le script est déterministe, un test le vérifie aussi.

---

## 3. Résultats hors-échantillon

Fenêtres OOS BTC/ETH : 2021-03-11 → 2024-10-02 (4 fenêtres de ~325 bougies, ~3,56 ans),
segment de recherche 2017-08-17 → 2024-10-02 (2 604 bougies).
SOL : 2022-12-25 → 2025-05-08, recherche depuis 2020-08-11 (1 732 bougies).
**Le holdout n'a jamais été chargé** (BTC/ETH < 2024-10-03, SOL < 2025-05-09).

### 3.1 BTC/USD — l'actif du verdict, frais maker 0,40 %/jambe (mesure PRIMAIRE)

| Contendant | Net OOS | Brut OOS | Frais (pts) | Sharpe | DD max | Exposition | Ordres | Fen. + |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Ne rien faire (B&H)** | **+6,6 %** | +8,6 % | 1,9 | 0,32 | **−76,6 %** | 100 % | 4 | 50 % |
| *TSMOM 365 (repère, hors critère)* | *+60,4 %* | *+65,5 %* | *5,1* | *0,50* | *−53,1 %* | *62 %* | *5* | *75 %* |
| SMA 200 mensuel **+0 j** | −15,0 % | −10,6 % | 4,3 | 0,09 | −65,1 % | 53 % | 6 | 50 % |
| SMA 200 mensuel **+7 j** | −8,8 % | −5,0 % | 3,8 | 0,13 | −60,1 % | 51 % | 5 | 50 % |
| SMA 200 mensuel **+14 j** | +33,8 % | +38,7 % | 4,9 | 0,39 | −47,5 % | 59 % | 4 | 50 % |
| SMA 200 mensuel **+21 j** | −27,2 % | −23,5 % | 3,7 | −0,02 | −75,3 % | 55 % | 6 | 50 % |
| **SMA 200 mensuel — MOYENNE 4 tranches** | **−4,3 %** | −0,1 % | 4,2 | 0,15 | **−62,0 %** | 54 % | 5,2 | 50 % |
| **DISPERSION (max − min)** | **61,0 pts** | 62,2 pts | 1,2 | 0,41 | **27,8 pts** | 8 pts | 2 | 0 |

### 3.2 BTC/USD — frais taker 0,80 %/jambe (continuité avec les études #5 et #8)

| Contendant | Net OOS | Sharpe | DD max | Ordres |
|---|---:|---:|---:|---:|
| **Ne rien faire (B&H)** | **+4,9 %** | 0,32 | **−76,6 %** | 4 |
| *TSMOM 365 (repère)* | *+55,9 %* | *0,49* | *−53,1 %* | *5* |
| SMA 200 mensuel +0 j | −18,7 % | 0,06 | −66,0 % | 6 |
| SMA 200 mensuel +7 j | −12,0 % | 0,11 | −60,8 % | 5 |
| SMA 200 mensuel +14 j | +29,5 % | 0,37 | −47,5 % | 4 |
| SMA 200 mensuel +21 j | −30,4 % | −0,04 | −75,9 % | 6 |
| **MOYENNE 4 tranches** | **−7,9 %** | 0,13 | **−62,5 %** | 5,2 |
| **DISPERSION** | **59,9 pts** | 0,41 | **28,4 pts** | 2 |

**Doubler les frais coûte 3,6 points de rendement cumulé sur 3,56 ans.** Le régime de frais ne
change ni le classement, ni le verdict : le passage en maker ne sauve rien.

### 3.3 Décomposition fenêtre par fenêtre (BTC, maker) — d'où vient tout

| Fenêtre | Période | B&H | TSMOM 365 | +0 j | +7 j | +14 j | +21 j | **Moy. 4 tr.** | **Dispersion** |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2021-03-11 → 2022-01-29 (sommet + début de baisse) | −32,0 % | −32,0 % | −54,5 % | −47,7 % | −34,8 % | −68,3 % | **−51,3 %** | **33,4 pts** |
| 2 | 2022-01-30 → 2022-12-20 (**le krach**) | **−55,9 %** | +1,7 % | **+0,0 %** | +0,0 % | +0,0 % | +0,0 % | **+0,0 %** | 0,0 pt |
| 3 | 2022-12-21 → 2023-11-10 (reprise) | +119,8 % | +43,2 % | +19,2 % | +17,4 % | +25,4 % | +41,1 % | **+25,8 %** | 23,7 pts |
| 4 | 2023-11-11 → 2024-10-02 | +61,9 % | +61,9 % | +56,7 % | +48,4 % | +63,6 % | +62,5 % | **+57,8 %** | 15,2 pts |

Ce tableau **est** le résultat, en trois lignes :

1. **Fenêtre 2 : la protection fonctionne, et elle est totale.** Le modèle est en cash pendant
   tout le krach 2022 : **+0,0 % contre −55,9 %**, sur les 4 tranches sans exception
   (dispersion nulle). Ce n'est pas contesté.
2. **Fenêtre 1 : la protection est détruite avant même le krach.** Sur le retournement de
   2021, le modèle perd **−51,3 % en moyenne quand ne rien faire perd −32,0 %** : il entre et
   sort à contretemps (whipsaw) autour d'une moyenne 200 jours traversée plusieurs fois. Et le
   jour de décision décide de tout : **de −34,8 % à −68,3 % selon la tranche, 33,4 points
   d'écart pour la même stratégie sur la même période.**
3. **Fenêtre 3 : il rend le rebond.** +25,8 % contre +119,8 % — il rentre après, comme tout
   suiveur de tendance (déjà mesuré étude #5 §3).

Le drawdown maximal du modèle (−62,0 %) **n'est pas fait dans le krach de 2022** : il est fait
dans le retournement de 2021, là où le signal mensuel est le plus lent. C'est exactement la
raison pour laquelle il ne protège pas.

**Pire drawdown par fenêtre** (convention d'affichage de l'étude #8, pour comparaison) :
B&H −66,7 %, TSMOM −53,1 %, tranches −59,8 / −54,5 / −47,5 / −72,0 %.

### 3.4 Robustesse — ETH et SOL, HORS VERDICT (protocole point 1)

Publiés parce qu'ils ont été mesurés, jamais pour amender le verdict BTC.

| Actif (maker) | SMA 200-M moy. | B&H | DD SMA 200-M | DD B&H | DD évité | Dispersion DD | Dispersion rendement |
|---|---:|---:|---:|---:|---:|---:|---:|
| ETH/USD | +86,2 % | +29,3 % | −60,4 % | −79,3 % | **+18,9 pts** | 10,0 pts | 145,6 pts |
| SOL/USD | +194,6 % | +1 310,7 % | −52,0 % | −59,8 % | **+7,8 pts** | 20,6 pts | 149,5 pts |

Tranches ETH : +107,5 / +164,7 / +53,2 / +19,1 % — tranches SOL : +268,7 / +205,8 / +119,2 /
+184,7 %. Au régime taker les conclusions sont identiques (ETH +80,5 %, DD −60,6 % ;
SOL +182,8 %, DD −52,6 %).

---

## 4. Verdict — confrontation aux critères gelés du §0

### 4.1 Axe PROTECTION (le verdict principal, consigne `CLAUDE.md` §Le cap point 2)

| Critère gelé (§0.5 / §0.6) | Mesure BTC maker | Mesure BTC taker | Statut |
|---|---|---|---|
| **P1** réduction de DD moyenne >= 15,0 pts | **+14,6 pts** | +14,1 pts | **ÉCHEC** |
| **P2** P1 tenu sur >= 3 tranches / 4 | +11,5 / +16,5 / +29,1 / **+1,3** → 2 sur 4 | 2 sur 4 | **ÉCHEC** |
| **P3** réduction > dispersion inter-tranches | **14,6 contre 27,8 pts** | 14,1 contre 28,4 | **ÉCHEC** |
| **P4** >= 4 ordres OOS | 5,2 ordres | 5,2 | OK |
| **C1** rendement net moyen >= 0 % | **−4,3 %** | −7,9 % | **ÉCHEC** |
| **C2** rendement net >= B&H − 20 pts | −4,3 % contre −13,4 | −7,9 contre −15,1 | OK |

> ### VERDICT : **NE PROTÈGE PAS.**

Deux déclencheurs **indépendants** de la table §0.7 sont allumés, dans les deux régimes de
frais : **P3 violé** (la dispersion de calendrier, 27,8 points de drawdown, est **presque le
double** de la protection apportée, 14,6 points) et **C1 violé** (le modèle perd de l'argent :
−4,3 %).

**Le verdict ne dépend pas du seuil de 15 points.** Même en abaissant P1 à 8 points, P3 et C1
restent violés. Le seuil n'a servi qu'à écrire à l'avance ce qu'on accepterait ; ce n'est pas
lui qui tranche.

**Ce que dit P3, en une phrase** : *choisir de décider le 14 du mois plutôt que le 21 change le
drawdown de 27,8 points ; la stratégie, elle, n'en économise que 14,6. On mesure un calendrier,
pas une protection.* C'est très exactement le risque annoncé — et chiffré à 220 bps — par
l'étude #9 §4.2 point 2 avant toute mesure.

### 4.2 Axe RENDEMENT (critère du protocole gelé, étude #9 §4.4 point 8)

> ### VERDICT : **ÉCHEC, net de frais, dans les deux régimes.**

−4,3 % contre +6,6 % pour le buy & hold en maker ; −7,9 % contre +4,9 % en taker.
**Application de M22** : « sans » la transformation (+6,6 %) est supérieur à « avec » (−4,3 %).
La règle dit de **retirer** la transformation, pas de la régler.
Une seule tranche sur quatre bat le buy & hold (+14 j, +33,8 %) — et rien ne permettait de la
choisir à l'avance. La choisir après coup serait le data-mining que l'étalement en 4 tranches
existe précisément pour rendre visible.

### 4.3 La phrase qui compte pour le projet

**Ce test clôt le dossier de recherche.** Il ne laisse pas de question ouverte sur BTC : la
méthode qui manquait au dossier a été testée selon son propre protocole, et elle échoue sur
les deux axes à la fois — elle ne protège pas et elle coûte. Le point 2 du cap est **exécuté**.

Nuance à ne pas perdre, parce qu'elle est mesurée : **le mécanisme de protection existe** —
en fenêtre 2, le modèle est resté intégralement en cash pendant le krach 2022 (+0,0 % contre
−55,9 %), sur les 4 tranches. Ce qui échoue n'est pas l'idée de sortir en tendance baissière,
c'est **la cadence mensuelle** : trop lente pour le retournement, et si dépendante du jour du
mois que la protection nette disparaît dans le bruit de calendrier. Le point 3 du cap
(détecteur de régime **journalier**, vote de plusieurs horizons pour ne dépendre d'aucun) n'est
pas invalidé par ce résultat — il est **renforcé** : ce test montre que la fragilité à un
paramètre unique (ici le jour du mois) est le vrai ennemi, et le vote multi-horizons est
exactement la réponse à cette fragilité.

---

## 5. Ce qui n'est PAS établi (à relire avant toute décision)

1. **ETH aurait passé les critères, BTC non.** Sur ETH : DD évité +18,9 pts, dispersion
   10,0 pts, rendement +86,2 % contre +29,3 % — les six critères gelés sont satisfaits.
   Sur SOL : +7,8 pts de DD évité, dispersion 20,6 pts, rendement écrasé (+194,6 % contre
   +1 310,7 %) — échec net. **Le résultat tient donc 1 actif sur 3**, et l'actif qui passe
   n'est pas celui du protocole. Ce n'est **pas** une raison d'amender le verdict (BTC a été
   gelé comme seul juge avant mesure, protocole point 1) : c'est le **même motif d'instabilité
   par actif** que l'étude #5 §7.2 documentait déjà. Un résultat qui change de signe selon
   l'actif n'est pas un edge, c'est un échantillon.
2. **Une seule fenêtre porte tout, et c'est la fenêtre 1.** Le verdict sur BTC se joue sur
   ~11 mois (le retournement 2021). Un placement de fenêtre différent donnerait un autre
   chiffre — caveat n°1 de l'étude #5, inchangé.
3. **Un cycle et demi, un seul krach majeur** (2022) dans l'échantillon BTC. « Protège pendant
   un krach » n'est mesuré que sur **un** krach.
4. **Exposition non égalisée.** Le modèle est investi 54 % du temps contre 100 % pour le buy &
   hold (protocole point 7). Aucune correction d'exposition n'a été appliquée : à exposition
   égalisée le rendement du modèle remonterait mécaniquement, mais son drawdown aussi. Ce
   travail n'a **pas** été fait ici.
5. **USDT vs USD.** Recherche sur Binance USDT, exécution réelle sur Kraken USD (caveat
   permanent du dépôt).
6. **Le holdout reste vierge.** Aucun `--final`, aucun `--use-holdout`. Ce rapport n'est pas le
   dernier juge : les 20 % réservés (BTC/ETH depuis 2024-10-03, SOL depuis 2025-05-09) sont une
   cartouche unique, dont l'usage est une décision explicite de Mandar (étude #5 §7 point 6).
7. **La littérature reste muette.** L'étude #9 §4.3 avait constaté qu'aucune publication
   sérieuse ne testait BTC + SMA 200 j mensuel hors échantillon. Ce document est, à notre
   connaissance, le seul résultat protocolé sur la question — avec un échantillon d'un cycle
   et demi, ce qui limite sa portée à ce dépôt.

---

## 6. Ce qui a bougé après coup

- **§0 : rien.** Aucun critère, aucun seuil, aucune définition de tranche n'a été modifié après
  la première mesure. Les seuils (15 / 8 / 20 pts, 4 ordres) et la définition des 4 tranches
  ont été écrits avant le premier lancement du script.
- **Code** : un défaut de cadence corrigé (§2.3), trouvé par les tests, sans effet sur les
  chiffres (étude rejouée avant/après, résultats identiques).
- **Écart au protocole déclaré** : la publication de TSMOM 365 comme repère chiffré malgré le
  point 6 (« comparateur unique »), justifiée au §1. TSMOM n'entre dans aucun critère.

