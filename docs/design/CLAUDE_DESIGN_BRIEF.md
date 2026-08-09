# Kit de départ — Claude Design pour InsertYourCoin

> Statut : document de travail, **aucun fichier de code touché**.
> Auteur : UX/UI Designer. Date : 2026-08-09.
> Cible : Mandar, dans **claude.ai/design** (navigateur), pour explorer et valider
> des directions visuelles, puis les rapatrier à la main dans l'app Python.
> Références ancrées (lues pour écrire ce document) : `docs/UI_UX_WEBAPP_SPEC.md`
> (spec validée, §8 accessibilité), `docs/mockups/prototype.html` (maquette
> validée = **la référence visuelle**), `docs/audit/AUDIT_WEBAPP_L0-5.md`
> (audit QA, P2 corrigés au Lot 9), `trading/webui.py` (thème réel),
> `trading/*_page.py` + `trading/monitor.py` + `trading/dashboard.py` (écrans réels).

---

## 0. Le constat qui justifie tout ce document (MESURÉ)

Trois mesures faites sur le code, pas des impressions.

1. **`var(--...)` : 0 occurrence dans les 12 fichiers `trading/*_page.py`.**
   Le thème `THEME_CSS` (`trading/webui.py:32-103`) définit bien `--gold`, `--txt`,
   `--serif`, `--mono`… mais **aucune page ne les consomme** : chaque écran réécrit
   ses couleurs en hexadécimal dans son propre bloc `_CSS` (ex.
   `trading/stats_page.py:18-56`, `trading/walkforward_page.py:40-110`).
   Conséquence directe : **changer un token ne change rien**. Toute évolution de
   palette se paie aujourd'hui en N fichiers édités à la main.

2. **`#1f6feb` (bleu) est le bouton primaire dans 10 fichiers**
   (`check_page.py`, `compare_page.py`, `live_page.py`, `monitor.py`,
   `optimize_page.py`, `paper_page.py`, `portfolio_page.py`, `research_page.py`,
   `stats_page.py`, `walkforward_page.py`). Or ce bleu **n'existe dans aucune
   variable du thème**, et la maquette validée dit l'inverse :
   `docs/mockups/prototype.html:140` -> `.btn.primary{background:var(--gold); color:#1a140a; font-weight:600}`.
   L'app a donc un bouton d'action « bleu générique » là où la direction validée
   disait « or sur fond sombre ».

3. **`--serif` n'est utilisé que 2 fois hors définition du thème** :
   `trading/webui.py:61` (le mot-marque de la nav) et `trading/dashboard.py:197/202/209`
   (le Rapport). Les **12 autres écrans n'ont aucun titre serif** : tous en
   `h1 { font-size: 18px }` sans famille déclarée (`home_page.py:18`,
   `walkforward_page.py:43`, `stats_page.py:21`, `paper_page.py:32`, etc.).
   La spec §1.2 disait pourtant « serif pour les titres, monospace pour les
   chiffres ». **Le Rapport de backtest est aujourd'hui le seul écran fidèle à la
   maquette** ; les autres sont une version aplatie — fonctionnelle, mais sans
   hiérarchie.

