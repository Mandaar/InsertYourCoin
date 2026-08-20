# Mode adaptatif — régime de marché, et la place réelle d'une « petite IA »

> Statut : **SPEC — proposition à valider, rien n'est implémenté.** Écrite le 2026-08-18 sur
> demande de Mandar : « *il faudrait qu'on ait un mode dynamique, quand une période de grosse
> baisse est étudiée autant adapter le trading* » et « *une sorte de petite IA prédictive et
> surtout adaptative* ».
> Doctrine du projet, non négociable : **le walk-forward hors-échantillon est le juge**. Aucun
> backtest in-sample ne vaut preuve. Honnêteté avant tout : si ça n'a pas d'edge, on le dit.

---

## 1. Le fait fondateur — ce n'est pas une intuition, c'est déjà mesuré

`docs/ETUDE_5_TSMOM_VS_BH.md` a mesuré exactement ce que tu décris. Décomposition fenêtre par
fenêtre du TSMOM 365 j sur BTC, hors échantillon :

| Fenêtre | Période | TSMOM | Buy & Hold | Mécanisme |
|---|---|---|---|---|
| 1 | 2021 (sommet + début de baisse) | −32,2 % | −33,9 % | encore long, subit comme le marché |
| 2 | **2022 (bear)** | **+0,1 %** | **−55,4 %** | **en CASH — évite le krach** |
| 3 | 2023 (reprise) | +42,6 % | +121,7 % | rentre en retard, rend une grosse part du rebond |
| 4 | 2024 | +61,2 % | +63,3 % | égalité |

**Tout l'avantage vient de la fenêtre 2.** La conclusion de l'étude, mot pour mot :
« *TSMOM ne bat pas le B&H en choisissant des gagnants — il le bat en s'asseyant hors des
krachs.* » Drawdown réduit sur **3 actifs sur 3** (BTC −53 % contre −77 %).

