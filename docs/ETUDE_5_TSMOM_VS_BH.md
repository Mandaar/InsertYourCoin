# Etude #5 -- TSMOM vs Buy & Hold (le caveat n.1 de l'etude #4)

> Date : 2026-07-16. Suite directe du **Resultat d'etude #4** (`ENQUETE_ET_AMELIORATIONS.md` §2).
> Doctrine : le **walk-forward hors-echantillon est le juge** ; honnetete absolue, jamais de survente.
> **Holdout INTACT** : aucun `--final` lance. Aucun fichier de code existant modifie
> (seul ajout : `scripts/etude5_tsmom.py`, qui importe les modules sans les toucher).

---

## 0. La question a trancher

L'etude #4 a montre TSMOM 365j **positif 3/3 actifs** en walk-forward, mais **sans
jamais afficher le Buy & Hold**. D'ou la seule question qui compte :

> **TSMOM bat-il reellement le Buy & Hold, ou ne fait-il que le suivre avec moins de casse ?**

Les gros cumuls OOS de l'etude #4 (+118%, +308%...) peuvent n'etre que du **beta**
(les actifs ont beaucoup monte) et non de l'**alpha** au-dessus du B&H. On tranche ici.

---

## 1. Protocole exact (reproductible)

- **Donnees** : source **Binance** (historique long, sans cle), timeframe **1d**, tout
  le listing (BTC/ETH depuis 2017-08, SOL depuis 2020-08). Derniere bougie (en
  formation) exclue. Cache disque `data/history/`.
- **Holdout 20% sacre** : les 20% de bougies les plus recentes sont RETIREES avant
  toute analyse (meme frontiere `holdout_split` que le CLI). Elles ne sont **jamais**
  vues. On travaille sur le segment de **recherche** uniquement.
- **Walk-forward** : 4 fenetres, `train_frac=0.5`, params **FIGES** (zero optimisation,
  anti-data-mining), critere Sharpe.