> Autrement dit : la direction visuelle a été **validée puis perdue en route** sur
> 12 surfaces sur 14. Ce n'est pas un défaut d'exécution des Lots 0-9 (qui ont
> livré le fonctionnel, les garde-fous et l'accessibilité AA) — c'est le travail
> de design qui reste à faire, et c'est exactement ce que Claude Design permet
> d'explorer vite avant de payer une passe de code.

**Ce qui est déjà bon et ne doit PAS être re-designé** (base verrouillée) :
contraste AA atteint après le Lot 9, accents français restaurés, badge IN-SAMPLE
présent sur Backtest / Comparer / Optimiser, Buy & Hold toujours visible, bandeau
verdict walk-forward avec icône + libellé (jamais la couleur seule), mur de
friction du live, états vides rédigés partout.

---

## 1. Comment Claude Design s'articule avec cette app

**Claude Design produit du React dans le navigateur. L'app est du HTML assemblé
en Python (`http.server` stdlib, zéro build JS, offline).** Les deux ne se
branchent pas : on se sert de Claude Design comme d'un **studio de prototypage** —
on y explore une mise en page, une hiérarchie, une densité, on la regarde, on la
valide ou on la jette — puis on **porte à la main** le HTML et le CSS retenus dans
`trading/webui.py` et `trading/*_page.py`. Le React généré est un **moyen de
voir**, jamais un livrable.

**Ce qui se porte bien** (l'essentiel du gain) : mise en page et grilles ·
hiérarchie typographique (tailles, familles, graisses, interlignage) · densité et
rythme vertical · palette et tokens · états dessinés (vide / chargement / erreur /
succès) · micro-copie et libellés · composants statiques (cartes KPI, tableaux,
badges, bandeaux, barres CSS) · alignement des colonnes de chiffres · responsive
par media-query.

**Ce qui NE se porte PAS tel quel** : tout composant React à état client
(accordéons, onglets, modales, drag-and-drop) · les animations complexes ·
toute dépendance npm (Tailwind, shadcn, lucide, framer-motion, recharts) —
l'app est **offline et vendorisée**, Chart.js est le seul JS tiers et il est servi
depuis `/static/chart.umd.min.js` · les polices web (le thème n'utilise que des
piles système) · les icônes d'une librairie (à remplacer par du texte ou un SVG
inline minimal) · tout ce qui exige un build.

**Règle de conversion** : si un écran de Claude Design ne survit pas à
« JavaScript désactivé », il ne se porte pas — sauf sur les surfaces qui ont déjà
du JS assumé (polling du panneau de job, refresh 7 s du monitoring, les deux
`confirm()` de sécurité).

---

## 2. Le bloc de contexte à coller dans Claude Design

> À coller **en tête de chaque conversation** Claude Design, avant le prompt de
> l'écran. C'est ce bloc qui empêche de recevoir un dashboard SaaS générique.

```
CONTEXTE PRODUIT
InsertYourCoin : outil personnel de trading algorithmique crypto (Kraken), en
application web LOCALE auto-hébergée (127.0.0.1), utilisée par une seule
personne, tous les jours. Ce n'est pas un produit commercial et il ne sera
jamais vendu. Le capital engagé est du capital qu'on peut se permettre de
perdre.

DOCTRINE — NON NÉGOCIABLE
1. Honnêteté avant tout. L'UI ne doit JAMAIS rendre un résultat plus flatteur
   qu'il n'est. Concrètement :
   - le WALK-FORWARD (performance hors-échantillon) est LE JUGE : il domine
     visuellement le backtest, jamais l'inverse ;
   - tout résultat de backtest / comparaison / optimisation porte un badge
     "IN-SAMPLE — non validé hors-échantillon" ;
   - la référence Buy & Hold est toujours visible dans les comparaisons ;
   - les frais, le drawdown et la part des frais ne sont jamais masqués, jamais
     relégués en pied de page, jamais en gris pâle ;
   - un verdict négatif s'affiche en grand, au même niveau qu'un verdict
     positif. Pas de "presque", pas de vert d'encouragement.
2. Sécurité par construction. Le mode "live" (argent réel) est délibérément
   PÉNIBLE à atteindre : hors de la navigation principale, pré-requis à cocher,
   deux allers-retours serveur, phrase exacte à taper. La friction est le
   design, pas un défaut à corriger.
3. Clarté > densité. Un écran = un but. Chaque état (vide / en cours / erreur /
   succès) est dessiné.

TON VISUEL
"Terminal de trading" sobre et raffiné : fond sombre chaud, accent OR, titres en
serif, chiffres en monospace. Jamais de ton commercial, jamais de vert
clignotant "GAINS", jamais d'emoji, jamais de dégradé néon. L'inspiration est le
rapport imprimé d'une salle de marché, pas une app crypto grand public.

TOKENS DU THÈME (valeurs réelles, à réutiliser telles quelles)
Fonds       : --bg #0e1116 · --bg-deep #0a0c10 · --panel #171c24 · --panel2 #1b212b
Lignes      : --line #232b36 · --line-gold rgba(214,170,90,.22)
Textes      : --txt #d7dee8 · --muted #7f8c9c · --muted2 #8b97a6
Accent      : --gold #d6aa5a · --gold-bright #f0b429 · --gold-soft rgba(214,170,90,.10)
Sémantique  : --up #46c46f (positif) · --down #e5534b (négatif) · --blue #6cb6ff (liens)
Typo serif  : "Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif
Typo mono   : ui-monospace,"SF Mono",Consolas,"Liberation Mono",Menlo,monospace
Typo sans   : -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif
Fond de page: radial-gradient(1100px 560px at 82% -12%, rgba(214,170,90,.06), transparent 60%),
              radial-gradient(820px 460px at -8% 112%, rgba(70,196,111,.04), transparent 60%),
              #0e1116
Usage : serif pour les titres et les grandes valeurs · monospace pour TOUS les
chiffres (alignement) · sans-serif pour le texte courant et la navigation.
Les couleurs sémantiques ne portent JAMAIS l'information seule : toujours
doublées d'un signe (+/-), d'un mot ou d'une icône texte.

STRUCTURE
Barre de navigation persistante (sticky, 56px, fond rgba(11,13,17,.94)) :
  marque "InsertYourCoin" (le "Your" en or), puis les onglets
  Accueil · Diagnostic · Recherche · Paper · Monitoring · Stats · Options · Aide,
  puis à droite deux pastilles d'état : "Local 127.0.0.1" et "SSL vérif. actif".
  L'onglet actif est en or sur fond --gold-soft.
  "Live" n'est PAS un onglet (friction par l'architecture) : on y accède par un
  lien discret depuis l'Accueil.
Sous-navigation dans Recherche : Backtest · Comparer · Optimiser · Portefeuille ·
  Walk-forward.
Largeur de contenu : max 1160px, centré.

CONTRAINTES TECHNIQUES (impératives)
- Rendu final = HTML + CSS écrits à la main dans du Python. Donne-moi du HTML
  sémantique simple et du CSS PUR (pas de Tailwind, pas de classes utilitaires).
- ZÉRO dépendance externe : pas de CDN, pas de npm, pas de Google Fonts, pas de
  librairie d'icônes. Polices système uniquement. La seule lib autorisée est
  Chart.js, déjà vendorisée localement.
- Doit fonctionner sans JavaScript, sauf deux exceptions existantes (polling
  d'un job de calcul, rafraîchissement du monitoring toutes les 7 s).
- Accessibilité AA obligatoire : contraste >= 4.5:1 pour le texte normal, chaque
  champ a un <label for>, l'anneau de focus natif n'est jamais supprimé, boutons
  >= 40px de haut, information jamais portée par la couleur seule.
- Cible desktop. Responsive de courtoisie jusqu'à la tablette ; les tableaux
  peuvent défiler horizontalement.
- Langue : français, avec les accents.
```

---

## 3. Les 14 surfaces réelles, une par une

> Note honnête : la commande parlait de « 12 écrans ». Le décompte réel est de
> **14 surfaces rendues** (13 pages + le fragment de monitoring). Les voici toutes,
> avec ce qui existe et ce qui mérite d'être amélioré — priorisé, pas catalogué.

### 3.1 Accueil — `/` — `trading/home_page.py`
**But** : savoir en un coup d'œil si tout va bien et où aller.
**Existant** : 4 cartes en grille auto-fit (Diagnostic / Paper / Recherche /
Réglages) + un bandeau d'avertissement pleine largeur. Titres de carte en `h2`
14px majuscules. Liens bleus `#6cb6ff`. La carte Recherche est figée sur
« Aucune analyse lancée » (`home_page.py:100`) — **aucun résultat n'est persisté**,
l'app ne peut donc pas afficher le dernier verdict.
**À améliorer (par ordre)** :
1. **Hiérarchie inexistante** — les 4 cartes ont le même poids visuel alors que
   leurs enjeux sont incomparables (« le paper tourne-t-il ? » vs « les clés
   sont-elles là ? »). Il faut une carte dominante (l'état du paper, la seule
   chose qui change toute seule) et trois cartes de service.
2. **Le titre `Accueil` en 18px sans-serif ne pose aucun ton** — la maquette
   prévoyait un surtitre majuscule or + un titre serif large
   (`prototype.html:95-99`).
3. **La carte Recherche est un état vide permanent** → ✅ **TRANCHÉ (Mandar,
   2026-08-09) : ON PERSISTE** un résumé de la dernière analyse, pour que la carte
   affiche un vrai « dernier walk-forward » (verdict + actifs + date).
   Contraintes d'implémentation (à respecter au port, **tirées du vécu projet**) :
   - résumé **minimal** : kind, verdict, actifs, horodatage, job_id — **aucun
     secret, aucun solde** ;
   - écrit sur le volume de données (`/data`, survit au restart conteneur), en
     **écriture ATOMIQUE** (`.tmp` + `os.replace`, patron `paper_state.json` /
     `live_state.json`) ;
   - ⚠️ **BUG-015 / BUG-016 (`docs/SQA.md`)** : dans ce projet, deux écritures
     concurrentes d'un même fichier d'état ont déjà produit un P0 et un P2
     (TOCTOU sur `ThreadingHTTPServer`). Ce résumé étant écrit à la fin de jobs
     de recherche, l'écriture doit être **sérialisée** (verrou) ou strictement
     atomique-dernier-gagne assumé — jamais une lecture-modification-écriture non
     protégée ;
   - l'affichage **préserve la sévérité** du verdict : un « PAS D'EDGE FIABLE »
     reste rouge et lisible sur l'Accueil (on n'affiche pas que les bonnes
     nouvelles — doctrine d'honnêteté).
   Le design peut supposer la carte REMPLIE, mais doit **aussi** dessiner l'état
   vide (avant toute première analyse).
4. Le lien « passer en live » est correctement discret — **ne pas le rendre plus
   visible**.

### 3.2 Diagnostic — `/check` — `trading/check_page.py`
**But** : équivalent de `main.py check` (versions installées + test de connexion).
**Existant** : carte « Installation » (bloc monospace), carte « Connexion Kraken »
avec formulaire GET + résultat coloré par catégorie (`ok-cat` vert / `ssl` ambre /
`network` rouge). État neutre honnête (« Diagnostic non lancé cette session »).
**À améliorer** : peu de choses. (a) le bloc de versions est un pavé séparé par
`<br>` qui mériterait un tableau clé/valeur ; (b) le message d'erreur SSL est le
plus important de l'app en cas de panne — il devrait ressembler à une fiche
d'action (cause / geste à faire) plutôt qu'à un paragraphe. **Priorité basse** :
cet écran fait son travail.

### 3.3 Monitoring — `/monitoring` + fragment `/fragment` — `trading/monitor.py`
**But** : suivre le paper trading EN DIRECT. **C'est l'écran regardé tous les jours.**
**Existant** : 7 cartes KPI identiques en grille `minmax(130px,1fr)` (Statut,
Prix, Equity, P&L, Drawdown, Exposition, Cycles), tableau des 8 derniers ordres,
journal monospace de 40 lignes, alerte d'inactivité au-delà de 360 s, horodatage
« Dernière maj … (auto-refresh 7s) ».
**À améliorer (par ordre)** :
1. **Sept cartes de poids strictement égal.** Le regard quotidien cherche deux
   choses — *est-ce que ça tourne encore ?* et *où en est mon capital ?* — et doit
   les extraire d'une rangée de sept tuiles jumelles. Il faut une **zone primaire**
   (Statut + Equity + P&L) et une **zone secondaire** dense (Prix, Drawdown,
   Exposition, Cycles).
2. **Aucun sens de la durée** : pas de courbe d'equity, pas de « depuis N heures »,
   pas de tendance. Or c'est précisément un écran qu'on regarde *sur la durée*.
3. **Le journal occupe autant de place que les chiffres** alors qu'il est le
   dernier recours en cas de doute.
4. L'alerte d'inactivité est bonne (rouge + texte explicite) — la garder telle quelle.

### 3.4 Paper — `/paper` — `trading/paper_page.py`
**But** : configurer, démarrer et arrêter le paper trading.
**Existant** : carte Statut (EN COURS depuis … / ARRÊTÉ) puis, si arrêté, le
formulaire complet (stratégie, symbole, timeframe, stop, objectif, trailing,
sizing, vol cible) + bouton. Note d'honnêteté sur l'historique conservé. Mode
« pilotage désactivé » (déploiement conteneurisé) bien géré.
**À améliorer** : (a) **le formulaire à 8 champs est servi à plat**, sans
regroupement *marché* / *risque*, alors que ce sont deux décisions de nature
différente ; (b) **aucune valeur par défaut n'est expliquée** — pourquoi 5 % de
stop, 8 % de trailing ? Un mot par champ éviterait de les changer au hasard ;
(c) la transition ARRÊTÉ -> EN COURS est un rechargement sec, sans état
intermédiaire dessiné.

### 3.5 Labo de stats — `/stats` — `trading/stats_page.py`
**But** : synthèse descriptive du CSV accumulé par le paper.
**Existant** : sélecteur de fichier, période, 8 cartes KPI (dont la carte
« Frais » volontairement en ambre), deux blocs de mini-barres CSS (par heure, par
jour) et un encart d'honnêteté dérivé de `config.FEE`.
**À améliorer (par ordre)** :
1. **Les barres heure/jour mesurent la mauvaise chose** : 24 lignes puis 7 lignes,
   largeur proportionnelle au **nombre de cycles** — or ce nombre est quasi
   constant pour un bot. Ce qui intéresse, c'est le résultat ou l'activité de
   trading par créneau, pas le nombre de passages.
2. **8 cartes de même poids.** La carte Frais est distinguée (bien), mais
   Rendement, Drawdown max et PnL devraient dominer le reste.
3. L'encart d'honnêteté est un `<p>` en `white-space: pre-wrap` de texte CLI
   recopié — à mettre en forme **sans en changer un mot**.

### 3.6 Recherche / Backtest — `/research/backtest` — `trading/research_page.py`
**But** : lancer un backtest, qui produit un Rapport.
**Existant** : sous-nav Recherche, formulaire (stratégie, symbole, timeframe,
jours, source Kraken/Binance, bloc risque), bouton, puis panneau de job async.
Note d'honnêteté IN-SAMPLE sous le formulaire.
**À améliorer** : (a) même formulaire à plat que Paper — les blocs *Marché* /
*Source* / *Risque* de la spec §4.0 existent conceptuellement mais pas
visuellement ; (b) la note d'honnêteté est **sous** le bouton, donc lue après
l'action ; (c) le bouton Annuler du panneau de job mesure ~33 px de haut, sous la
cible de 40 px que la spec se fixe (audit §2.6).

### 3.7 Recherche / Comparer — `/research/compare` — `trading/compare_page.py`
**But** : classer toutes les stratégies sur le même jeu de données.
**Existant** : tableau + **ligne Buy & Hold dédiée** + badge IN-SAMPLE + callout
automatique « 0 stratégie ne bat Buy & Hold » quand c'est le cas.
**À améliorer** : le tableau est la bonne réponse et le garde-fou Buy & Hold est
exemplaire. Reste : (a) **séparer visuellement la ligne Buy & Hold du classement**
(c'est une référence, pas un concurrent) ; (b) alignement et graisse des colonnes
chiffrées ; (c) le tri par clic sur en-tête annoncé en spec §4.4 exigerait du JS —
à trancher, probablement à abandonner.

### 3.8 Recherche / Optimiser — `/research/optimize` — `trading/optimize_page.py`
**But** : chercher des paramètres avec séparation train/test.
**Existant** : deux panneaux Train (in-sample) / Test (hors-échantillon), le Test
distingué par une bordure or, encart « surapprentissage probable » si le test
s'effondre, badge IN-SAMPLE (`optimize_page.py:307`).
**À améliorer** : l'intention honnête est là, mais **la domination du Test n'est
qu'une bordure** — en lecture rapide, les deux panneaux se ressemblent. Le Test
doit être d'un autre ordre (taille, position, poids), pas d'une autre couleur de
trait.

### 3.9 Recherche / Portefeuille — `/research/portfolio` — `trading/portfolio_page.py`
**But** : panier multi-actifs équipondéré + corrélation.
**Existant** : KPI agrégés, **heatmap de corrélation en HTML/CSS pur** (pas de
lib), note honnête au-delà de 0,7 (« la diversification lisse, ne protège pas d'un
krach systémique »), liste explicite des actifs non chargés.
**À améliorer** : la heatmap est le bon geste ; il lui manque une **légende
d'échelle** et un traitement du cas « toutes les cases sont rouges », qui est le
cas normal en crypto et qui devrait être commenté visuellement.

### 3.10 Recherche / Walk-forward — `/research/walkforward` — `trading/walkforward_page.py`
**But** : **LE JUGE.** Optimisation glissante hors-échantillon, holdout sacré,
validation finale unique.
**Existant** : le formulaire le plus riche de l'app (symboles multiples, fenêtres,
train-frac, métrique, paramètres FIGÉS, holdout %, case VALIDATION FINALE avec
`confirm()`), un **bandeau verdict** (icône + libellé + détail, vert/ambre/rouge,
22px gras), l'état du holdout, une carte par actif avec table des fenêtres, et un
`<details>` pédagogique « Pourquoi le walk-forward est le juge ».
**À améliorer (par ordre)** :
1. **Le bandeau verdict est censé être « l'élément le plus visible de TOUTE
   l'app » (spec §4.6). Il fait 22px** (`walkforward_page.py:78`). Le titre `h1`
   du Rapport de backtest, lui, monte à 52px (`dashboard.py:197`). **Le juge est
   typographiquement plus petit que ce qu'il juge** — c'est l'inversion la plus
   grave de l'app.
2. **Le formulaire fait peur** : 12 champs dont trois notions expertes
   (train-frac, paramètres figés, holdout sacré) sans explication en ligne. Qui ne
   comprend pas le holdout ne le mettra pas — et perdra la seule garantie
   anti-data-mining.
3. La case VALIDATION FINALE est correctement dangereuse — **ne pas l'adoucir**.
4. Les cartes par actif empilent des tables denses sans ligne de synthèse.

### 3.11 Rapport — `/report/<job_id>` — `trading/report_page.py` + `trading/dashboard.py`
**But** : le résultat riche d'un backtest (KPI, courbe de capital, drawdown,
comparaison, derniers trades).
**Existant** : **le seul écran fidèle à la maquette** — palette chaude propre
(`--bg #14110c`), titre serif `clamp(30px,5vw,52px)`, cartes KPI en dégradé, `h2`
avec filet, 3 graphiques Chart.js vendorisés avec dégradation propre si absent,
footer d'avertissement. Précédé du badge IN-SAMPLE avec lien vers le walk-forward.
**À améliorer** : quasiment rien sur le fond — c'est la **référence interne**.
Deux points : (a) sa palette diverge de celle de la nav qui l'entoure (fond
`#14110c` chaud sous une nav `#0e1116` froide) — assumé et scopé
(`dashboard.py:171-184`) → ✅ **TRANCHÉ (Mandar, 2026-08-09) : ON ALIGNE** la
palette du Rapport sur celle de l'application (un seul univers visuel, pas un
« document dans une coquille »). **Sens de l'alignement — important** : le Rapport
est la **référence de qualité** (seul écran fidèle à la maquette validée) ; on
aligne donc sa **palette de fond** sur le thème global, **sans dégrader** sa
typographie serif, ses titres à filet, ses cartes KPI ni sa hiérarchie — et c'est
au contraire **ce vocabulaire-là qu'on propage aux 13 autres écrans**. Contrainte
technique : son CSS est aujourd'hui **scopé** (`.report-body`, cf. `dashboard.py`)
pour ne pas fuiter dans la coquille — cet isolement doit être **préservé** au port
(un correctif de fuite CSS a déjà été nécessaire au Lot 4) ; (b) le badge IN-SAMPLE
reste discret face à un titre de 52px.

