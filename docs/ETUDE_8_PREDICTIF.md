# Étude #8 — Une stratégie PRÉDICTIVE apporte-t-elle quelque chose ?

> Sujet : `MODE_ADAPTATIF_SPEC.md` §2b (« la moitié prédictive — le piège classique ») et
> §3 étage 3 (« la petite IA »). Cette étude ne réécrit pas cette analyse : **elle la teste**.
> Juge : le walk-forward hors-échantillon, jamais le backtest (garde-fou n°1 de `CLAUDE.md`).
> Le **holdout sacré reste vierge** : aucun `--final`, aucun `--use-holdout`.

---

## 0. Critères gelés — écrits AVANT toute mesure

**Horodatage de gel : 2026-09-02, avant le premier entraînement.**
Aucun modèle n'a été entraîné, aucun walk-forward lancé, aucun chiffre de cette étude
n'existait quand cette section a été écrite. Preuve de l'ordre des opérations : cette
section est le premier contenu écrit du fichier ; toute modification ultérieure est
signalée explicitement en §6 (« Ce qui a bougé après coup »).

### 0.1 La cible (M2)

La cible est le **rendement NET DE FRAIS hors-échantillon**, comparé à **ne rien faire**
(buy & hold, lui aussi net de frais, sur exactement les mêmes fenêtres).
Ne sont **pas** des cibles et ne seront jamais invoqués comme succès : le taux de bonnes
classifications, l'AUC, la log-vraisemblance, le rendement brut, le backtest in-sample.

### 0.2 Le protocole, chiffré