- **Frais** : `config.FEE` = **0.80%** taker + **slippage 5 bps** (inchanges).
- **Comparaison B&H sur les MEMES fenetres** (pas sur toute l'histoire -- ce serait
  biaise) :
  - *Rendement* : TSMOM OOS = `walk_forward(...).oos_total_return` (chiffre officiel,
    identique a l'affichage CLI et a l'etude #4). B&H OOS = compose des
    `buy_hold_return` **par fenetre** que le backtester calcule deja (rebase sur le
    1er close de chaque segment compte) -> exactement les memes bornes, meme traitement.
  - *Risque* (Sharpe, drawdown max, volatilite) : mesure sur la courbe d'equite OOS
    **continue** (un seul backtest sur l'union des fenetres `[train_initial, n)`), pour
    TSMOM comme pour le B&H (`res.df["buy_hold"]`, memes formules moteur). La courbe
    continue est plus honnete pour le drawdown (un DD reel peut traverser une frontiere).

**Commandes CLI equivalentes** (le script structure ce que le CLI affiche + ajoute le B&H) :
```bash
# Reproduit le rendement OOS TSMOM (chiffre "TSMOM ret" des tableaux ci-dessous) :
.venv/Scripts/python.exe main.py walkforward --strategy tsmom --fixed "lookback=365" \
    --symbols BTC/USD,ETH/USD,SOL/USD --source binance --days 3600 --holdout 20
# Sensibilite : idem avec --fixed "lookback=180" puis "lookback=540".
# Temoin SMA : --strategy sma --fixed "fast=50,slow=200".
# Analyse complete (TSMOM ret + B&H ret + Sharpe/DD des deux cotes) :
.venv/Scripts/python.exe scripts/etude5_tsmom.py
```

**Validation croisee (Loi 2)** : le "TSMOM ret" du script est **identique** a la sortie
CLI `walkforward` (BTC +55.9%, ETH +98.2%, SOL +264.6% pour lookback 365) -> le harness
d'analyse est fiable. Le rendement OOS *continu* colle au *fenetre* a <3 pts pres partout
(BTC 55.9/58.6, SOL 264.6/270.9), ce qui confirme l'absence d'artefact de frontiere.

**Spans OOS effectifs** (segment de recherche, holdout retire) :

| Actif | Recherche | Span OOS (4 fenetres) | n OOS |
|---|---|---|---|
| BTC/USD | 2017-08-17 -> 2024-10-02 (2604 b.) | 2021-03-11 -> 2024-10-02 | 1302 |
| ETH/USD | 2017-08-17 -> 2024-10-02 (2604 b.) | 2021-03-11 -> 2024-10-02 | 1302 |
| SOL/USD | 2020-08-11 -> 2025-05-08 (1732 b.) | 2022-12-25 -> 2025-05-08 | 866 |

> Note cruciale sur les spans : avec `train_frac=0.5`, l'OOS de BTC/ETH **demarre pres
> d'un sommet (mars 2021)** et **englobe le krach 2022** ; celui de SOL **demarre au
> creux absolu (fin 2022)** et **ne contient aucun krach majeur**. Ce placement, purement
> mecanique, oriente deja la comparaison (voir §5).

---

## 2. Resultat principal -- TSMOM 365j (FIGE) vs Buy & Hold, par actif (OOS)

| Actif | TSMOM ret | B&H ret | TSMOM Sharpe | B&H Sharpe | TSMOM DD max | B&H DD max | % fen. prof. | DSR* |
|---|---|---|---|---|---|---|---|---|
| **BTC/USD** | **+55.9%** | +6.7% | **0.49** | 0.32 | **-53.1%** | -76.6% | 75% | 93% |
| **ETH/USD** | **+98.2%** | +31.4% | **0.62** | 0.48 | **-57.2%** | -79.3% | 100% | 89% |
| **SOL/USD** | +264.6% | **+1317.8%** | 1.12 | **1.66** | **-52.9%** | -59.8% | 50% | 98% |

*Rendement = OOS compose sur les memes fenetres (walk-forward). Sharpe / DD = courbe OOS
continue, memes bornes. Frais 0.80% + slippage 5 bps.*
*DSR = deflated Sharpe **par config** (n_trials=1, params figes) ; il ne deflate PAS
l'exploration des 3 lookbacks (voir §4 et §7).*

**Lecture honnete, en trois lignes** :
- **Drawdown : TSMOM gagne 3/3.** Il reduit le DD max sur les trois actifs (BTC -53 vs
  -77, ETH -57 vs -79, SOL -53 vs -60). La "moins de casse" est **reelle**.
- **Rendement : TSMOM gagne 2/3.** Il bat le B&H en rendement sur BTC et ETH, mais se
  fait **ecraser sur SOL** (+265% vs +1318%).
- **Sharpe : TSMOM gagne 2/3.** Meilleur risk-adjusted sur BTC/ETH, **inferieur sur SOL**
  (1.12 vs 1.66) -- sur SOL le B&H gagne sur les DEUX tableaux.

---

## 3. D'ou vient l'ecart -- decomposition fenetre par fenetre (BTC 365)

Le rendement de chaque fenetre OOS raconte le mecanisme (TSMOM vs B&H, %) :

| Fenetre | ~Periode | TSMOM | B&H | Ce qui se passe |
|---|---|---|---|---|
| 1 | 2021 (top + debut baisse) | -32.2% | -33.9% | TSMOM encore long -> subit comme le B&H |
| 2 | 2022 (bear) | **+0.1%** | **-55.4%** | **TSMOM en CASH -> evite le krach (crisis-alpha)** |
| 3 | 2023 (reprise) | +42.6% | +121.7% | TSMOM re-entre en retard -> **rend une grosse part du rebond** |
| 4 | 2024 | +61.2% | +63.3% | ~egalite |

**Tout l'avantage de TSMOM sur BTC vient de la fenetre 2** (rester en cash pendant le
bear 2022 : 0% vs -55%). En bull, il **retarde** (fenetre 3 : +43% vs +122%). Meme motif
sur ETH (fenetre 2 : +3% vs -53%). Autrement dit : **TSMOM ne bat pas le B&H en choisissant
des gagnants -- il le bat en s'asseyant hors des krachs.** Quand la fenetre OOS ne contient
pas de krach (SOL, mesure depuis un creux), il ne fait que suivre en moins bien.

Contexte revelateur : sur le span BTC 2021-03 -> 2024-10, le B&H **n'a fait que +5 a +7%**
(BTC ~flat entre ces deux dates, avec un krach et un rebond au milieu). Le +56% de TSMOM
est presque entierement l'evitement du trou. Sur SOL 2022-12 -> 2025-05, le B&H a fait
**+1318%** (achat au creux absolu) : impossible a battre pour un filtre de tendance qui, par
construction, re-entre **apres** le debut de la hausse.

---

## 4. Sensibilite au lookback (anti-data-mining) -- on DOCUMENTE, on ne SELECTIONNE pas

Memes runs, lookback **fige** a 180, 365, 540 (jamais optimise). Rendement OOS (fenetres) :

| Actif | 180j | **365j** | 540j | Positifs |
|---|---|---|---|---|
| BTC/USD | **-25.7%** | +55.9% | **-32.1%** | 1/3 (seul 365) |
| ETH/USD | +41.9% | +98.2% | **-39.9%** | 2/3 (180, 365) |
| SOL/USD | +251.7% | +264.6% | +152.6% | 3/3 |
| **Actifs positifs** | **2/3** | **3/3** | **1/3** | |

Sharpe OOS continu correspondant (pour contexte) :

| Actif | 180j | 365j | 540j |
|---|---|---|---|
| BTC/USD | 0.04 | 0.49 | 0.04 |
| ETH/USD | 0.47 | 0.62 | 0.14 |
| SOL/USD | 1.07 | 1.12 | 0.91 |

**Verdict sensibilite** : le signal est **tres sensible** au lookback. **Seul 365 donne
3/3 positif** ; a 180 BTC devient negatif, a 540 BTC **et** ETH deviennent negatifs (DSR
ETH@540 chute a 36%, sous le seuil de credibilite). Que **365 (la valeur canonique du
momentum 12 mois) soit precisement le pic** est autant un argument litteraire (Moskowitz-
Ooi-Pedersen) **qu'un signal de fragilite** : pour BTC, le resultat n'existe **qu'a 365**,
encadre de deux valeurs perdantes. On ne peut pas exclure qu'atterrir sur la meilleure
valeur tienne en partie a la structure de CE cycle. **On documente cette fragilite ; on ne
choisit surtout pas 365 comme "le bon parametre".**

---

## 5. Temoin SMA 50/200 (FIGE) vs Buy & Hold (OOS)

| Actif | SMA ret | B&H ret | SMA Sharpe | B&H Sharpe | SMA DD max | B&H DD max |
|---|---|---|---|---|---|---|
| BTC/USD | +3.4% | +6.7% | 0.23 | 0.32 | -58.2% | -76.6% |
| ETH/USD | +67.7% | +31.4% | 0.54 | 0.48 | -57.2% | -79.3% |
| SOL/USD | +48.7% | +1317.8% | 0.60 | 1.66 | -60.0% | -59.8% |

Meme profil que TSMOM, en **plus faible** : SMA 50/200 ne bat le B&H en rendement que sur
ETH (1/3), reduit le DD sur BTC/ETH (mais **pas** sur SOL), et se fait ecraser sur SOL.
**TSMOM 365 est le meilleur des deux trend-followers**, mais ils partagent **exactement la
meme limite structurelle** : ils vivent de l'evitement de krach, pas de la generation de
rendement, et perdent contre un B&H mesure depuis un creux.

---

## 6. Verdicts (une phrase par question)

- **Q1 -- TSMOM bat-il le B&H ?** *Non de facon fiable : il **reduit le drawdown 3/3**
  (la "moins de casse" est reelle) mais ne bat le B&H en rendement ET en Sharpe que sur
  **2/3** (BTC, ETH) et perd lourdement sur SOL -- son avantage est du **crisis-alpha**
  (evitement des krachs), donc les gros cumuls OOS de l'etude #4 sont surtout du **beta**,
  pas de l'alpha au-dessus du B&H.*
- **Q2 -- Sensibilite au lookback ?** *Elevee : **seul 365 donne 3/3 positif**, encadre de
  valeurs perdantes (BTC negatif a 180 et 540) ; que la valeur canonique soit le pic est
  un signal de **fragilite a documenter, pas un parametre a selectionner**.*
- **Q3 -- Temoin SMA 50/200 ?** *Meme conclusion en plus faible (bat le B&H en rendement
  sur ETH seulement, reduit le DD sur BTC/ETH, ecrase par SOL) -- confirme que le profil
  "reducteur de drawdown, pas batteur de marche" est **structurel** au trend-following, pas
  propre a TSMOM.*

---

## 7. Caveats restants (a relire avant toute decision)

1. **Comparaison regime-dependante par placement de fenetre.** Le split 50/50 fait
   demarrer l'OOS de BTC/ETH pres d'un sommet (favorable au trend-follower, krach a
   eviter) et celui de SOL au creux absolu (favorable au B&H). "TSMOM 3/3 positif" (etude
   #4) est vrai mais **ne signifie pas 3/3 "bat le marche"** : c'est du beta haussier +
   evitement de krach sur 2 des 3.
2. **Instabilite des estimations par actif.** Entre l'etude #4 (2026-06-10) et #5
   (2026-07-16), **+36 bougies** (~1% d'historique en plus) ont fait passer, a strategie et
   params identiques, ETH de +4.9% a +98.2% et BTC de +118.9% a +55.9% (la moyenne 3
   actifs restant ~+140%). Les chiffres OOS par actif ne sont **pas des estimations
   ponctuelles stables** : le walk-forward 4-fenetres est sensible a l'emplacement exact
   des frontieres. A traiter comme des ordres de grandeur, jamais comme des cibles.
3. **DSR non deflate de l'exploration des lookbacks.** Les DSR affiches (93/89/98%)
   supposent **1 hypothese pre-enregistree** (n_trials=1) ; ils **ne penalisent pas** le
   fait d'avoir teste 180/365/540. En tenant compte de cette exploration, la confiance
   reelle sur BTC@365 (le seul lookback positif pour BTC) est **nettement plus basse** que
   93%.
4. **USDT vs USD.** Recherche sur Binance USDT ; execution reelle sur Kraken USD. Ecarts
   minimes en daily mais reels (frais, slippage, liquidite, prime stablecoin).
5. **Un cycle et demi seulement**, majors liquides uniquement (survivorship des alts morts
   non teste).
6. **Le HOLDOUT RESTE VIERGE.** Aucun `--final`. La validation finale sur les 20% sacres
   (2024-10 -> 2026-07 pour BTC/ETH ; 2025-05 -> 2026-07 pour SOL) est une **decision
   explicite de Mandar, UNE seule fois**. C'est le dernier juge -- pas ce rapport.

---

## 8. Recommandation (au producer / a la decision)

- **Ne pas presenter TSMOM comme "bat le marche".** Le positionner honnetement : *outil de
  reduction de drawdown (crisis-alpha), a esperance de rendement <= B&H sur un actif porte
  par un bull depuis un creux.* C'est utile pour **preserver le capital** (garde-fou n.2
  du projet), pas pour maximiser le rendement.
- **Prochaine brique a valider (OOS, avant tout --final)** : la couche **filtre de regime +
  vol-targeting** (panel #3) PAR-DESSUS TSMOM 365 -- non pour inventer du rendement (le
  risk-management lisse, il ne cree pas), mais pour voir si elle ameliore le **Sharpe/DD
  hors-echantillon** sans coup de chance. Chaque parametre ajoute doit gagner sa place en
  OOS, sinon on le retire.
- **Garder 365 fige** (ne pas migrer vers 180/540 "parce que 365 gagne") : ce serait
  precisement le data-mining que ce rapport denonce. La sensibilite mesuree ici est une
  raison de **prudence**, pas un menu de selection.