### 3.12 Options — `/options` — `trading/monitor.py:522`
**But** : niveau de logs, liaison Kraken (clés), wallet lien-only, arrêt/redémarrage
du serveur web.
**Existant** : 4 cartes empilées, champs `type=password` avec placeholders
neutres, état booléen « Clés configurées : OUI/NON » (jamais la valeur), aide
insistante « JAMAIS Withdraw Funds », wallet en lien sortant, boutons serveur avec
confirmation.
**À améliorer** : (a) les 4 cartes sont de nature très différente (préférence /
secret / lien externe / action système) et se ressemblent toutes — la carte
« Serveur web » porte une action d'arrêt et ressemble à la carte « Niveau de
logs » ; (b) l'avertissement Withdraw est un `<p class='help'>` gris 12px alors
que c'est **la consigne de sécurité la plus importante de l'app**.

### 3.13 Aide — `/help` — `trading/help_page.py`
**But** : ordre de travail, rappel SSL/antivirus, avertissement risque, lien SETUP.
**Existant** : 4 cartes de texte, dont une carte « risque » distinguée.
**À améliorer** : c'est de la documentation servie comme une page de réglages.
L'« ordre de travail recommandé » (backtest -> walk-forward -> paper -> live) est
la seule chose qu'on lira vraiment ici : il mérite un traitement en étapes
numérotées lisibles. **Priorité basse.**