| Élément | Valeur gelée |
|---|---|
| Source de données | `binance` daily (`1d`), historique long depuis le listing |
| Actifs | BTC, ETH, SOL (3 actifs — un edge doit tenir sur la majorité) |
| Segment utilisable | uniquement les bougies **antérieures à la frontière de holdout gelée** (`config.HOLDOUT_REFERENCES` → `holdout_start`) : BTC/ETH < 2024-10-03, SOL < 2025-05-09 |
| Fenêtres walk-forward | **4**, `train_frac = 0.5` (première moitié = amorçage, 4 fenêtres OOS enchaînées sur la seconde moitié ; la dernière absorbe le reste) |
| Frais | `config.FEE_TAKER = 0,80 %` par côté (aller-retour 1,62 %) + slippage 5 bps/côté |
| Risque | aucun stop / take-profit / trailing / sizing (défauts `config`) — on juge le SIGNAL, pas l'habillage |
| Comparateur n°1 (« ne rien faire ») | buy & hold **net de frais**, mêmes fenêtres, même moteur |
| Comparateur n°2 | TSMOM 365 (paramètres figés, validé étude #5), mêmes fenêtres |
| Réentraînement | glissant, expanding window, **uniquement sur le passé de la fenêtre** |

### 0.3 Budget de configurations — déclaré à l'avance

**Maximum 3 configurations essayées, au total, sur toute l'étude.**
Elles sont nommées ici avant d'avoir vu le moindre résultat :

1. **CONFIG PRIMAIRE** : horizon de classification **H = 5 jours** ;
2. sensibilité : **H = 10 jours** ;
3. sensibilité : **H = 20 jours**.

Tout le reste est figé et ne sera pas touché : 6 caractéristiques (momentum 20/60/180,
ratio de volatilité réalisée 20/100, drawdown depuis le plus haut glissant 180, écart au
SMA 200), régression logistique L2 (lambda = 1,0), 300 itérations de descente de gradient,
pas d'apprentissage 0,5, initialisation à zéro (donc déterministe), standardisation sur le
train seul, seuil de décision **0,50**, réentraînement tous les 30 jours, minimum
300 lignes étiquetées avant la première décision.

**Le verdict est prononcé sur la CONFIG PRIMAIRE.** Les deux autres sont publiées
intégralement (jamais « la meilleure des trois »). Choisir a posteriori la meilleure des
trois serait exactement le sur-apprentissage que cette étude est censée détecter : plus on
essaie de configurations, plus le meilleur résultat est du hasard.
Si une 4e configuration devait être essayée, elle serait écrite en §6 avec sa raison.

### 0.4 Ce qui compte comme RÉUSSITE (les cinq à la fois)

- **S1** — rendement cumulé OOS net du prédictif **> celui du buy & hold net** sur
  **au moins 2 actifs sur 3** ;
- **S2** — rendement cumulé OOS net **> 0 sur les 3 actifs sur 3** ;
- **S3** — moyenne des 3 rendements cumulés OOS nets **>= moyenne du buy & hold + 10 points
  de pourcentage** (marge exigée : sans marge, on célèbre du bruit) ;
- **S4** — Sharpe OOS moyen du prédictif **> celui du buy & hold ET > celui du TSMOM 365** ;
- **S5** — au moins **5 trades** sur au moins **3 fenêtres sur 4**, et ce par actif (en
  dessous, le résultat est un accident statistique, pas une stratégie).

### 0.5 Ce qui compte comme ÉCHEC (un seul suffit)

- **E1** — rendement cumulé OOS net **<= 0 sur 2 actifs ou plus** ;
- **E2** — prédictif **< buy & hold** sur **2 actifs ou plus** ;
- **E3** — moyenne des rendements cumulés OOS nets du prédictif **< moyenne du buy & hold** ;
- **E4** — le test de non-lookahead échoue (le signal voit le futur) : tout résultat est nul
  et non avenu ;
- **E5** — moins de 5 trades sur au moins 2 fenêtres par actif (le modèle ne décide rien).

**Zone entre les deux** (ni tous les S, ni aucun E) = **INDÉCIS**, traité comme un échec
pour la décision d'usage : on ne trade pas une piste indécise. La phrase écrite dans le
verdict est alors « ça n'apporte rien de démontrable », pas « prometteur, à affiner ».

### 0.6 Ce que cette étude ne fera pas

- pas de `--final`, pas de `--use-holdout` : le holdout ne se reconstitue pas et sa
  consommation est une décision explicite du propriétaire (étude #5 §7.6) ;
- pas de réglage de seuil, de caractéristiques ou d'hyperparamètres après avoir vu un
  résultat ;
- pas d'ajout de stop/take-profit « pour rattraper » un modèle qui perd.

---

## 1. Ce qui a été construit

- `trading/predictive.py` — `LogisticRegimeStrategy`, enregistrée dans `STRATEGIES`
  sous la clé `predictive` (donc `build_strategy("predictive")`, CLI, walk-forward et
  pages web y ont accès comme à n'importe quelle autre stratégie).
  Classification d'**état** (investi / hors marché), pas prédiction de prix.
  Régression logistique L2 en **numpy pur** — `sklearn` n'est pas dans
  `requirements.txt` et cette étude ne justifiait pas d'ajouter une dépendance ;
  poids initialisés à zéro, nombre d'itérations fixe : **aucun aléatoire**, donc
  déterminisme sans graine.
- `trading/optimizer.py` — `_declared_warmup()` : le walk-forward accorde désormais à
  une stratégie la marge d'amorçage qu'elle **déclare** (`warmup_bars`), au lieu de la
  déduire de ses seuls paramètres entiers. Sans cela, une stratégie qui apprend passait
  la moitié de chaque fenêtre hors-échantillon à l'arrêt — handicap artificiel qui
  n'existe pas en réel. **Neutre pour l'existant** : toute stratégie sans `warmup_bars`
  renvoie 0, les résultats des études #4/#5/#7 sont inchangés (test dédié).
- `scripts/etude8_predictif.py` — le juge : chargement Binance, troncature à la
  frontière de holdout gelée, walk-forward à paramètres figés, comparateurs sur les
  **mêmes fenêtres**, double mesure avec et sans frais.
- `tests/test_predictive.py` — 17 tests, sans réseau ni clés.

### 1.1 Le holdout n'a pas été touché

Le protocole ne s'appuie pas sur `--holdout 20` calculé sur l'historique **du jour** :
l'historique a grandi depuis l'étude #5 (3 303 bougies BTC/ETH contre 3 255 de
référence), et une coupe à 20 % du fichier actuel serait tombée à ~2024-11-09, soit
**38 bougies à l'intérieur de la zone réservée**. Le script coupe donc à la frontière
**gelée** (`optimizer.holdout_start`) : BTC/ETH < 2024-10-03, SOL < 2025-05-09.
Aucun `--final`, aucun `--use-holdout`, `holdout_usage.log` inchangé.

### 1.2 Le test anti-lookahead, et la preuve qu'il sait mordre

Deux contrôles complémentaires :

1. **Causalité** — on réécrit les données *après* la bougie k (futur multiplié par 4,
   ou divisé par 4) : tous les signaux jusqu'à k doivent être **identiques**. Toute
   fuite, même indirecte (étiquette, standardisation calculée sur tout l'échantillon),
   casse ce test.
2. **Oracle** — sur une série dont les signes de rendement sont **tirés au sort**, une
   stratégie qui triche (`close[t+1]`) fait fortune : le test le vérifie d'abord sur
   une tricheuse fabriquée exprès (+500 % exigé), puis exige que la vraie stratégie
   reste au niveau du hasard.

> Piège rencontré et corrigé pendant l'écriture des tests : la première version de
> l'oracle utilisait une série **alternée** +5 % / −5 %. La stratégie y gagnait ×1 800…
> **sans tricher** : la parité est parfaitement encodée dans les caractéristiques.
> Un « ça gagne énormément » n'y prouvait donc rien. Série remplacée par un tirage au
> sort, où le passé n'informe réellement pas.

---

## 2. Résultats hors-échantillon — le tableau qui décide

Walk-forward 4 fenêtres, paramètres **figés** (aucune optimisation de grille, donc
`n_trials = 1`), frais taker 0,80 %/côté + slippage 5 bps/côté.
Fenêtres OOS **identiques** pour les trois contendants.

- BTC/ETH : 2021-03-11 → 2024-10-02 (4 × ~325 bougies), recherche 2017-08-17 → 2024-10-02.
- SOL : 2022-12-25 → 2025-05-08 (4 × ~216 bougies), recherche depuis 2020-08-11.

Vérification croisée : les chiffres du script et ceux de
`trading.optimizer.walk_forward` (mêmes réglages) coïncident à **0,0000 point** près
sur les 6 couples actif x stratégie testés — le script n'a pas son propre moteur.

### 2.1 BTC/USD

| Contendant | Net OOS | Brut OOS | Frais (pts) | Sharpe moy. | DD max | Ordres | Fen. + |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Ne rien faire (B&H)** | **+4,9 %** | +8,6 % | 3,6 | 0,57 | −66,7 % | 4 | 50 % |
| TSMOM 365 | +55,9 % | +65,5 % | 9,6 | 0,76 | −53,1 % | 5 | 75 % |
| **Prédictif H=5 j (primaire)** | **−62,2 %** | −43,1 % | 19,1 | −0,09 | −61,0 % | 25 | 50 % |
| Prédictif H=10 j | −71,1 % | −47,4 % | 23,6 | −0,27 | −59,6 % | 36 | 50 % |
| Prédictif H=20 j | −53,4 % | −22,9 % | 30,5 | 0,07 | −61,8 % | 31 | 50 % |

### 2.2 ETH/USD

| Contendant | Net OOS | Brut OOS | Frais (pts) | Sharpe moy. | DD max | Ordres | Fen. + |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Ne rien faire (B&H)** | **+27,3 %** | +31,7 % | 4,4 | 0,62 | −71,7 % | 4 | 75 % |
| TSMOM 365 | +98,2 % | +125,2 % | 27,1 | 0,65 | −57,2 % | 9 | 100 % |
| **Prédictif H=5 j (primaire)** | **−38,9 %** | +10,1 % | 49,0 | −0,08 | −63,7 % | 36 | 50 % |
| Prédictif H=10 j | −52,2 % | −27,3 % | 24,8 | −0,37 | −57,2 % | 26 | 25 % |
| Prédictif H=20 j | −48,4 % | −13,8 % | 34,5 | −0,36 | −57,2 % | 31 | 25 % |

### 2.3 SOL/USD

| Contendant | Net OOS | Brut OOS | Frais (pts) | Sharpe moy. | DD max | Ordres | Fen. + |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Ne rien faire (B&H)** | **+1 288,1 %** | +1 336,3 % | 48,2 | 1,64 | −59,8 % | 4 | 100 % |
| TSMOM 365 | +264,6 % | +303,9 % | 39,3 | 1,29 | −52,9 % | 7 | 50 % |
| **Prédictif H=5 j (primaire)** | **+205,8 %** | +312,2 % | 106,4 | 0,86 | −51,4 % | 19 | 75 % |
| Prédictif H=10 j | +255,5 % | +336,3 % | 80,8 | 1,17 | −41,0 % | 13 | 100 % |
| Prédictif H=20 j | +268,0 % | +383,5 % | 115,5 | 1,22 | −39,8 % | 17 | 100 % |

### 2.4 Synthèse (moyenne des 3 actifs)

| Contendant | Net OOS moyen | Actifs positifs | Sharpe moyen |
|---|---:|---:|---:|
| **Ne rien faire (B&H)** | **+440,1 %** | 3/3 | 0,94 |
| TSMOM 365 | +139,6 % | 3/3 | 0,90 |
| **Prédictif H=5 j (primaire)** | **+34,9 %** | 1/3 | 0,23 |
| Prédictif H=10 j | +44,1 % | 1/3 | 0,18 |
| Prédictif H=20 j | +55,4 % | 1/3 | 0,31 |

---

## 3. Verdict — confrontation aux critères gelés du §0

**Configuration primaire (H = 5 j), critères d'échec :**

| Critère gelé | Mesure | Statut |
|---|---|---|
| **E1** — net OOS <= 0 sur >= 2 actifs | BTC −62,2 % et ETH −38,9 % (2/3) | **DÉCLENCHÉ** |
| **E2** — < buy & hold sur >= 2 actifs | 3/3 (−67 pts, −66 pts, −1 082 pts) | **DÉCLENCHÉ** |
| **E3** — moyenne < moyenne du B&H | +34,9 % contre +440,1 % | **DÉCLENCHÉ** |
| **E4** — lookahead détecté | tests verts, causalité respectée | non déclenché |
| **E5** — < 5 ordres sur >= 2 fenêtres | SOL : [3, 6, 4, 6] → 2 fenêtres | **DÉCLENCHÉ** |

Critères de réussite : **S1, S2, S3 et S4 échouent** (0 actif où le prédictif bat le
buy & hold ; 2 actifs sur 3 en perte ; Sharpe moyen 0,23 contre 0,94 pour « ne rien
faire » et 0,90 pour TSMOM 365).

> ### VERDICT : **ça n'apporte rien.** La piste est déclarée MORTE.
>
> Le modèle prédictif est battu par **ne rien faire** sur les 3 actifs sur 3, il est en
> perte sur 2 sur 3, et son Sharpe hors-échantillon vaut un quart de celui du buy &
> hold. Les deux configurations de sensibilité (H = 10, H = 20) échouent exactement de
> la même façon : 1 actif positif sur 3, moyenne très en dessous du comparateur.
> Ce n'est pas « prometteur, à affiner » : c'est le résultat que `MODE_ADAPTATIF_SPEC.md`
> §2b annonçait, désormais **mesuré** au lieu d'être supposé.

**Application de M22 (mesurer la cible SANS la transformation)** : « sans » (+440,1 %)
est supérieur à « avec » (+34,9 %) sur la moyenne, et sur chacun des trois actifs pris
séparément. La règle dit alors de **retirer** la transformation, pas de la régler.
La stratégie reste dans le code comme **objet d'étude documenté** (et pour que le
résultat soit reproductible), elle n'a aucune vocation à toucher du capital.

---

## 4. Pourquoi ça échoue — ce que les chiffres montrent, sans spéculation

1. **Les frais mangent le signal, exactement comme prédit.** Le cas le plus net est
   ETH H=5 : **+10,1 % brut → −38,9 % net**, soit **49 points de frais** pour 36 ordres.
   Le modèle produit 5 à 9 fois plus d'ordres que TSMOM et il n'a pas 5 à 9 fois plus
   d'edge — il n'en a pas du tout de mesurable.
2. **Même brut, il ne bat pas « ne rien faire ».** En supprimant totalement frais et
   slippage, le prédictif reste sous le buy & hold sur les 3 actifs (BTC −43,1 % contre
   +8,6 % ; ETH +10,1 % contre +31,7 % ; SOL +312,2 % contre +1 336,3 %). Le problème
   n'est donc **pas** un problème de coût d'exécution qu'un passage en maker
   (0,40 %/côté) réglerait : le signal lui-même n'a pas d'edge.
3. **Le seul actif positif est celui qui monte le plus.** SOL, +1 288 % en buy & hold :
   y être investi une partie du temps suffit à finir positif. C'est du bêta, pas de
   l'alpha — le même piège que l'étude #5 §7.1 documente déjà.
4. **Non-stationnarité, visible dans la structure des fenêtres** : le prédictif fait
   50 % de fenêtres profitables sur BTC et 25 % sur ETH (H=10/20). Ce qu'il apprend sur
   le passé ne se reproduit pas sur la fenêtre suivante.

Observation à ne pas surinterpréter : sur SOL, le prédictif **réduit** le drawdown
maximal (−51,4 % contre −59,8 % ; −39,8 % en H=20). Ce n'était pas un critère de
réussite gelé, et l'effet n'est pas gratuit : sur les trois actifs, la réduction de
drawdown coûte 67 à 1 082 points de rendement. Rester en cash réduit toujours le
drawdown ; c'est le prix payé qui compte, et il est ici prohibitif.

---

## 5. Honnêteté du protocole — le compte exact

- **Nombre de configurations essayées : 3**, exactement celles déclarées au §0.3
  (H = 5, 10, 20). Aucun réglage de seuil, aucun ajout ou retrait de caractéristique,
  aucun ajustement de `lambda`, `refit`, `min_train` ni `threshold` après avoir vu un
  résultat. Aucune configuration essayée puis jetée en silence.
- **Le verdict porte sur la configuration primaire** (H = 5), désignée avant mesure.
  Les deux autres sont publiées, et elles échouent aussi — ce qui rend le verdict
  robuste au choix de l'horizon.
- **Aucun seuil n'a été dérivé des points testés** : les cinq critères d'échec ont été
  écrits avant le premier entraînement et n'ont pas été modifiés.
- **Le producteur ne signe pas sa propre gate** : ce rapport présente d'abord les
  échecs, agrégat en dernier, et laisse la décision au propriétaire.

---

## 6. Ce qui a bougé après coup

- **Section 0 : rien.** Les critères gelés n'ont pas été modifiés après la première
  mesure.
- Une correction a eu lieu **côté test**, avant toute mesure de performance : la série
  « oracle » alternée a été remplacée par un tirage au sort (cf. §1.2). C'est un
  correctif de test, pas un réglage de modèle ; il ne touche ni les critères, ni les
  configurations, ni les résultats du §2.

---

## 7. Ce qui n'est pas établi (limites, à lire avant toute décision)

1. **Le holdout n'a pas été consommé** : ce rapport n'est pas le juge final, seulement
   le walk-forward de recherche. Un `--final` reste une décision explicite du
   propriétaire — et il n'y a ici aucune raison de la dépenser sur une piste morte.
2. **Un seul type de modèle a été testé** (régression logistique L2, 6 caractéristiques
   de prix). Un gradient boosting peu profond, d'autres caractéristiques (volumes,
   données on-chain, dominance, signaux inter-actifs) ou d'autres cibles
   (« drawdown > X % à horizon N », spec §3 étage 3) n'ont pas été évalués.
   Ce rapport ne dit pas « aucun modèle ne peut marcher » : il dit que **celui-ci, avec
   ce protocole honnête, perd contre ne rien faire**.
3. **Trois actifs, un cycle et demi, majors liquides** — mêmes limites que l'étude #5
   §7.5, biais du survivant compris.
4. **Recherche sur Binance USDT, exécution réelle sur Kraken USD** (étude #5 §7.4).
5. **Sensibilité au placement des fenêtres** : l'étude #5 §7.2 a mesuré qu'une
   variation de ~1 % de l'historique pouvait déplacer fortement les chiffres par actif.
   Les rendements ci-dessus sont des **ordres de grandeur**, pas des estimations
   ponctuelles. L'écart entre le prédictif et le buy & hold est cependant d'une ampleur
   (−67 à −1 082 points) que ce genre de sensibilité n'explique pas.
6. **Aucune mesure de significativité statistique du déficit** n'a été produite (pas
   d'intervalle de confiance sur l'écart prédictif − B&H) : les critères gelés étaient
   des seuils de décision, pas un test d'hypothèse.
