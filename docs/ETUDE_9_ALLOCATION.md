# Etude #9 — Diversifier, ou l'arithmetique qui ne pardonne pas

> Date : 2026-09-02. Demande de Mandar (verbatim) : « *pourquoi chercher forcement une solution, il
> est peut etre interessant de varier, on ne [met] pas ses oeufs dans le meme panier* » puis
> « *renseigne toi* ».
> Doctrine : honnetete avant tout, le walk-forward hors-echantillon est le juge, jamais de survente.
> Methode : recherche web uniquement (aucun serveur, aucun navigateur, aucune fenetre lancee).
> Chaque chiffre porte son statut **MESURE** (chiffre d'une source, avec periode et echantillon) /
> **DERIVE** (calcule a partir d'un MESURE) / **SUPPOSE**.
> **Garde-fou n°6 du projet : aucun conseil en investissement personnalise. Les decisions et le
> risque appartiennent a l'utilisateur.**

**Contexte : ce qui etait deja etabli avant cette etude** (etudes #1 a #7, statut MESURE) —
croisements de moyennes mobiles intraday morts (47 % du capital en frais en 11 jours, -35 %) ;
balayage 5 min -> 4 h sur 22 jours, aucune configuration positive hors-echantillon ; TSMOM 365 j
valide sur 8 ans en reduction de drawdown mais -26,3 % sur les 2 dernieres annees d'ETH contre
+5,4 % en ne faisant rien ; modele predictif (regression logistique, walk-forward, criteres geles
d'avance) rejete, battu par « ne rien faire » sur 3 actifs sur 3 **meme avec frais et slippage a
zero** ; buy & hold est le seul comparateur que rien n'a battu.

Cette etude ne cherche donc plus **LA** strategie. Elle instruit la piste **allocation**.

---

## 1. La question centrale : diversifier des paris sans edge

### 1.1 La reponse honnete est NON, et ce n'est pas une opinion

**MESURE (mathematique, pas empirique)** : l'esperance d'un portefeuille est la **moyenne ponderee**
des esperances de ses composantes. Il n'y a **aucun terme d'interaction**. La correlation n'agit que
sur la variance, jamais sur l'esperance.

```
E[w1*S1 + w2*S2 + ... + wN*SN] = w1*E[S1] + w2*E[S2] + ... + wN*E[SN]
```

Consequence directe : combiner N strategies d'esperance nulle ou negative donne un portefeuille
d'esperance nulle ou negative. C'est une contrainte arithmetique, pas une hypothese de marche. On
ne la contourne pas en changeant de strategies, de timeframe ou de parametres.

**Ce que la diversification fait reellement** : elle reduit la variance, donc la dispersion des
resultats. Sur des paris perdants, elle **rend la perte plus reguliere, pas plus petite**.

**Et il y a pire dans notre cas, DERIVE** : les frais s'additionnent **eux aussi lineairement**.
Diversifier sur 4 strategies actives a 0,40 % par ordre multiplie par 4 le nombre d'ordres, donc
reproduit a petite echelle exactement ce que l'etude #6bis a mesure (47 % du capital en frais en
11 jours). Diversifier des strategies actives, chez nous, **degrade** l'esperance au lieu de la
laisser inchangee.

### 1.2 La relecture positive de l'intuition — elle est juste, mais sur un autre panier

L'intuition « on ne met pas ses oeufs dans le meme panier » est **correcte**. Ce qui doit changer,
c'est l'identification du panier.

| Ce qu'on croit diversifier | Ce que ca vaut |
|---|---|
| Plusieurs **strategies** sans edge demontre | Rien. Esperance = moyenne ponderee (§1.1). Frais x N. |
| Plusieurs **cryptos** (BTC/ETH/SOL) | Presque rien. Correlation ~0,8 **MESURE** en interne (etude portefeuille). Lisse, ne protege pas d'un krach systemique. |
| Plusieurs **classes d'actifs** a esperance positive propre | **C'est la seule diversification qui compte.** |

**Le panier a diversifier n'est pas les strategies, ce sont les classes d'actifs — et chacune doit
avoir une esperance positive propre, etablie independamment.** Une classe d'actifs a esperance
negative n'est pas rachetee par ses voisines : elle tire la moyenne vers le bas, exactement a
hauteur de son poids.

Applique a ce projet : « crypto detenue en buy & hold » d'un cote, « tresorerie euro remuneree » de
l'autre. Deux paniers dont chacun a une esperance defendable seul. La proportion est une decision
qui appartient a l'utilisateur (garde-fou n°6).

### 1.3 DeMiguel-Garlappi-Uppal (2009) — ce que le papier dit vraiment

**MESURE** (*Review of Financial Studies* 22(5), 2009, p. 1915-1953) :
- Sur **14 modeles** d'allocation optimisee testes sur **7 jeux de donnees empiriques**, **aucun**
  ne bat systematiquement le 1/N en ratio de Sharpe, en equivalent-certitude ou en turnover.
- Fenetre d'estimation necessaire pour qu'une moyenne-variance echantillonnale batte le 1/N :
  **~3 000 mois pour 25 actifs**, **~6 000 mois pour 50 actifs** (250 a 500 ans de donnees).

**Transposable a un panier de strategies ? Partiellement, et pas dans le sens espere.**

1. Le message central du papier est **anti-estimation** : chaque parametre estime sur donnees
   courtes detruit plus de valeur qu'il n'en cree. Ce message s'applique integralement a nous et
   **condamne l'optimisation de parametres** que fait `trading/optimizer.py`. C'est le point le plus
   actionnable de tout le papier pour ce depot.
2. Mais le 1/N de DGU s'applique a un univers d'actifs a **esperance positive** (actions). Un 1/N
   sur des strategies a esperance negative reste negatif (§1.1). Le papier ne dit **nulle part** que
   l'equiponderation cree du rendement : il dit qu'elle en detruit **moins** que l'optimisation.

Source : https://academic.oup.com/rfs/article-abstract/22/5/1915/1592901

---

## 2. Rendement sans exposition directionnelle

C'est le seul endroit ou un edge **structurel** (un mecanisme economique identifie) plutot que
statistique pourrait exister pour un particulier. Trois pistes instruites, un seul survivant.

### 2.1 Rendement sur stablecoins — PISTE FERMEE par la reglementation

**MESURE** (page support officielle Kraken, consultee 2026-09-02) :

| Actif | Taux non-abonne | Taux Kraken+ | Disponibilite |
|---|---|---|---|
| USDG | 2 % | 4,25 % | partout **SAUF l'EEE** |
| USDC | 1,75 % | 3,75 % | **US, Canada, Australie, UK uniquement** |
| APXUSD | 3 % | 6 % | hors Bresil/Argentine/EAU — pas l'EEE |
| USDe | 3,5 % (plafond 25 000 jetons) | 4,25 % | idem |
| RLUSD | 1,75 % | 3,75 % | US et UK uniquement |
| tGBP | 2 % | 4 % | mondial hors regions restreintes |

L'EEE — donc la France — est explicitement exclu de la ligne USDG, et les autres lignes sont soit
US/UK, soit hors-EEE.

**Cause racine, MESURE** : l'**article 50 de MiCA** interdit a tout prestataire agree dans l'UE
d'octroyer des interets ou toute remuneration liee a la detention d'un jeton de monnaie
electronique (EMT). L'interdiction couvre explicitement **bonus, recompenses et produits d'epargne
flexible** — pas seulement le mot « interet ».

**Point d'evolution possible, MESURE** : la Commission europeenne a ouvert une consultation sur le
fonctionnement de MiCA le **20 mai 2026** (cloture **31 aout 2026**), **la remuneration figurant
parmi les sujets ouverts**. La regle **peut** bouger. A la date de cette etude, **elle n'a pas
bouge** — et une piste qui depend d'un changement reglementaire futur n'est pas une piste, c'est un
pari sur un legislateur.

**Bilan de piste**
- **OBTIENT** : rien, en France, chez Kraken. Le produit n'existe pas pour un resident francais.
- **ABANDONNE** : sans objet.
- **COUTE** : le contournement (plateforme non-EEE, stablecoin non-MiCA type USDT) echange 2-4 % de
  rendement contre un risque de contrepartie non regule et un delistage EEE deja acte (USDT retire
  des paires par Kraken, Binance et Bitpanda en 2026, **MESURE**). Le rapport est defavorable : le
  taux sans risque euro se prend en produit de tresorerie classique, sous garantie bancaire, sans
  risque de depeg ni de blocage de retrait.

Sources : https://support.kraken.com/articles/stablecoin-rewards ·
https://www.amf-france.org/en/news-publications/depth/mica ·
https://en.cryptonomist.ch/2026/09/01/mica-interest-ban-stablecoins/

### 2.2 Funding rate / cash-and-carry — PISTE FERMEE DEUX FOIS

C'etait le seul edge a **mecanisme economique identifie** repere dans les etudes precedentes : une
prime payee par des acheteurs a levier. Le mecanisme est reel. La piste est fermee quand meme, pour
deux raisons independantes.

**Fermeture n°1 — la prime est morte. MESURE** : Borri, Liu, Tsyvinski & Wu, *Cryptocurrency as an
Investable Asset Class: Coming of Age*, arXiv:2510.14435. Donnees Binance, perpetuals BTC,
**1er aout 2020 -> 31 mai 2025**, strategie = long spot / short perpetuel :

| Periode | Sharpe annualise |
|---|---|
| Plein echantillon (08/2020 - 05/2025) | **6,45** |
| 2024 | **4,06** |
| 2025 | **negatif** |

Rendement moyen de funding ~8 % pour une volatilite de 0,8 %. Le papier ecrit que les primes de
funding « ne sont ni garanties ni permanentes » et pose explicitement la question de la
soutenabilite a long terme des produits de rendement construits dessus.

**MESURE, etat du marche** : apres le krach du 10-11 octobre 2025, l'open interest BTC est passe
d'environ **45 Md$ a ~22 Md$** ; le rendement annualise du cash-and-carry est passe d'environ
**13,5 % a ~5 %**, soit la convergence vers le taux sans risque. Le funding perpetuel BTC etait
**negatif (-0,0048 %) au 28 aout 2026**.

**Origine theorique, MESURE** : Schmeling, Schrimpf & Todorov, *Crypto Carry*, BIS Working Paper
1087 (2023), publie dans *Management Science* (2026). Le carry a pu depasser **40 % par an**. Le
mecanisme identifie : demande de levier de petits investisseurs suiveurs de tendance, face a un
capital d'arbitrage limite par les frictions reglementaires et de marge.

**Fermeture n°2 — hors mandat, DERIVE de la contrainte du projet** : la jambe courte du
cash-and-carry est une position **short sur futures ou perpetuels**. Le mandat de ce projet est
**spot Kraken, sans levier, sans short** (CLAUDE.md, garde-fous 1 a 4). La strategie n'est pas
executable dans le perimetre, quelle que soit la prime.

**Ecarte explicitement** : les chiffres a 10-30 %/an circulant sur cette strategie proviennent
**exclusivement de contenu promotionnel** (billets Medium d'arbitragistes, academies d'exchanges).
Aucune source academique ne les soutient. **Le fait qu'une piste ne soit portee que par ceux qui la
vendent est en soi une information.**

Sources : https://arxiv.org/html/2510.14435 · https://www.bis.org/publ/work1087.htm ·
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4268371

### 2.3 Staking — LA SEULE PISTE POSITIVE, et elle est marginale

**MESURE** (pages Kraken officielles, 2026-09-02) — la vitrine : ETH « jusqu'a 2,53 % APY », SOL
« jusqu'a 5,61 % APY », accroche « jusqu'a 21 % » portee par des actifs marginaux (SCRT 13,7 %,
MINA 11,58 %, ATOM 10,41 %).

**MESURE** (page support staking) — ce que la vitrine n'affiche pas :

| Element | Valeur |
|---|---|
| Commission Kraken, flexible et Auto Earn | **30 % des recompenses** |
| Commission Kraken, staking bloque | 25 % en dessous d'1 M$ d'encours, degressive au-dela seulement |
| Base des taux affiches | **avant prelevement de la commission** (mention explicite sur la page FR) |
| Unbonding, mode bloque | **>= 3 jours**, actif ni cessible ni retirable |
| Unbonding, mode flexible | instantane, mais rendement plus bas |
| Garantie de recompense | **aucune** (« nous ne garantissons pas que vous gagnerez une recompense ») |
| Slashing | indemnisation **limitee**, exclue en cas de maintenance reseau, bug ou piratage |

**DERIVE** : 2,53 % (ETH) - 30 % de commission = **~1,77 %/an net**, libelle **en ETH**.

**Ce que ce chiffre est, et ce qu'il n'est pas.** Le rendement est paye dans un actif dont la
volatilite annuelle depasse 50 %. Ce n'est pas un revenu sans risque : c'est un **rabais d'environ
1,8 %/an sur une exposition directionnelle integrale**. Face au comparateur unique du projet
(buy & hold), le staking = buy & hold + ~1,8 %/an - un risque de blocage de 3 jours au pire moment.

C'est **le seul element de tout ce dossier qui ameliore reellement le fait de ne rien faire**, et il
est compatible avec le mandat spot. Mais il ne remplace pas une strategie : il ameliore
marginalement l'inaction.

**Bilan de piste**
- **OBTIENT** : ~1,8 %/an net sur ETH, ~3,9 %/an net sur SOL (**DERIVE** : 5,61 % - 30 %), en plus
  de la detention.
- **ABANDONNE** : la liquidite immediate en mode bloque (>= 3 j), et la simplicite fiscale (§2.4).
- **COUTE** : capital minimum negligeable ; complexite faible ; risque de perte totale nul du fait
  du staking lui-meme, **mais integral du fait de la detention de l'actif sous-jacent**. Le risque
  dominant reste le prix de l'actif, pas le staking.

Sources : https://support.kraken.com/articles/360037682011-overview-of-staking-on-kraken ·
https://www.kraken.com/fr/features/staking · https://www.kraken.com/features/staking/ethereum ·
https://www.kraken.com/features/staking/solana

### 2.4 Fiscalite francaise du staking — NON TRANCHEE, et il faut le dire

**Statut : NON ETABLI. Les sources se contredisent.**

| Lecture | Consequence | Source |
|---|---|---|
| BNC (art. 92 CGI, BOI-BNC-CHAMP-10-10-20-40), **taxable a la reception** | impot du meme si l'actif n'est jamais vendu, et meme s'il s'effondre ensuite | cabinet d'avocats (NBE) |
| Neutre a la reception, **taxable a la cession** au PFU 30 % (art. 150 VH bis) | impot seulement au moment de la vente | plusieurs sources commerciales, « BOFIP dedie attendu en 2026 » |

Les deux lectures aboutissent a des factures tres differentes, et la premiere peut rendre le
rendement net **negatif** si l'actif baisse apres reception. Le corpus trouve est majoritairement
**commercial** (editeurs d'outils fiscaux, blogs patrimoniaux, page « Learn » de Kraken elle-meme —
juge et partie). **Je ne tranche pas.**

**Voie restante** : lire directement le BOFIP `BOI-BNC-CHAMP-10-10-20-40` et la doctrine 150 VH bis,
ou consulter un fiscaliste. Tant que ce point n'est pas tranche, le « ~1,8 % net » du §2.3 est un
**brut de fiscalite**.

Source : https://www.nbe-avocats.fr/articles/cryptomonnaies/fiscalite-du-staking-crypto-en-france-regles-et-declarations-2026/

---

## 3. Rebalancement : la prime existe-t-elle ?

**MESURE (theorie)** : la litterature part de Booth & Fama (1992), « diversification return ». Le
papier arXiv:1109.1256 (*Diversification Return, Portfolio Rebalancing, and the Commodity Return
Puzzle*) conclut que ce supplement est **un artefact de mesure** : il vient de ce que le rendement
geometrique est une fonction **concave** de la volatilite, donc que le rendement geometrique d'un
portefeuille rebalance depasse mecaniquement la moyenne des rendements geometriques de ses
composantes. Ce n'est pas de la performance : c'est l'ecart entre moyenne arithmetique et moyenne
geometrique.

**MESURE (actions)** : sur un univers S&P 500, prime de rebalancement moyenne d'environ **90 points
de base sur 5 ans, hors frais de transaction** — soit **~18 bps/an brut** (**DERIVE**).

**DERIVE, et c'est le chiffre qui tranche** : 18 bps/an bruts contre **40 bps par ordre** chez nous.
Un rebalancement a deux jambes coute **~80 bps**. Il faudrait **plus de quatre ans** de prime
theorique pour payer **un seul** rebalancement. Sur crypto la volatilite est plus forte donc la
prime brute est plus grande, mais **aucune estimation nette de frais** n'a ete trouvee dans une
source serieuse.

**Signal en soi — ecarte explicitement** : les chiffres flatteurs sur le rebalancement crypto
(« seuil 15 %, +77,1 % vs HODL », « rebalancement quotidien, Sharpe superieur ») proviennent
**exclusivement de contenu promotionnel** : Zignaly, captainaltcoin, Hashdex, Phemex — tous
vendeurs d'outils ou de fonds de rebalancement. L'etude Quantpedia (27 cryptos,
31/12/2018 -> 29/10/2021), verifiee ligne a ligne, **ne chiffre pas la prime en texte et ne mentionne
pas les frais**. Une piste portee uniquement par ceux qui la vendent, sans chiffre net de frais
publie, se traite comme **non demontree**.

**Verdict** : NON DEMONTREE nette de frais. Testable en interne (fenetre de test proche de celle du
§4), mais l'ordre de grandeur ne plaide pas pour un rebalancement frequent.

Sources : https://arxiv.org/pdf/1109.1256 ·
https://www.aqr.com/-/media/AQR/Documents/Whitepapers/AQR_Portfolio-Rebalancing_Common-Misconceptions.pdf ·
https://link.springer.com/article/10.1007/s11408-022-00419-6 ·
https://quantpedia.com/estimating-rebalancing-premium-in-cryptocurrencies/

---

## 4. Le trou du dossier : timing BTC par SMA 200 j en cadence mensuelle

### 4.1 Faber — les VRAIS chiffres

**MESURE, mais par reproduction tierce, pas par le PDF original** (voir §6, point 5). Modele SMA
10 mois, 5 classes d'actifs (S&P 500 / obligations / EAFE / matieres premieres / REITs), cadence
mensuelle, **1973-2012** :

| | Timing SMA10 | Buy & hold |
|---|---|---|
| Rendement annualise brut | **10,5 %** | 9,9 % |
| Volatilite | **7,0 %** | 10,3 % |
| Sharpe brut | **0,73** | 0,44 |
| Drawdown max | **-9,5 %** | -46,0 % |

Version originale 1972-2005 : Sharpe 0,81, CAGR 11,7 %, DD -9,5 %.
**Mises a jour recentes** (incluant 2008, le COVID et 2022) : Sharpe **0,68**, CAGR **6,05 %**,
DD **-11,7 %**.

### 4.2 Les limites, et elles sont lourdes

1. **Le gain est en RISQUE, pas en rendement.** +0,6 point de CAGR contre -36 points de drawdown.
   C'est **exactement** ce que le TSMOM 365 j a mesure en interne (drawdown reduit 3 actifs sur 3,
   rendement detruit sur ETH). Les deux resultats sont **coherents**, pas contradictoires.
2. **Fragilite a la date d'execution, MESURE** : rebalancer un jour fixe du mois introduit
   **jusqu'a 220 bps de variance de CAGR** sans aucun rapport avec la strategie ; un etalement
   hebdomadaire ramene cela a **63 bps** et reduit le turnover annuel de pres de moitie. Un backtest
   mensuel non etale est donc **partiellement du bruit de calendrier**.
3. **Exposition non comparable** : le modele est investi a >= 60 % environ 80 % du temps, exposition
   moyenne 70 % (30 % en cash). Le comparer a un buy & hold a 100 % sans corriger l'exposition est
   trompeur.
4. **Frais et fiscalite** traites a minima dans l'original. Chez nous, chaque aller-retour coute
   **80 bps**, a comparer aux **60 bps** de surperformance annuelle du modele.

### 4.3 Litterature sur BTC + SMA 200 j mensuel : INTROUVABLE

**Aucune etude academique** en acces libre sur le timing BTC par moyenne 200 jours en cadence
mensuelle. Ce qui existe est du contenu de trading (substacks, guides d'exchanges, heatmaps
200-semaines) **sans protocole hors-echantillon**. Le constat tient : **c'est trivialement testable
avec le backtester du projet et personne de serieux n'a publie le resultat.**

### 4.4 Protocole minimal — a respecter integralement, sinon le test est ININTERPRETABLE

Si ce test est lance un jour sur la foi de ce document, il doit respecter **tous** les points
ci-dessous. Chacun repond a une faiblesse identifiee au §4.2.

1. **Un seul actif : BTC.** Pas de panier, pas de moyenne sur plusieurs actifs — sinon on melange
   l'effet du signal et l'effet de la diversification.
2. **Signal : SMA 200 jours, evaluee au dernier jour de chaque mois.** Cadence mensuelle stricte —
   c'est le point du dossier qui n'a jamais ete teste, ne pas deriver vers du journalier.
3. **Execution a l'ouverture de la barre suivante** (convention du projet : decision a la cloture de
   t, execution a l'ouverture de t+1, pas de lookahead).
4. **Frais : 0,40 % par jambe** (grille reelle maker verifiee — le code `config.py` fait foi, jamais
   un taux cite dans la doc).
5. **ETALEMENT DU JOUR DE DECISION SUR 4 TRANCHES HEBDOMADAIRES.** Quatre sous-portefeuilles de
   25 % chacun, decidant respectivement la semaine 1, 2, 3 et 4 du mois, puis moyenne des quatre.
   **Sans cet etalement, jusqu'a 220 bps de CAGR sont du pur bruit de calendrier et le resultat ne
   veut rien dire** (§4.2 point 2). C'est la condition la plus facile a oublier et la plus fatale.
6. **Comparateur unique : buy & hold sur le meme actif, meme periode, frais inclus a l'entree.**
   Aucun autre comparateur. Pas de comparaison a une version optimisee de soi-meme.
7. **Correction d'exposition** : reporter l'exposition moyenne du modele (% du temps investi) a cote
   du resultat, faute de quoi la comparaison au buy & hold a 100 % est biaisee (§4.2 point 3).
8. **Criteres de succes geles AVANT de lancer**, ecrits dans le depot, sur la vraie cible : battre
   le buy & hold **net de frais** sur la periode de test hors-echantillon. Un drawdown reduit sans
   rendement superieur est un **echec** au regard de la question posee — c'est deja mesure trois
   fois dans ce depot.
9. **Historique le plus long disponible** (>= 8 ans), split train/test declare d'avance.

Sources : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461 ·
https://www.cxoadvisory.com/technical-trading/long-term-outperformance-from-trends-defined-by-moving-averages/ ·
https://concretumgroup.substack.com/p/global-tactical-asset-allocation

---

## 5. Le piege : a quoi il ressemble AVANT

**Le motif est identique dans les quatre cas, MESURE** : un passif court terme finance des actifs
longs ou illiquides, avec un collateral peu echange, verrouille, ou correle au bilan de l'emetteur
lui-meme. Rien de tout cela n'est aleatoire, et rien n'etait invisible avant.

| Cas | Date | Chiffres (MESURE) |
|---|---|---|
| **Anchor / UST** | 2022 | 20 % promis sur UST, finances par une reserve tombee de **70 M$ (fev. 2022) a 35 M$ (avr. 2022)**, rythme -13 M$/mois, **zero programme pour juin 2022**. Le rendement etait la trajectoire **publiee on-chain** d'une faillite, six mois a l'avance. |
| **Celsius** | 2022 | Premier grand acteur emporte par UST. Hodlnaut : **-189,7 M$** sur Anchor. Risque de source de rendement **concentree**. |
| **Stream Finance / xUSD** | nov. 2025 | **93 M$** de perte ; **170 M$ d'actifs reels contre 530 M$ de jetons emis** (levier > 4:1) ; xUSD de 1,00 $ a **0,43 $** puis **-90 % en moins d'un jour** ; contagion sur deUSD d'Elixir (65 % de son collateral expose a Stream) **-98 %, de 1,00 $ a 0,015 $** ; ~285 M$ de contagion, ~500 M$ de capitalisation effacee. Aggravant : des protocoles de pret avaient **code en dur le prix de xUSD a 1,00 $** dans leurs oracles pour eviter les liquidations — une illusion de stabilite qui a transfere la perte aux preteurs. |
| **Ethena / USDe** | 11 oct. 2025 | Chute a **0,65 $ sur Binance** pendant la cascade de liquidations a 19 Md$ ; **-8,3 Md$** de sorties. Le debat « vrai depeg ou defaillance du carnet Binance » est secondaire : le detenteur subissait le prix affiche. **USDe est precisement un produit delta-neutre adosse au funding rate** — la piste du §2.2 emballee en jeton. Quand la prime de funding est morte en 2025, le produit a casse. |

### La regle des trois questions (DERIVE de ces quatre cas)

Tout rendement significativement superieur au taux sans risque de la devise est **le paiement d'un
risque**. Avant d'accepter quoi que ce soit :

1. **Qui paie ce rendement ?**
2. **Avec quel argent ?**
3. **Que se passe-t-il quand ca s'arrete ?**

Anchor, Stream et USDe echouent aux trois, **et le test etait disponible avant l'effondrement**.
Le staking (§2.3) y repond, lui : le protocole paie, avec l'emission de nouveaux jetons prevue par
le consensus, et si ca s'arrete le rendement tombe a zero sans que le principal soit detruit — ce
qui est exactement pourquoi il est a ~1,8 % et pas a 20 %.

Sources : https://www.oecd.org/content/dam/oecd/en/publications/reports/2022/12/lessons-from-the-crypto-winter_37bf4b9e/199edf4f-en.pdf ·
https://financefeeds.com/why-crypto-lenders-fail-lessons-for-investors/ ·
https://reports.tiger-research.com/p/collapse-of-the-defi-jenga-the-stream-eng ·
https://www.coindesk.com/markets/2025/10/11/ethena-s-usde-briefly-loses-peg-during-usd19b-crypto-liquidation-cascade

---

## 6. Synthese — verdict par piste

| Piste | Verdict | Chiffre net | Statut |
|---|---|---|---|
| Diversifier des strategies sans edge | **NON, ca ne cree rien** | esperance lineaire ; les frais s'additionnent aussi | MESURE (math) |
| Diversifier des **classes d'actifs** a esperance positive | **Seule diversification qui compte** | — | DERIVE |
| 1/N (DGU 2009) | Valide, mais condamne surtout `optimizer.py` | 0/14 modeles battent 1/N ; 3 000 mois requis pour 25 actifs | MESURE |
| Rendement stablecoin (Kraken) | **FERMEE** — EEE exclu, MiCA art. 50 | **0 %** accessible en France | MESURE |
| Cash-and-carry / funding | **FERMEE x2** : prime morte + hors mandat spot | Sharpe 6,45 -> 4,06 (2024) -> negatif (2025) ; funding BTC negatif au 28/08/2026 | MESURE |
| **Staking ETH/SOL sur Kraken** | **SEULE PISTE POSITIVE**, marginale | **~1,8 %/an net** (ETH), en ETH, unbonding >= 3 j, fiscalite non tranchee | MESURE (taux, commission) / DERIVE (net) |
| Prime de rebalancement | **NON DEMONTREE** nette de frais | ~18 bps/an brut (actions) vs 80 bps par aller-retour chez nous | MESURE brut / DERIVE net |
| Faber / SMA 10 mois | Reduit le risque, ne cree pas de rendement | +0,6 pt CAGR, -36 pts de DD ; +/-220 bps de bruit de calendrier | MESURE |
| Produits de rendement crypto | **PIEGE, motif identifiable a l'avance** | Anchor, Stream (-90 %), deUSD (-98 %), USDe (0,65 $) | MESURE |

### Conclusion, sans enrobage

L'intuition du proprietaire est bonne sur le principe **et ne change rien au resultat** : diversifier
protege d'une concentration, ca ne fabrique pas d'esperance. Le seul element de ce dossier qui
ameliore reellement le buy & hold dans le perimetre du projet est **le staking**, pour ~1,8 %/an net
sur ETH, en acceptant 3 jours d'illiquidite et une fiscalite francaise non tranchee. Tout le reste
est soit ferme par la reglementation, soit ferme par le mandat spot, soit tue par 0,40 % de frais
par ordre, soit un risque deguise en rendement.

La bonne allocation « plusieurs paniers » ici n'est pas plusieurs strategies crypto : c'est crypto
en buy & hold d'un cote, tresorerie euro remuneree de l'autre, **dans une proportion que seul le
proprietaire peut fixer**. Rappel du garde-fou n°6 : **aucun conseil en investissement
personnalise** ; la decision et le risque appartiennent a l'utilisateur.

---

## 7. Ce qui n'est PAS etabli, et les voies restantes

Un obstacle n'est pas une reponse : chaque point ci-dessous nomme la voie qui reste ouverte.

1. **Taux et eligibilite exacts pour un compte francais.** Les pages Kraken sont geo-adaptees ; la
   page `legal/micar` renvoie a Payward Europe Solutions Ltd (regulee par la Banque centrale
   d'Irlande) **sans enumerer les services restreints**.
   *Voie restante* : lire la grille depuis un compte Kraken FR connecte, ou support Kraken.
2. **Disponibilite du staking pour les residents francais sous MiCAR.** Les pages disent « des
   restrictions geographiques s'appliquent », jamais detaillees. **Non confirme** — tout le §2.3
   suppose que le staking est ouvert en France.
   *Voie restante* : verification depuis un compte FR, ou support Kraken.
3. **Fiscalite francaise du staking** : BNC a la reception contre PFU 30 % a la cession, doctrines
   contradictoires, aucune source primaire ouverte consultee.
   *Voie restante* : BOFIP `BOI-BNC-CHAMP-10-10-20-40` en direct, doctrine 150 VH bis, ou
   fiscaliste.
4. **BIS WP 1087 en texte integral** : `bis.org/publ/work1087.pdf` repond **404**. Les resultats
   qualitatifs sont acquis (carry > 40 % p.a., mecanisme), **pas les tables**.
   *Voies restantes* : SSRN 4268371, la version *Management Science* 2026 (payante),
   EconPapers/RePEc.
5. **Chiffres Faber lus dans le PDF original** : extraction impossible sur cette machine
   (`pdftoppm` absent, les deux PDF sont revenus en binaire). Les chiffres du §4.1 viennent de
   **reproductions tierces concordantes** (CXO Advisory, reproduction R sur GitHub, fil Bogleheads).
   *Voie restante* : installer poppler-utils, ou lire la page SSRN 962461 en HTML.
6. **Prime de rebalancement crypto nette de frais** : introuvable hors contenu promotionnel. Aucune
   etude serieuse chiffrant l'effet a 0,40 % par ordre.
   *Voie restante* : la mesurer nous-memes avec le backtester, sur le meme protocole que le §4.4.
7. **Etude academique sur le timing BTC par SMA 200 j en cadence mensuelle** : n'existe apparemment
   pas en acces libre.
   *Voies restantes* : bases payantes (SSRN full-text, ScienceDirect, *Journal of Alternative
   Investments*). **C'est le trou du dossier, et il est comblable en interne** — protocole au §4.4.
8. **Correlation exacte entre « crypto buy & hold » et « tresorerie euro »** : non mesuree ici,
   supposee tres faible (**SUPPOSE**). C'est l'hypothese sur laquelle repose toute la recommandation
   d'allocation du §1.2 ; elle est plausible mais non verifiee sur donnees.
   *Voie restante* : la mesurer, meme grossierement, avant d'appuyer une decision dessus.

---

*Etude #9 — 2026-09-02. Recherche web uniquement, aucun serveur ni navigateur lance. Aucun commit
effectue par cette etude.*