### 3.14 Live — `/live` — `trading/live_page.py`
**But** : le mur de friction. Argent réel.
**Existant** : bandeau rouge permanent, pré-requis avec pastilles OK/manquant,
plafonds `config.py` affichés, sélecteur de mode **décoratif et désactivé**, deux
formulaires **séparés** (dry-run / RÉEL), 3 attestations à cocher, bouton RÉEL
désactivé côté serveur, puis un écran de récapitulation servi par le serveur avec
phrase exacte à taper. En cours : bandeau ROUGE ou AMBRE selon le mode, bouton
« Arrêter immédiatement », journal.
**À améliorer** : **très peu, et avec précaution.** La friction est le design
(`docs/design/LOT8_LIVE_SPEC.md` §1.1) et cet écran a passé une gate indépendante.
Seul vrai gain : **rendre les plafonds et le mode en cours lisibles d'un mètre**
(aujourd'hui `Ordre max : 100 $` est du texte 13px au milieu d'une carte). Tout le
reste — nombre d'étapes, cases, phrase exacte — est **intouchable**.

---

## 4. Top 5 priorisé + prompts prêts à coller

Priorisation sur l'usage réel et sur la doctrine, pas sur la surface à repeindre.

| # | Écran | Pourquoi en priorité | Gain attendu |
|---|---|---|---|
| 1 | **Monitoring** `/monitoring` | Regardé tous les jours ; 7 tuiles jumelles, aucune notion de durée | lire l'état du bot en 3 secondes au lieu de 7 chiffres à balayer |
| 2 | **Walk-forward** `/research/walkforward` | Le juge (22px) est plus petit que ce qu'il juge (52px) | le verdict redevient l'élément le plus imposant de l'app |
| 3 | **Accueil** `/` | Première chose vue à chaque lancement ; 4 cartes de poids égal | savoir en un coup d'œil si le paper tourne, et poser le ton |
| 4 | **Labo de stats** `/stats` | Les barres mesurent la mauvaise chose ; 8 KPI indifférenciés | voir enfin ce que coûtent les frais et quand ça trade |
| 5 | **Rapport de backtest** `/report/<id>` | La référence à préserver | en extraire la bibliothèque de composants pour les 13 autres |