> **Ce que ça veut dire pour ta demande** : « adapter le trading quand ça baisse fort » n'est
> pas une amélioration parmi d'autres. C'est **le seul mécanisme que ce projet ait mesuré
> comme fonctionnant** (l'évitement de krach). L'optimisation de paramètres, elle, n'a jamais
> survécu au walk-forward (étude #1 : in-sample +43,8 %, OOS −13,6 %).

Et la stratégie qui tourne aujourd'hui en paper — SMA croisement, pas SMA 50/200 figé — **n'a
pas ce comportement**.

### Ce que le corpus d'études dit déjà (recopié, pas seulement cité)

- **Étude #1** (2026-06-07) — SMA optimisé : in-sample flatteur (+43,8 %), OOS **négatif**
  (−13,6 %, 25 % de fenêtres profitables). *L'optimisation flatte ; le walk-forward démasque.*
- **Étude #3** (2026-06-10) — SMA 50/200 figé multi-actifs sur 2 ans : **non robuste** (1/3
  positif). Mais l'échantillon était trop court — leçon : ne pas conclure sur 2 ans.
- **Étude #4** (2026-06-10) — sur ~8 ans (Binance long) : **TSMOM 3/3 positif, SMA 50/200
  2/3**. Premier signal d'edge. Nuance déjà écrite : l'edge attendu est le rendement **ajusté
  du risque**, pas de battre le B&H en absolu.
- **Étude #5** (2026-07-16) — l'edge de TSMOM est du **crisis-alpha** (évitement de krach),
  pas de la génération de rendement ; sensibilité au lookback **élevée** (seul 365 fait 3/3) ;
  les gros cumuls de l'étude #4 étaient surtout du bêta.
- **Reco déjà actée dans le journal d'enquête** : « *Prochaine brique OOS : **filtre régime +
  vol-targeting (panel #3)** par-dessus, validé au Sharpe/DD hors-échantillon, avant tout
  `--final`.* » — **cette spec EST cette brique**, élargie de l'anti-fragilité (vote de
  lookbacks) et d'un étage 3 optionnel.

---

## 2. Tes deux moitiés n'ont pas le même pronostic — il faut les séparer

Tu as demandé une IA « **prédictive** et surtout **adaptative** ». Ce sont deux projets
différents, et les traiter comme un seul serait malhonnête.

### 2a. La moitié ADAPTATIVE — solide, mesurable, à faire

Ce n'est pas de l'IA : c'est une **machine à états** qui répond à « dans quel régime
sommes-nous ? » et change de comportement en conséquence. La littérature est ancienne et
solide (Moskowitz-Ooi-Pedersen sur le momentum 12 mois, vol targeting). Surtout : **notre
propre mesure le confirme sur nos propres données**.

Pronostic : **bon**, avec une réserve sérieuse détaillée au §3, étage 1.

### 2b. La moitié PRÉDICTIVE — le piège classique, à traiter comme tel

Entraîner un modèle à prédire le rendement de demain à partir de l'historique de prix est
l'endroit exact où meurent les projets de quant amateur. Les raisons, sans enrobage :

- **Rapport signal/bruit catastrophique.** Sur des barres journalières, la part prévisible du
  rendement est de l'ordre de quelques pour cent de la variance. Un modèle qui affiche « 55 %
  de bonnes prédictions » en backtest est presque toujours en train de mémoriser.
- **Trop peu de données.** Cinq ans de bougies journalières font environ 1 800 points. Un
  réseau de neurones a plus de paramètres que ça ; même un gradient boosting y sur-apprend
  sans effort.
- **Non-stationnarité.** Le régime qui a produit les données d'entraînement n'est pas celui de
  demain — c'est précisément le sujet de cette spec, et ça se retourne contre le modèle.
- **Les frais tuent les petits edges.** `config.FEE = 0,80 %` par aller-retour chez Kraken. Un
  signal qui gagne 0,3 % par trade perd de l'argent.

Pronostic : **mauvais a priori.** Ce n'est pas une raison de ne pas essayer — c'en est une de
poser les critères d'échec **avant** de commencer, et de ne jamais laisser ce modèle toucher
de l'argent réel avant qu'il ait passé le même juge que tout le reste.

> **Le compromis, en trois lignes :**
> - **on obtient** un modèle appris qui pondère plusieurs signaux de régime au lieu d'un seuil
>   écrit à la main ;
> - **on abandonne** l'oracle qui prédit le prix — on ne prédit pas le rendement, on **classe
>   l'état du marché** ;
> - **ça coûte** un lot de travail, et le risque réel de conclure « ça n'apporte rien », qui
>   est l'issue la plus probable et qu'il faut accepter d'écrire.

---

## 3. Le design proposé — trois étages, du plus sûr au plus spéculatif

Chaque étage est utile seul, se mesure seul, se livre seul. On ne passe au suivant que si le
précédent a passé le walk-forward.

### Étage 1 — Détecteur de régime (aucune IA, aucun paramètre optimisé)

Trois états : **RISK-ON** · **NEUTRE** · **RISK-OFF**.

Entrées, toutes calculables sur les données déjà disponibles :

- momentum long terme (prix contre sa moyenne longue) — le signal validé par l'étude 5 ;
- pente de la moyenne longue (le marché monte-t-il ou descend-il) ;
- volatilité réalisée rapportée à sa propre médiane historique — les krachs sont des épisodes
  de volatilité, pas seulement de baisse ;
- drawdown courant depuis le plus haut glissant.

**Anti-fragilité — le point critique de toute cette spec.** L'étude 5 a montré que le TSMOM ne
gagne **qu'à 365 j**, encadré de deux valeurs perdantes (180 et 540 négatifs sur BTC).
Construire un système sur 365 serait bâtir sur du sable. Donc : **vote d'un ensemble de
lookbacks** (180 / 270 / 365 / 450 / 540), régime déterminé à la **majorité**, jamais par une
valeur élue.

Si le résultat de l'ensemble s'effondre alors que 365 seul brillait, **c'est la preuve que 365
était un accident de ce cycle** — et c'est une information qu'on veut obtenir avant de risquer
de l'argent, pas après.

### Étage 2 — Réponse adaptative (ce que le régime change concrètement)

| Régime | Exposition | Stop | Prise de profit |
|---|---|---|---|
| RISK-ON | pleine, sizing par volatilité (déjà implémenté) | normal | normal |
| NEUTRE | réduite de moitié | resserré | inchangé |
| RISK-OFF | **zéro — cash** | sans objet | sans objet |

C'est exactement le mécanisme de la fenêtre 2 : **rester en cash pendant le bear**. Le prix à
payer est connu et mesuré — on rend une partie du rebond (fenêtre 3 : +43 % contre +122 %).
Ce n'est pas un défaut à corriger, c'est le coût de l'assurance. Il doit être **écrit dans
l'interface**, pas caché.

### Étage 3 — La « petite IA », et seulement à cet endroit

Un modèle **simple et interprétable** (régression logistique, ou gradient boosting à
profondeur très faible) dont la cible n'est **pas** le rendement de demain, mais :

> « à horizon N jours, sommes-nous dans un régime où le drawdown va dépasser X % ? »

C'est une **classification d'état**, bien plus apprenable qu'une prédiction de rendement, et
directement actionnable par l'étage 2. Le modèle **remplace le vote par majorité** de l'étage 1
— et seulement s'il fait mieux que lui.

Contraintes non négociables :

- entraînement **uniquement** sur la partie in-sample, jamais sur les fenêtres de test ;
- ré-entraînement **glissant** dans le walk-forward : à chaque fenêtre, le modèle ne voit que
  le passé — sinon c'est du lookahead déguisé ;
- **le holdout sacré reste vierge** ; `--final` ne se lance jamais sans décision explicite de
  Mandar ;
- si le modèle ne bat pas le vote par majorité, **on garde l'étage 1** et on écrit noir sur
  blanc que l'IA n'a rien apporté.

---

## 4. Les critères d'échec — posés MAINTENANT, avant de coder

Une gate calibrée après coup ne teste rien. Donc, gelés à l'avance :

1. **Le régime doit réduire le drawdown maximum hors échantillon** sur 3 actifs sur 3, versus
   la même stratégie sans régime. Un régime qui n'amortit pas les krachs n'a aucune raison
   d'exister — c'est sa seule justification.
2. **Robustesse au lookback** : le résultat de l'ensemble doit rester positif quand on retire
   n'importe lequel des membres du vote. Si tout dépend d'un seul, c'est 365 déguisé.
3. **Marge sur les frais** : le nombre d'allers-retours induits par les bascules de régime est
   compté, et le gain doit survivre à `FEE = 0,80 %` par aller-retour.
4. **Aucun seuil dérivé des fenêtres de test.** Les seuils viennent de l'in-sample ou de la
   littérature, jamais d'un ajustement « pour que ça passe ».
5. **Étage 3 seulement** : le modèle doit battre l'étage 1 **sur le walk-forward**, pas sur le
   backtest. Écart non significatif = on ne garde pas le modèle.

Si l'un de ces cinq points tombe, la conclusion écrite est « ça n'a pas marché » et le paper
continue sans. C'est une issue acceptable et prévue.

---

## 5. Plan par lots — chacun livrable et jugeable seul

| Lot | Contenu | Juge |
|---|---|---|
| **A** | `trading/regime.py` — détecteur pur (aucun I/O, aucun état) + tests sur séries synthétiques : bear fabriqué, bull fabriqué, plat | tests unitaires |
| **B** | Branchement dans le backtester en surcouche d'une stratégie existante ; comparaison régime / sans régime | walk-forward, critères 4.1 à 4.3 |
| **C** | Écran web « Régime » : état courant, historique des bascules, coût en frais, et **le coût du retard en bull affiché honnêtement** | SQA runtime + gate visuelle |
| **D** | Branchement paper en **mode observation** : le régime est calculé et journalisé **sans agir**, pendant plusieurs semaines | comparaison journal contre réalité |
| **E** | Étage 3 — modèle appris, ré-entraînement glissant | critère 4.5 |

**Le lot D passe avant le lot E, sans négociation** : on regarde le détecteur annoncer des
régimes en temps réel pendant des semaines avant de lui laisser changer quoi que ce soit.

---

## 6. Ce qu'on ne fera pas

- ❌ Réseau de neurones, LSTM ou transformer sur des bougies — trop de paramètres pour environ
  1 800 points, sur-apprentissage garanti.
- ❌ Prédiction du prix ou du rendement comme cible d'entraînement.
- ❌ Sélection du meilleur lookback après avoir vu les résultats — c'est ce que l'étude 5
  s'interdit explicitement.
- ❌ Toucher au holdout sans décision explicite de Mandar.
- ❌ Passer en live sur ce système avant de l'avoir vu tourner en paper à travers un vrai
  épisode de baisse.

---

## 7. Références internes

- `docs/ETUDE_5_TSMOM_VS_BH.md` — la mesure fondatrice : crisis-alpha et sensibilité au lookback
- `trading/optimizer.py` — `walk_forward()`, le juge
- `trading/backtester.py` — moteur événementiel, stop / trailing / sizing intra-bougie
- `config.py` — `FEE` et plafonds live
- `docs/SQA.md` — registre des bugs ; tout correctif exige son test de non-régression