> Le Rapport est classé 5 **exprès** : c'est le seul écran réussi. On l'ouvre en
> dernier, et surtout pour en **extraire le vocabulaire visuel**, pas pour le refaire.

---

### PROMPT 1 — Monitoring (le quotidien)

```
[coller d'abord le BLOC DE CONTEXTE de la section 2]

ÉCRAN À TRAVAILLER : Monitoring du paper trading (page consultée tous les jours,
en arrière-plan, souvent en un coup d'œil de 3 secondes).

CE QUI EXISTE AUJOURD'HUI
- Un horodatage "Dernière maj : 2026-08-09 14:03:12 (auto-refresh 7s)".
- Une rangée de 7 cartes rigoureusement identiques (grille auto-fit, minmax
  130px) : Statut (CASH ou INVESTI), Prix (3120.50), Equity (10042.31),
  P&L (+42.31 (+0.42%)), Drawdown (3.10%), Exposition (0%), Cycles (947).
- Un tableau "Derniers ordres" : Heure | Sens (BUY/SELL) | Prix | Motif,
  8 lignes maximum.
- Un bloc "Journal" : 40 dernières lignes en monospace, les lignes contenant
  "erreur"/"echec" en rouge.
- Une alerte rouge "ATTENTION : aucun cycle depuis 412s (paper inactif ?)"
  quand plus de 360 s se sont écoulées.
- Un état vide : "En attente de données du paper..." + une phrase explicative.

OBJECTIF
Donner une hiérarchie de lecture à trois niveaux :
1. PRIMAIRE, lisible d'un mètre : le paper tourne-t-il, et où en est le capital
   (Statut, Equity, P&L) — grande typo serif, chiffres en monospace.
2. SECONDAIRE, dense et compact : Prix, Drawdown, Exposition, Cycles.
3. TERTIAIRE, consultable à la demande : les ordres et le journal.
Ajoute une notion de DURÉE : cet écran se regarde sur des semaines et ne montre
aujourd'hui qu'un instantané. Propose une représentation de l'évolution de
l'equity réalisable en HTML/CSS pur ou avec Chart.js (déjà disponible) — pas une
librairie de plus.

DESSINE AUSSI LES ÉTATS
- état vide (paper jamais lancé),
- état inactif (alerte >360s : elle doit rester impossible à rater),
- état "aucun ordre pour l'instant".

CE QU'IL NE FAUT PAS CHANGER
- Le drawdown et le P&L négatif restent affichés en clair, jamais adoucis,
  jamais masqués derrière un onglet.
- L'alerte d'inactivité garde sa sévérité (couleur + texte explicite).
- Pas d'objectif de gain, pas de barre de progression vers un but, pas de
  félicitations : cet écran informe, il n'encourage pas.
- Le contenu est remplacé par un fragment HTML toutes les 7 s : ne propose rien
  qui exige un état client conservé entre deux rafraîchissements (pas
  d'accordéon ouvert/fermé, pas d'onglets, pas d'animation en cours).
```

---

### PROMPT 2 — Walk-forward (le juge)

```
[coller d'abord le BLOC DE CONTEXTE de la section 2]

ÉCRAN À TRAVAILLER : Walk-forward — la validation hors-échantillon. C'est LE
JUGE du produit : c'est lui qui dit si une stratégie a un edge réel, et sa
réponse est très souvent NON.

CE QUI EXISTE AUJOURD'HUI
1. Un formulaire de 12 champs : stratégie, symboles (liste séparée par des
   virgules), timeframe, jours, source (Binance recommandé par défaut, ou
   Kraken), fenêtres (4), train-frac (0.5), métrique
   (sharpe/sortino/calmar/total_return/profit_factor), "Paramètres FIGÉS
   (anti-data-mining, recommandé)" en texte libre "fast=50,slow=200",
   "Holdout sacré (%)" (20), une case à cocher "VALIDATION FINALE (1 seule fois
   par stratégie !) — consomme le holdout", puis stop / objectif / trailing.
2. Un bandeau de verdict après calcul, actuellement en 22px gras :
     "✗ VERDICT : PAS D'EDGE FIABLE   (0 / 4 actifs OOS positifs)"
   trois tonalités : vert "EDGE PLAUSIBLE", ambre "FRAGILE / MITIGÉ" ou
   "SUR-APPRENTISSAGE PROBABLE" ou "INDÉCIDABLE", rouge "PAS D'EDGE FIABLE" /
   "NE PAS TRADER".
3. Un bloc d'état du holdout : "Holdout sacré : NON consommé" ou, après
   validation finale, un verdict par actif.
4. Une carte par actif : nom, OOS cumulé, % de fenêtres profitables, PSR/DSR,
   puis un tableau des fenêtres (période hors-échantillon, paramètres retenus,
   métrique, rendement, drawdown max).
5. Un bloc dépliable "Pourquoi le walk-forward est le juge".

OBJECTIF
1. LE VERDICT DOIT DEVENIR L'ÉLÉMENT LE PLUS IMPOSANT DE TOUTE L'APPLICATION.
   Aujourd'hui il fait 22px alors que le titre d'un simple rapport de backtest
   monte à 52px : le juge est plus petit que ce qu'il juge. Corrige cette
   inversion. Le verdict doit rester aussi imposant quand il est NÉGATIF que
   quand il est positif — c'est le point le plus important de ce prompt.
2. Rends le formulaire enseignable : regroupe-le en blocs nommés (Quoi tester /
   Comment découper / Le segment sacré / Le risque), et prévois pour trois
   notions une explication courte en ligne, SANS JavaScript :
   - train-frac : la part de chaque fenêtre utilisée pour régler avant de tester,
   - paramètres figés : on impose les réglages au lieu de les chercher, ce qui
     empêche de fabriquer un bon résultat par tâtonnement,
   - holdout sacré : une portion récente des données mise de côté, à n'utiliser
     qu'UNE fois, en toute fin.
3. Donne une ligne de synthèse par actif avant son tableau détaillé.

DESSINE AUSSI LES ÉTATS
- calcul en cours (c'est le plus long de l'app : plusieurs minutes),
- verdict rouge, verdict ambre, verdict vert,
- "actif non chargé (données indisponibles)",
- holdout non consommé vs holdout consommé.

CE QU'IL NE FAUT PAS CHANGER
- La case VALIDATION FINALE doit rester visiblement dangereuse et rébarbative.
- Les tonalités portent TOUJOURS une icône texte et un libellé écrit : jamais
  la couleur seule.
- N'ajoute aucun encouragement, aucune reformulation positive d'un verdict
  négatif, aucun "essayez avec d'autres paramètres" : la conclusion honnête
  d'un walk-forward raté est qu'il n'y a pas d'edge, point.
```

---

### PROMPT 3 — Accueil

```
[coller d'abord le BLOC DE CONTEXTE de la section 2]

ÉCRAN À TRAVAILLER : Accueil / hub d'état. Première page vue à chaque lancement
de l'application (double-clic sur un raccourci -> navigateur).

CE QUI EXISTE AUJOURD'HUI : quatre cartes strictement identiques en grille, plus
un bandeau d'avertissement pleine largeur.
- Diagnostic : "[OK] Connexion Kraken OK (ETH/USD = 3120.50, vérifié à 14:02)"
  + "[OK] truststore actif (SSL de l'OS)" + lien "Lancer le diagnostic".
- Paper trading : "Statut : INVESTI" + "Equity 10 042.31$ (P&L +42.31$ (+0.42%))"
  + lien "Voir le monitoring". Ou, si rien ne tourne : "Aucun paper en cours".
- Recherche : "Aucune analyse lancée." + lien "Nouvelle analyse". (L'application
  ne conserve aucun résultat entre deux redémarrages : cet état vide est
  permanent aujourd'hui.)
- Réglages : "Clés Kraken configurées : OUI/NON" + liens Options, Aide, et un
  lien volontairement DISCRET "passer en live".
- Bandeau : "Avertissement : outil de recherche. Aucun gain promis. Le live
  engage de l'argent réel — il est verrouillé par défaut."

OBJECTIF
1. Hiérarchiser : l'état du paper trading est la seule information qui change
   toute seule et la seule qu'on vient vraiment consulter. Elle doit dominer.
   Diagnostic, Recherche et Réglages sont des points d'entrée de service.
2. Poser le ton dès la première seconde : aujourd'hui le titre est un "Accueil"
   de 18px sans caractère. Propose une en-tête qui installe l'identité
   (surtitre en majuscules espacées couleur or + titre serif large), sans verser
   dans la page d'accueil marketing.
3. Traiter l'état vide de la carte Recherche comme un vrai design, pas comme un
   trou : par exemple rappeler l'ordre de travail honnête
   backtest -> walk-forward -> paper -> live.

DESSINE AUSSI LES ÉTATS
- tout vert (connexion OK, paper en cours),
- diagnostic en échec (SSL intercepté par un antivirus : c'est le cas de panne
  réel de cette machine),
- aucun paper en cours,
- clés Kraken absentes.

CE QU'IL NE FAUT PAS CHANGER
- Le lien "passer en live" reste DISCRET, en bas d'une carte secondaire. Ne le
  transforme jamais en bouton d'action mis en avant : sa discrétion est une
  mesure de sécurité délibérée.
- Le bandeau d'avertissement reste présent et lisible, jamais réduit à une
  mention en pied de page.
- Aucun chiffre de performance mis en avant façon "vitrine".
```

---

### PROMPT 4 — Labo de stats

```
[coller d'abord le BLOC DE CONTEXTE de la section 2]

ÉCRAN À TRAVAILLER : Labo de stats — synthèse DESCRIPTIVE des cycles accumulés
par le paper trading (lecture d'un fichier CSV). Ce n'est pas une preuve de
performance, et l'écran le dit lui-même.

CE QUI EXISTE AUJOURD'HUI
- Un sélecteur de fichier CSV et une ligne "Période : 2026-07-01 08:12:00 →
  2026-08-09 14:03:12".
- Huit cartes KPI identiques : Cycles (947), Rendement (+0.42%), Drawdown max
  (3.10%), Trades (18 (9 achats / 9 ventes)), Réussite (44%), PnL total
  (+42.31), "Frais (part du |pnl|+frais)" (974.77 (~45%)) — celle-ci en ambre,
  Exposition moy. (37%).
- Deux blocs de mini-barres CSS : "Par heure (cycles / trades)" (24 lignes) et
  "Par jour (cycles / trades)" (7 lignes). La longueur de barre est
  proportionnelle au NOMBRE DE CYCLES.
- Un encart "Honnêteté" en texte préformaté, rappelant que ces statistiques sont
  descriptives et que les frais pèsent lourd sur les petites unités de temps.

OBJECTIF
1. La carte des FRAIS est la plus importante de l'écran (sur cette machine les
   frais représentent une part énorme du résultat). Elle est distinguée par une
   couleur, ce qui ne suffit pas : donne-lui un vrai statut de premier plan.
   Idem pour le Drawdown max et le Rendement.
2. Les mini-barres mesurent la mauvaise chose : le nombre de cycles par heure est
   quasi constant pour un bot, donc 24 barres presque égales n'apprennent rien.
   Propose une représentation qui montre ce qui varie réellement selon l'heure et
   le jour (activité de trading et résultat), toujours en HTML/CSS pur, sans
   librairie. Prévois explicitement le cas "presque aucune donnée sur ce créneau".
3. L'encart d'honnêteté est un pavé de texte de terminal recopié tel quel :
   mets-le en forme SANS en modifier un seul mot.

DESSINE AUSSI LES ÉTATS
- aucune donnée ("Aucune donnée de stats. Lance d'abord du paper trading pour
  accumuler des cycles."),
- très peu de trades (moins de 10) : le doute statistique doit être visible,
- un seul fichier disponible (le sélecteur disparaît, seul le nom reste).

CE QU'IL NE FAUT PAS CHANGER
- La part des frais reste affichée en clair et en évidence.
- L'encart d'honnêteté ne peut être ni raccourci, ni reformulé, ni replié par
  défaut.
- Aucun classement, aucun score, aucune note globale : ce sont des statistiques
  descriptives, pas un bulletin.
```

---

### PROMPT 5 — Rapport de backtest (extraire, pas refaire)

```
[coller d'abord le BLOC DE CONTEXTE de la section 2]

ÉCRAN À TRAVAILLER : Rapport de backtest. ATTENTION — c'est le SEUL écran de
l'application qui respecte la direction visuelle validée. Il sert de RÉFÉRENCE.
L'objectif n'est PAS de le refaire, mais (a) de corriger deux points précis et
(b) d'en extraire un vocabulaire visuel réutilisable ailleurs.

CE QUI EXISTE AUJOURD'HUI, ET QUI EST BON
- Palette chaude propre au rapport : fond #14110c, panneaux #1d1913 en léger
  dégradé, filets rgba(214,170,90,.16), or #d6aa5a, positif #6fbf8a, négatif
  #df6a4f, texte #ece4d4.
- Surtitre "TABLEAU DE BORD · BACKTEST" en majuscules très espacées, couleur or.
- Titre serif de clamp(30px, 5vw, 52px) : "ETH/USD · Croisement de moyennes".
- Sous-titre "ETH/USD — 1d — 2024-08-01 → 2026-08-01" + une pastille de risque
  "stop −8% · trailing 5% · objectif +20%".
- 10 cartes KPI (rendement total, annualisé, vs Buy & Hold, Sharpe, Sortino,
  drawdown max, profit factor, taux de réussite, nb de trades, temps investi),
  valeurs en serif 27px.
- Titres de section serif 21px suivis d'un filet horizontal qui remplit la ligne.
- Trois graphiques Chart.js : courbe de capital avec Buy & Hold en pointillés,
  drawdown, comparaison des stratégies en barres.
- Tableaux alignés à droite, pastilles de motif de sortie (stop / objectif /
  signal / ouvert).
- Un pied de page d'avertissement.
- Juste au-dessus du rapport, un bandeau ambre : "IN-SAMPLE — non validé
  hors-échantillon. De bons chiffres passés ne garantissent jamais le futur." +
  "Le walk-forward est le juge — lance-le ici".

LES DEUX SEULS POINTS À CORRIGER
1. Le bandeau IN-SAMPLE est écrasé par un titre de 52px juste en dessous. Or ce
   bandeau est la seule chose qui empêche de prendre un beau backtest pour une
   preuve. Donne-lui le poids qu'il mérite — sans casser la sobriété du rapport,
   et sans le transformer en alerte agressive qu'on apprendra à ignorer.
2. Ce rapport est encastré dans une coquille de navigation à la palette plus
   froide (fond #0e1116). Propose les deux options et recommande-en une :
   (a) aligner la palette du rapport sur celle de l'application,
   (b) assumer le contraste "document imprimé dans une coquille d'outil" et le
   marquer franchement (marge, cadre, changement de fond net).

TROISIÈME DEMANDE — EXTRACTION
À partir de cet écran, donne-moi une petite bibliothèque de composants
réutilisables (HTML + CSS pur, sans dépendance) que je pourrai propager aux
autres écrans, qui sont eux beaucoup plus plats : en-tête de page (surtitre +
titre serif + sous-titre), carte KPI, titre de section avec filet, tableau de
chiffres, pastille/badge, bandeau d'avertissement. Nomme les classes de manière
neutre et réutilisable.

CE QU'IL NE FAUT PAS CHANGER
- Buy & Hold reste tracé sur la courbe de capital, en pointillés, toujours
  visible.
- Le drawdown garde son graphique dédié : il n'est jamais réduit à un chiffre.
- Le pied de page d'avertissement reste intégral.
- Les graphiques doivent continuer à se dégrader proprement en message texte si
  Chart.js n'est pas chargé.
```

---

## 5. Grille d'acceptation du port

Un design revenu de Claude Design est **accepté** si les 8 lignes sont vertes.
Une seule ligne rouge = on ne porte pas, on renvoie une itération.

| # | Critère | Comment on vérifie |
|---|---|---|
| A1 | **Tokens respectés** | Toutes les couleurs sont des valeurs de `THEME_CSS` (`--bg`, `--panel`, `--txt`, `--muted`, `--gold`, `--up`, `--down`, `--blue`) ou une teinte dérivée assumée et nommée. Aucune couleur inventée sans justification. |
| A2 | **Zéro dépendance externe** | Recherche de `http://`, `https://`, `cdn`, `fonts.googleapis`, `@import` dans le CSS proposé -> **0 résultat**. Aucune classe Tailwind, aucun composant de librairie. |
| A3 | **Contraste AA** | Chaque paire texte/fond calculée (formule WCAG, pas à l'œil) : >= 4.5:1 en texte normal, >= 3:1 en grand texte. Attention aux `opacity` : c'est la couleur **rendue** qui compte — c'est ce qui avait fait tomber `--muted2` à 2,08:1 dans l'audit L0-5 §2.1. |
| A4 | **Honnêteté préservée** | Badge IN-SAMPLE, référence Buy & Hold, drawdown, part des frais, verdict négatif et bandeaux d'avertissement sont **au moins aussi visibles qu'avant**. Aucun élément honnête n'a été replié, grisé, déplacé en pied de page ou reformulé positivement. |
| A5 | **Tous les états dessinés** | Vide, en cours, erreur, succès — plus les états spécifiques listés dans le prompt de l'écran. Un état manquant = port refusé (c'est la régression classique : on repeint le happy path). |
| A6 | **Rendu sans JS** | Le HTML se lit et s'utilise avec JavaScript désactivé. Exceptions tolérées, déjà existantes : polling du panneau de job, refresh 7 s du monitoring, `confirm()` de la validation finale, `confirm()` de l'arrêt serveur. Toute nouvelle exigence JS = refus. |
| A7 | **Accessibilité de formulaire** | Chaque `input`/`select` a un `<label for>` apparié (ou est enveloppé par son label) ; aucun `outline:none` ; boutons >= 40 px de haut (la spec §8 se fixe ce seuil, l'audit avait mesuré 33 à 39 px — c'est l'occasion de le corriger). |
| A8 | **Aucune régression fonctionnelle** | Mêmes champs, mêmes `name=`, mêmes `action=`, jeton CSRF conservé dans chaque formulaire POST, mêmes liens, mêmes messages d'erreur au mot près. Le design change la forme, jamais le contrat. |

**Deux refus automatiques, sans discussion** :
- un design qui rend un résultat plus flatteur qu'il n'est (A4) ;
- un design qui touche au nombre d'étapes, aux attestations ou à la phrase exacte
  de l'écran Live.

---

## 6. Procédure de port (ce que je ferai, moi, Claude Code)

Un écran validé se rapatrie en **6 temps**, un écran à la fois, jamais deux.

**0. Verrouiller la base.** `git status` propre, `pytest` vert (593 tests au
dernier compte). On note le nombre exact : c'est la baseline de non-régression.

**1. Cadrer le port en une phrase.** « Je porte la mise en page et la typographie
de l'écran X, sans toucher aux `name=`, aux routes ni aux textes d'honnêteté. »
Si la phrase s'allonge, c'est du creep : on retire.

**2. Extraire le CSS, pas le React.** Du livrable Claude Design je ne prends que
la structure HTML et le CSS. Toute classe utilitaire est convertie en règle CSS
nommée. Tout composant à état est rendu statique ou abandonné.

**3. Décider où va le CSS — c'est LA décision du port.** Trois cas :
- **partagé** (en-tête de page, carte KPI, tableau de chiffres, badge, bandeau) ->
  `trading/webui.py`, dans `THEME_CSS`, servi à toutes les pages par
  `page_shell()`. **C'est ici que se règle le problème n°1 du §0** : à mesure que
  des composants montent dans le thème, les blocs `_CSS` locaux rétrécissent et
  les tokens redeviennent effectifs ;
- **spécifique à un écran** -> le bloc `_CSS` du `*_page.py` concerné, en
  **consommant `var(--...)`** au lieu de réécrire des hex ;
- **propre au Rapport** -> `trading/dashboard.py`, dans le scope `.report-body`
  (ne jamais remonter ses variables au niveau racine : elles écraseraient la nav —
  c'est déjà documenté `dashboard.py:171-177`).

**4. Éditer, une page à la fois.** Les fonctions de rendu sont **pures** (aucune
I/O) : je change le HTML produit, jamais la signature ni les paramètres. Les
textes d'honnêteté et les messages d'erreur sont **recopiés au caractère près**
(plusieurs viennent d'une source unique partagée avec la CLI, comme
`stats.honesty_note()` — les diverger recréerait le bug P2 corrigé au Lot 9).

**5. Gate SQA, dans cet ordre** :
- `pytest` -> **le même nombre de tests verts qu'à l'étape 0**, zéro échec ;
- les tests de rendu existants passent tels quels — s'ils cassent sur du texte,
  c'est que j'ai modifié un contrat : je reviens en arrière ;
- **je lance le serveur et je regarde moi-même** l'écran porté **et ses deux
  voisins** dans la nav (toute modification de `THEME_CSS` touche les 14 surfaces) ;
- je repasse la grille §5, ligne par ligne, sur le **rendu réel**, pas sur la maquette ;
- Live et Options : je vérifie en plus qu'aucun jeton CSRF, aucune attestation et
  aucun plafond n'a bougé.

**6. Journaliser.** Une ligne dans `docs/SQA.md` si un défaut est trouvé au
passage ; mise à jour de `docs/UI_UX_WEBAPP_SPEC.md` si le design retenu s'écarte
de la spec validée (la spec est la référence : elle se modifie explicitement, elle
ne se contredit pas en silence).

**Ordre de port recommandé** : d'abord la **bibliothèque de composants** issue du
prompt 5 (elle monte dans `THEME_CSS` et profite à tout le monde), puis Monitoring,
puis Walk-forward, puis Accueil, puis Stats. Un port par session, gate complète
entre chaque.

---

## 7. Ce qui ne sera PAS portable — dit franchement

- **Tout composant React à état** : onglets, accordéons, modales, tooltips riches
  au survol, tableaux triables côté client, filtres dynamiques. L'app n'a pas de
  framework et n'en aura pas. (Conséquence concrète : le « tri par clic sur
  en-tête » prévu en spec §4.4 pour l'écran Comparer reste non réalisable à coût
  raisonnable.)
- **Tailwind et toute classe utilitaire** : le CSS est écrit à la main dans des
  chaînes Python. Un rendu Tailwind doit être retraduit intégralement.
- **Toute librairie npm** : shadcn/ui, lucide-react, framer-motion, recharts,
  react-hook-form. Zéro build, zéro `node_modules`.
- **Les polices web** (Google Fonts, woff2 distants) : l'app est offline et
  n'utilise que des piles système. Une police embarquée localement serait
  techniquement possible (`trading/static/` existe déjà) mais c'est une décision à
  part, avec son poids au dépôt.
- **Les icônes SVG d'une librairie** : à remplacer par du texte (`[OK]`, `✓`, `✗`,
  `⚠` sont déjà utilisés) ou un SVG inline minimal.
- **Les animations chaînées et transitions d'entrée** : la seule animation de
  l'app est la barre de progression indéterminée du panneau de job
  (`webui.py:245-251`), et elle suffit.
- **Le rendu temps réel type WebSocket** : le monitoring remplace un fragment HTML
  toutes les 7 s. Tout design qui suppose une donnée qui « coule » est à ramener à
  ce modèle.
- **Le mode clair** : le thème est sombre, unique, sans mécanique de bascule. Un
  design en clair serait à jeter.
- **Le responsive mobile réel** : cible desktop, courtoisie jusqu'à la tablette.
  Ne pas payer pour du design mobile qui ne sera jamais regardé.

---

*Fin du kit. Document de conception uniquement — aucun fichier de code n'a été
modifié pour l'écrire.*
