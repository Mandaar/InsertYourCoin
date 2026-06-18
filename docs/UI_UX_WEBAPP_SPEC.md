# UI/UX — Spécification de l'application web locale (InsertYourCoin)

> Statut : VALIDÉE (direction visuelle + 3 décisions §11 actées le 2026-06-18 ;
> maquette des 13 écrans approuvée). Spec de conception, pas du code.
> Implémentation : non commencée — voir la roadmap §9 (Lots 0→9) et
> `docs/RAPPORT_WEBAPP_SUITE.md` pour la reprise.
> Auteur : UX/UI Designer. Cible : transformer la CLI `python main.py <commande>`
> en application web **locale, auto-hébergée, AV-proof**, couvrant TOUTES les fonctions.
> Ancrage : lecture directe de `main.py`, `config.py`, `trading/monitor.py`,
> `trading/options.py`, `trading/dashboard.py`, `trading/paper_trader.py`,
> `trading/stats.py`, `trading/strategies.py`, `lancer.py`, `SETUP.md`, `docs/SQA.md`.
> Principe directeur n°1 : **ne rien casser de ce qui existe** (monitor + options
> déjà en prod) et **monter par lots** vers l'app complète.

---

## 0. Résumé exécutif (à lire en premier)

L'outil est aujourd'hui une CLI honnête + un mini-serveur web stdlib qui sert deux
pages (monitoring du paper + Options). On le fait évoluer vers **une seule app web
locale** servie par le même `http.server` (stdlib, un seul process Python), lancée
par `lancer.bat`/`lancer.sh`, ouverte dans le navigateur sur `127.0.0.1`.

Trois familles d'écrans :
1. **Recherche** (backtest / compare / optimize / walkforward / portfolio / dashboard) :
   on conçoit, on teste, et **le walk-forward juge** (honnêteté).
2. **Exploitation** (paper trading + monitoring live, labo de stats) : on lance, on
   observe sur la durée.
3. **Réglages & live** (check, options/clés Kraken, wallet lien-only, live verrouillé).

Tensions assumées et tranchées dans ce document :
- **Offline vs CDN** : on **vendorise** Chart.js et les polices localement (le dashboard
  actuel dépend d'un CDN — à corriger).
- **CLI longue (backtest/walkforward) vs serveur stdlib** : exécutées en **tâche
  asynchrone** (un job à la fois) avec polling de statut, jamais en bloquant la requête.
- **Friction live vs ergonomie** : le live reste **délibérément pénible** à activer
  (multi-étapes, frappe d'une phrase exacte) — c'est un choix de sécurité, pas un défaut UX.

---

## 1. Vision & principes UX

### 1.1 Pour qui
- **Utilisateur principal (solo)** : le propriétaire de l'outil, prudent, technique
  mais qui veut arrêter de taper des lignes de commande pour le quotidien (lancer un
  backtest, juger au walk-forward, suivre son paper).
- **Tiers à terme** : une personne à qui on partage le dépôt. Elle doit pouvoir
  installer (SETUP.md), lancer (`lancer.bat`) et comprendre **sans manuel** que
  l'outil ne promet aucun gain et que le live est dangereux.

### 1.2 Ton
Sobre, "terminal de trading" raffiné (l'esthétique du dashboard actuel : fond sombre
chaud, accent or, serif pour les titres, monospace pour les chiffres). **Jamais**
de ton commercial, jamais de vert clignotant "GAINS". Le ton dit la vérité, y compris
quand elle est décevante.

### 1.3 Cinq principes directeurs (par ordre de priorité)

1. **Honnêteté avant tout.** Le walk-forward (hors-échantillon) est **typographiquement
   et hiérarchiquement** mis au-dessus du backtest in-sample. Quand il n'y a pas d'edge,
   l'UI l'affiche en clair (pas enterré). Frais, slippage et drawdown sont toujours
   visibles, jamais masqués.
2. **Sécurité par construction.** Clés jamais affichées, live friction-né, wallet
   lien-only, bind local, CSRF, anti-DNS-rebinding. La sécurité existante (monitor.py /
   options.py) est un **socle non négociable** que l'app étend, jamais n'affaiblit.
3. **Clarté > densité.** Un écran = un but. Chaque état (vide / chargement / erreur /
   succès) est dessiné. Lisibilité avant exhaustivité de l'information.
4. **Local-first / offline-capable.** Tout doit fonctionner sans connexion sortante
   sauf l'appel Kraken lui-même (prix). Aucune dépendance CDN au runtime.
5. **Réversibilité & non-surprise.** Aucune action irréversible n'arrive par accident.
   Le paper et la recherche ne touchent jamais d'argent ; seul le live le fait, derrière
   un mur d'avertissements.

---

## 2. Inventaire : commandes CLI -> écrans web

| Commande CLI | Options clés | Écran(s) web | Type d'exécution |
|---|---|---|---|
| `check` | `--symbol` | **Diagnostic** (carte sur l'Accueil + page dédiée) | synchrone court (1 appel Kraken) |
| `backtest` | strat, symbol, timeframe, days, source, risque, `--chart` | **Recherche > Backtest** + vue Rapport (réemploi `dashboard.py`) | async (job) |
| `compare` | idem backtest | **Recherche > Comparer** (tableau toutes stratégies) | async (job) |
| `optimize` | + `--metric`, `--train-frac` | **Recherche > Optimiser** (train/test) | async (job, plus long) |
| `walkforward` | + `--windows`, `--fixed`, `--holdout`, `--final`, `--symbols` | **Recherche > Walk-forward** (LE JUGE) | async (job, le plus long) |
| `portfolio` | `--symbols`, risque | **Recherche > Portefeuille** (multi-actifs + corrélation) | async (job) |
| `dashboard` | strat, risque, `--out` | **vue Rapport** intégrée (rendu inline, pas de fichier à ouvrir) | sous-produit du backtest |
| `paper` | strat, timeframe, risque | **Exploitation > Paper** (config + lancement) + **Monitoring** | process long (lancé/géré) |
| `monitor` | `--port/--stats/--log/--state` | **Monitoring** (existe déjà : `/`, `/fragment`) | serveur (l'app elle-même) |
| `live` | + `--execute` | **Live (verrouillé)** | process long, mur de friction |
| `stats` | `--file` | **Exploitation > Labo de stats** | synchrone (lecture CSV) |
| (options) | log_level, clés, wallet | **Réglages > Options** (existe déjà : `/options`) | synchrone (POST CSRF) |

Notes d'ancrage :
- Stratégies disponibles (registre `STRATEGIES`) : `sma`, `tsmom`, `rsi`, `macd`,
  `bollinger`. Toute liste déroulante de stratégie se génère depuis ce registre.
- `--source` (kraken | binance) n'existe que pour la **recherche** (backtest/compare/
  optimize/walkforward). Le paper/live sont **100% Kraken** : ne JAMAIS exposer `source`
  dans les écrans d'exploitation/live.
- `dashboard.py` n'est plus une commande "qui écrit un fichier à ouvrir" : son HTML
  devient le **rendu Rapport** servi inline après un backtest.

---

## 3. Architecture de navigation (sitemap)

Application **single-server, multi-pages** (pas de SPA : on reste cohérent avec le
modèle actuel coquille HTML + fragments fetch, zéro build JS).

```
/                         Accueil / Tableau de bord (hub)
│
├── /check                Diagnostic (check) — aussi en carte sur l'Accueil
│
├── RECHERCHE
│   ├── /research                 Recherche (hub : choisir l'analyse)
│   ├── /research/backtest        Backtest (-> /report/<job>)
│   ├── /research/compare         Comparer les stratégies
│   ├── /research/optimize        Optimiser (train/test)
│   ├── /research/walkforward     Walk-forward  ← LE JUGE (mis en avant)
│   ├── /research/portfolio       Portefeuille multi-actifs
│   └── /report/<job_id>          Rapport d'un job (réemploi dashboard.py)
│
├── EXPLOITATION
│   ├── /paper                    Paper : configurer + démarrer/arrêter
│   ├── /  (monitoring)           Monitoring live  ← page actuelle (/, /fragment)
│   └── /stats                    Labo de stats (stats)
│
├── RÉGLAGES
│   ├── /options                  Options : log, clés Kraken, wallet  ← existe déjà
│   └── /help                     Aide / SETUP résumé / avertissements
│
└── LIVE
    └── /live                     Live (verrouillé, mur de friction)  ← accès séparé
```

### 3.1 Barre de navigation principale (persistante)

```
+---------------------------------------------------------------------------+
| InsertYourCoin   Accueil  Recherche  Paper  Monitoring  Stats  Options    |
|                                                  [● Local 127.0.0.1] [SSL✓]|
+---------------------------------------------------------------------------+
```

- **Live** n'est PAS dans la nav principale : on y accède par un lien discret depuis
  Options ou l'Accueil, jamais en un clic depuis partout (friction par l'architecture).
- À droite, deux **indicateurs d'état permanents** : "Local 127.0.0.1" (rappel que
  rien n'est exposé) et "SSL ✓/✗" (état de `truststore`/connexion). Voir §6.
- L'item de nav de la page active est surligné (accent or).

### 3.2 Hiérarchie de l'information
- L'**Accueil** est un hub d'état (qu'est-ce qui tourne, est-ce que tout va bien),
  pas un mur de chiffres.
- **Recherche** sépare visuellement les analyses "rapides" (backtest, compare) des
  "verdicts" (walk-forward), ce dernier ayant un traitement visuel dédié (§4.6).
- **Exploitation** = ce qui vit dans le temps (paper + monitoring + stats).

---

## 4. Spécification écran par écran

> Convention : chaque écran décrit **But / Contenu / Composants / Interactions /
> États / Données / Sécurité**. Les wireframes sont indicatifs (ASCII).

### 4.0 Composants transverses (à définir une fois, réutilisés partout)

- **Sélecteur de stratégie** : liste déroulante peuplée depuis `STRATEGIES`
  (`sma / tsmom / rsi / macd / bollinger`). Affiche le nom court + le nom lisible
  (ex. "SMA — croisement de moyennes mobiles").
- **Bloc Paramètres marché** : `symbol` (défaut `ETH/USD`), `timeframe`
  (`1m,5m,15m,1h,4h,1d`, défaut `1d`), `days` (défaut 720) — `days` masqué pour paper/live.
- **Bloc Risque** (réemploi des options CLI) : `stop-loss %`, `take-profit %`,
  `trailing-stop %`, `position-sizing` (none|vol), `target-vol %`. Chaque champ vide
  = désactivé (cohérent avec `_frac()` qui mappe None).
- **Bloc Source d'analyse** (recherche seulement) : radio `kraken` (≈720 bougies,
  l'exchange d'exécution) / `binance` (historique long pour la recherche, sans clé).
  Tooltip honnête : "Binance = recherche longue ; l'exécution reste Kraken USD".
- **Carte KPI** : libellé + valeur, classe couleur up/down/neutre (réemploi `dashboard.py`).
- **Bandeau d'avertissement** : "Performances passées ≠ futures. Pas un conseil en
  investissement." présent au pied de tout écran de résultat.
- **Panneau de job async** : barre de progression indéterminée + bouton Annuler +
  zone de log live (voir §7.2).
- **Disclaimer in-sample** : badge orange "IN-SAMPLE — non validé hors-échantillon" sur
  tout résultat de backtest/optimize/compare ; badge vert/rouge de verdict sur walk-forward.

---

### 4.1 Accueil / Hub (`/`... voir note)

> Note : **DÉCIDÉ (utilisateur, 2026-06-18)** : Accueil sur `/`, monitoring déplacé sur
> `/monitoring`, avec **redirection douce** depuis `/` vers l'Accueil et lien direct vers
> le monitoring. (Aujourd'hui `/` = monitoring ; la bascule se fait au Lot 0/1 avec
> redirection pour ne casser aucun usage.)

**But** : en un coup d'oeil, savoir si tout va bien et où aller.

**Contenu / wireframe**
```
+----------------------------- ACCUEIL ------------------------------+
|  Diagnostic                          | Paper trading               |
|  [✓] Connexion Kraken OK (ETH 3120$) | Statut : EN COURS (CASH)    |
|  [✓] truststore actif (SSL OS)       | Equity 10 042$  (+0.42%)    |
|  [ Relancer le check ]               | [ Voir le monitoring -> ]   |
+--------------------------------------+-----------------------------+
|  Recherche                           | Réglages                    |
|  Dernier walk-forward : ETH/SMA      | Clés Kraken : configurées   |
|  Verdict : PAS D'EDGE (0/4 fenêtres) | [ Options ]  [ Aide ]       |
|  [ Nouvelle analyse -> ]             | lien discret: passer en live|
+--------------------------------------+-----------------------------+
|  Avertissement : outil de recherche. Aucun gain promis. Le live    |
|  engage de l'argent réel — il est verrouillé par défaut.           |
+--------------------------------------------------------------------+
```

**États** : tout-vert (prêt) / check en échec (carte rouge + lien vers /check détaillé) /
paper non démarré (carte "Aucun paper en cours — [Configurer]") / aucune recherche encore
(carte "Lance ta première analyse").

**Sécurité** : indicateurs SSL + Local en permanence ; le lien live est discret et mène
au mur de friction, jamais à une exécution.

---

### 4.2 Diagnostic (`/check`)

**But** : équivalent de `python main.py check` — vérifier install + connexion Kraken.

**Contenu** : versions paquets (python, ccxt, pandas, numpy, truststore), état
truststore, test de connexion sur un symbole (défaut `ETH/USD`), prix obtenu.

**Interactions** : bouton "Lancer le diagnostic" ; champ symbole optionnel.

**États**
- *Chargement* : "Test de connexion à Kraken…" (spinner court).
- *Succès* : carte verte "Connexion OK — ETH/USD = 3120.50".
- *Erreur SSL* : carte orange avec le message actionnable de `diagnose_error`
  (catégorie `ssl`) — texte exact réemployé, qui pointe vers SETUP §6 et rappelle de
  **ne pas désactiver VERIFY_SSL**.
- *Erreur réseau* : carte rouge, message catégorie `network`, bouton "Réessayer".

**Sécurité** : aucune clé requise ni affichée. Le message d'erreur ne contient jamais
de secret (déjà garanti côté `diagnose_error`).

---

### 4.3 Recherche — Backtest (`/research/backtest`)

**But** : tester une stratégie sur l'historique et produire un **Rapport** (équivalent
`backtest` + `dashboard`).

**Contenu / wireframe**
```
+---------------------- RECHERCHE / BACKTEST ----------------------+
| Stratégie [SMA ▾]   Symbole [ETH/USD]   Timeframe [1d ▾]  Jours [720] |
| Source   (●) Kraken  ( ) Binance (recherche longue)              |
| Risque   Stop [8]%  Objectif [20]%  Trailing [  ]%               |
|          Sizing [none ▾]  Vol cible [  ]%                        |
|                                          [ Lancer le backtest ]  |
+-----------------------------------------------------------------+
| (après lancement) -> redirige vers /report/<job_id>             |
+-----------------------------------------------------------------+
```

**Interactions** : remplir le formulaire -> "Lancer" crée un **job async** -> bascule
sur le panneau de progression -> à la fin, redirige vers la **vue Rapport**.

**États** : formulaire (vide/prérempli défauts) / en cours (job) / erreur (données
Kraken indisponibles, message clair) / succès (Rapport).

**Données** : tout ce que renvoie `Backtester.run().summary()` + `metrics`, déjà
structuré par `dashboard.py`.

**Sécurité** : aucune (données publiques). **Honnêteté** : badge IN-SAMPLE sur le Rapport
+ rappel "le walk-forward est le juge" avec lien direct vers /research/walkforward
pré-rempli avec les mêmes paramètres.

---

### 4.4 Recherche — Comparer (`/research/compare`)

**But** : exécuter toutes les stratégies sur le même jeu et les classer (équivalent
`compare`).

**Contenu** : même bloc paramètres (sans choix de stratégie unique). Résultat = tableau
trié : Stratégie | Rendement | Sharpe | DD max | PF | Trades | Réussite, **+ ligne
Buy & Hold** (référence, déjà dans `cmd_compare`).

**Composants** : tableau triable (clic en-tête), colonnes alignées droite pour les
nombres (monospace), badge IN-SAMPLE global.

**États** : vide / en cours / succès (tableau) / "0 stratégie ne bat Buy & Hold" mis en
évidence honnêtement si c'est le cas.

**Sécurité** : aucune. **Honnêteté** : Buy & Hold toujours visible comme garde-fou anti
sur-vente ; phrase reprise de la CLI "de bons chiffres passés ne garantissent jamais le futur".

---

### 4.5 Recherche — Optimiser (`/research/optimize`)

**But** : trouver les meilleurs paramètres AVEC séparation train/test (équivalent
`optimize`).

**Contenu** : bloc paramètres + `metric` (sharpe|sortino|calmar|total_return|
profit_factor) + `train-frac` (défaut 0.6). Résultat = rapport `format_report` :
meilleurs paramètres sur le train, **performance vérifiée sur le test**.

**Composants** : deux panneaux côte à côte "Train (in-sample)" vs "Test (out-of-sample)"
pour matérialiser visuellement la différence. Si le test s'effondre vs le train ->
encart d'alerte "surapprentissage probable".

**États** : vide / en cours (peut être long : barre + log) / succès / "pas assez de
données" (message clair, repris des gardes de l'optimizer).

**Sécurité** : aucune. **Honnêteté** : la colonne test est typographiquement dominante ;
le train est présenté comme "ce qu'on a trouvé", le test comme "ce qui compte".

---

### 4.6 Recherche — Walk-forward (`/research/walkforward`) — LE JUGE

**But** : le test honnête central. Optimisation glissante hors-échantillon, multi-actifs,
holdout sacré, validation finale unique (équivalent `walkforward` complet).

**Contenu / wireframe**
```
+------------------- RECHERCHE / WALK-FORWARD (LE JUGE) -------------------+
| Stratégie [SMA ▾]   Symboles [BTC/USD,ETH/USD,SOL/USD]  Timeframe [1d ▾] |
| Source (●) Binance (historique long, recommandé)  ( ) Kraken            |
| Fenêtres [4]   Train-frac [0.5]   Métrique [sharpe ▾]                    |
| Paramètres FIGÉS (anti-data-mining) [fast=50,slow=200]  (recommandé)     |
| Holdout sacré [20]% recents    [ ] VALIDATION FINALE (1 seule fois!)     |
|                                                  [ Lancer le verdict ]   |
+-------------------------------------------------------------------------+
| RÉSULTAT                                                                 |
|  +-------------------------------------------------------------------+  |
|  |  VERDICT : PAS D'EDGE FIABLE      (0 / 4 fenêtres profitables)     |  |  <- bandeau couleur
|  +-------------------------------------------------------------------+  |
|  Fenêtre 1 ... 4 : rendement OOS, paramètres retenus, DD             |
|  Holdout sacré : NON consommé (ou résultat unique si --final)        |
+-------------------------------------------------------------------------+
```

**Composants spécifiques**
- **Bandeau verdict** en haut du résultat, grande typo, **couleur sémantique** : vert
  "edge plausible", orange "fragile/mitigé", rouge "pas d'edge". C'est l'élément le
  plus visible de TOUTE l'app (priorité honnêteté).
- **Avertissement --final** : la case "Validation finale" déclenche une **confirmation
  modale** ("À ne faire qu'UNE fois par stratégie : le holdout sera consommé. Continuer ?")
  — friction volontaire, car `--final` brûle le segment sacré.
- **Tableau par fenêtre** : période OOS, params retenus, métrique, rendement, DD.
- **Encart pédagogique** repliable : "Pourquoi le walk-forward est le juge".

**États** : formulaire / en cours (le plus long des jobs : barre + log + estimation) /
verdict (vert/orange/rouge) / erreur (holdout invalide -> message des gardes
`--holdout doit être dans [0,90[`, `--final exige --holdout>0`) / "validation finale
impossible" par symbole (message repris de `cmd_walkforward`).

**Sécurité** : aucune (données publiques). **Honnêteté** : c'est l'écran qui incarne la
doctrine. Le walk-forward n'est jamais présenté comme une garantie ; le bandeau dit la
réalité même quand elle déçoit.

---

### 4.7 Recherche — Portefeuille (`/research/portfolio`)

**But** : backtester un panier multi-actifs équipondéré + corrélation (équivalent
`portfolio`).

**Contenu** : `symbols` (défaut `BTC/USD,ETH/USD,SOL/USD`) + bloc risque. Résultat =
`format_portfolio` : métriques agrégées + **matrice de corrélation**.

**Composants** : carte KPI agrégées + heatmap de corrélation (rendue en HTML/CSS simple,
pas besoin de lib) + courbe d'equity du panier.

**États** : vide / en cours / succès / "actif ignoré" (message repris de `_load_basket`
quand un symbole n'est pas chargeable) / "aucun actif chargeable".

**Sécurité** : aucune. **Honnêteté** : afficher la corrélation élevée (~0.8 crypto) en
clair avec la note "la diversification lisse mais ne protège pas d'un krach systémique"
(constat déjà acté dans CLAUDE.md).

---

### 4.8 Vue Rapport (`/report/<job_id>`)

**But** : afficher le résultat riche d'un backtest (réemploi intégral de `dashboard.py`).

**Contenu** : exactement la sortie de `generate_dashboard` (cartes KPI, courbe de
capital, drawdown, comparaison, derniers trades, footer avertissement) — **servie
inline**, plus de fichier `.html` à ouvrir manuellement.

**Changement requis vs existant** : `dashboard.py` charge aujourd'hui Chart.js et les
polices depuis un **CDN** (lignes ~140-143). Pour l'offline (principe 4), **vendoriser**
Chart.js (un `.js` local servi par le serveur) et les polices, ou dégrader proprement.
Voir §7.3.

**États** : rapport prêt / "graphiques indisponibles hors-ligne" (fallback dégradé si
on garde le CDN sans vendoring) / job introuvable (lien expiré -> retour Recherche).

**Sécurité** : aucune.

---

### 4.9 Exploitation — Paper (`/paper`)

**But** : configurer et démarrer/arrêter le paper trading (équivalent `paper` +
intégration `lancer.py`).

**Contenu / wireframe**
```
+------------------------------ PAPER ------------------------------+
| Statut : ARRÊTÉ                                                   |
| Stratégie [SMA ▾]  Symbole [ETH/USD]  Timeframe [5m ▾]            |
| Risque  Stop [5]%  Objectif [10]%  Trailing [8]%                  |
|         Sizing [none ▾]                                           |
|                              [ Démarrer le paper trading ]        |
+------------------------------------------------------------------+
| (en cours) Statut : EN COURS  depuis 2026-06-18 14:00            |
|            [ Arrêter ]   [ Voir le monitoring -> ]              |
+------------------------------------------------------------------+
```

**Interactions** : "Démarrer" lance le process paper (via la mécanique de `lancer.py`,
en réutilisant les gardes `Start-Process` / survie process documentées dans MEMORY.md
"gotcha process long-vivants vs job object"). "Arrêter" = stop propre. Les paramètres
remplacent les constantes en tête de `lancer.py` (qui dit explicitement "en attendant
une page Options").

**États** : arrêté / démarrage (transitoire) / en cours / inactif détecté (si aucun
cycle depuis >360s, cohérent avec `compute_view` `inactif`) / erreur de démarrage.

**Données** : statut dérivé de `paper_state.json` + présence du process.

**Sécurité** : **aucune clé requise** (paper = données publiques). Le paper ne touche
jamais d'argent. **Ne jamais** exposer `source=binance` ici (paper = Kraken only).
Garde-fou architectural : cet écran ne doit **jamais** pouvoir construire une commande
`live` (cf. `assert_paper_only`).

---

### 4.10 Exploitation — Monitoring (`/monitoring`, fragment `/fragment`) — EXISTE DÉJÀ

**But** : suivre le paper EN DIRECT. **C'est la page actuelle de `monitor.py`** — on la
conserve telle quelle (auto-refresh 7s via `fetch('/fragment')`), on l'intègre juste à
la nav et au thème global.

**Contenu** (déjà en prod) : bandeau de cartes (Statut, Prix, Equity, P&L, Drawdown,
Exposition, Cycles), derniers ordres, journal, alerte d'inactivité.

**États** (déjà gérés par `render_fragment`) : "en attente de données du paper" (vide) /
données présentes / alerte inactif (>360s).

**Sécurité** : lecture seule de fichiers (ne touche jamais le trading) ; bind 127.0.0.1 ;
host vérifié (anti-DNS-rebinding). **Inchangé.**

---

### 4.11 Exploitation — Labo de stats (`/stats`)

**But** : synthèse descriptive du CSV de stats (équivalent `stats`).

**Contenu** : sortie de `summarize` / `format_summary` mise en page web : période,
cycles, rendement, drawdown max, trades, réussite, PnL, **part des frais**, exposition
moyenne, **ventilation par heure et par jour** (tableaux ou mini-barres).

**Composants** : sélecteur de fichier CSV (défaut `paper_stats.csv`) ; tableaux
heure/jour ; encart d'honnêteté repris mot pour mot de `format_summary` ("stats
DESCRIPTIVES, pas une preuve d'edge…").

**États** : vide ("Aucune donnée de stats — lance d'abord du paper", message exact de
`load_stats`) / données présentes.

**Sécurité** : lecture seule. **Honnêteté** : la part des frais est mise en évidence
(sur timeframe court, les frais Kraken pèsent lourd — déjà dit dans `format_summary`).

---

### 4.12 Réglages — Options (`/options`) — EXISTE DÉJÀ

**But** : niveau de logs du paper, liaison Kraken (clés), wallet lien-only.
**C'est la page actuelle de `options.py` / `render_options_page`** — conservée, ré-habillée
au thème global, étoffée prudemment.

**Contenu** (déjà en prod) :
- Radios niveau de logs (leger / moyen / complet), appliqué à chaud.
- Champs clés **masqués** (`type=password`, placeholders "laisser vide pour ne pas
  changer"), case "Enregistrer dans .env (sinon session seulement)".
- État booléen "Clés configurées : OUI/NON" (jamais la valeur).
- Aide : créer la clé avec **Query Funds + Create & Modify Orders uniquement, JAMAIS
  Withdraw Funds**.
- Bloc Wallet : **lien** vers la page de retrait officielle Kraken, "cette app ne fait
  jamais de retrait et n'enregistre rien".

**Ajout proposé (optionnel, à valider)** : un bouton "Tester la liaison Kraken" qui
appelle `Query Funds` en lecture seule et affiche OK/échec **sans** révéler de solde
sensible en clair par défaut (solde masquable). Réutilise les clés session si présentes.

**États** : formulaire / "Modifications enregistrées" (bandeau vert, via redirect 303
existant) / 403 CSRF / 400 valeur invalide / 403 host non autorisé. Tous déjà gérés.

**Sécurité (socle non négociable, déjà en place)** : CSRF token au POST, comparaison
temps constant ; clés **jamais** dans le HTML/log/réponse (booléen seul) ; clés session =
**mémoire seule, rien sur disque** si case décochée ; `update_env_file` refuse les retours
à la ligne (anti-injection) ; bind 127.0.0.1 ; `host_allowed` anti-DNS-rebinding.

---

### 4.13 Live (`/live`) — VERROUILLÉ, mur de friction

**But** : exposer le live (équivalent `live --execute`) **sans jamais** le rendre
facile ni accidentel. Par défaut **dry-run**.

**Contenu / parcours en escalier (friction volontaire)**
```
+------------------------- LIVE (DANGER) -------------------------+
| Bandeau rouge permanent : ARGENT RÉEL. Pertes possibles jusqu'à |
| la totalité du capital. Outil sans garantie.                    |
+----------------------------------------------------------------+
| Pré-requis (tous obligatoires, sinon bouton désactivé) :        |
|  [✓] Clés Kraken configurées (Query Funds + Orders, PAS Withdraw)|
|  [✓] Diagnostic check OK                                         |
|  [✓] J'ai lancé un paper sur cette config et compris le risque   |
|  [✓] J'ai lu les plafonds : ordre max 100$ / position max 500$   |
+----------------------------------------------------------------+
| Mode : (●) Simulation (dry-run)   ( ) RÉEL                       |
|  -> Choisir "RÉEL" ouvre une modale récapitulative (paire,       |
|     stratégie, stop/objectif, plafonds config.py) et demande de  |
|     TAPER EXACTEMENT :  OUI JE CONFIRME                          |
|  [ Démarrer ]                                                    |
+----------------------------------------------------------------+
```

**Interactions** : le mode RÉEL exige (1) toutes les cases pré-requises cochées,
(2) la sélection explicite "RÉEL", (3) la modale récap (reprend l'écran de confirmation
texte de `cmd_live`), (4) la frappe **exacte** de `OUI JE CONFIRME` (même phrase que la
CLI). Toute faute -> annulation, aucun ordre. Dry-run reste l'option par défaut sélectionnée.

**États** : verrouillé (pré-requis incomplets, bouton RÉEL grisé) / dry-run prêt / modale
de confirmation / live en cours (bandeau rouge persistant + bouton "Arrêter
immédiatement" toujours visible) / clés manquantes (message exact de `cmd_live`).

**Données affichées** : plafonds `MAX_TRADE_VALUE_USD` (100$), `MAX_POSITION_VALUE_USD`
(500$), `MIN_TRADE_INTERVAL_SEC` — lus de `config.py`, toujours montrés avant exécution.

**Sécurité (le coeur)** : dry-run par défaut ; double (triple) confirmation ;
phrase exacte ; plafonds visibles et appliqués côté `config.py` (l'UI ne les contourne
jamais) ; clés jamais affichées ; live absent de la nav principale. **L'UI rend le live
volontairement pénible — c'est le design, pas un bug.**

---

### 4.14 Aide (`/help`)

**But** : SETUP résumé, workflow recommandé, avertissements, liens.

**Contenu** : ordre de travail honnête (backtest -> walk-forward -> paper -> live),
rappel SSL/antivirus (truststore), rappel "ne jamais désactiver VERIFY_SSL", encart
risque/non-conseil. Lien vers SETUP.md complet.

**Sécurité** : page statique, aucune donnée sensible.

---

## 5. Parcours utilisateurs clés

### 5.1 Premier lancement -> recherche -> juger -> paper -> suivre (parcours nominal)
1. L'utilisateur double-clique `lancer.bat`. Le serveur démarre, le navigateur s'ouvre
   sur l'**Accueil**.
2. La carte **Diagnostic** montre l'état du `check` (vert = connexion Kraken OK). Si
   rouge SSL -> message actionnable truststore.
3. Il va dans **Recherche > Backtest**, choisit SMA/ETH/1d, lance -> **Rapport** (badge
   IN-SAMPLE bien visible).
4. Le Rapport l'invite à **valider au walk-forward** (lien pré-rempli). Il lance
   **Recherche > Walk-forward** avec params figés + holdout.
5. **Bandeau verdict** : "PAS D'EDGE (0/4)". L'app ne le cache pas -> il sait que cette
   stratégie n'a pas d'edge fiable.
6. Il décide quand même de tester en réel-fictif : **Paper**, configure, **Démarrer**.
7. Il suit sur **Monitoring** (auto-refresh 7s) sur plusieurs semaines, puis consulte
   **Labo de stats** pour la ventilation et la part des frais.

### 5.2 Lier son compte Kraken
1. **Options**. Lit l'aide : créer la clé Kraken avec **Query Funds + Create & Modify
   Orders uniquement** (jamais Withdraw).
2. Colle les deux clés (champs masqués). Choisit "session seulement" (rien sur disque)
   OU "Enregistrer dans .env".
3. "Enregistrer" -> bandeau vert. État passe à "Clés configurées : OUI".
4. (Optionnel) "Tester la liaison" -> OK/échec, sans révéler de solde par défaut.

### 5.3 Tenter de passer en live (parcours de friction)
1. Lien discret "passer en live" (Accueil/Options) -> page **Live**, bandeau rouge.
2. Bouton RÉEL **grisé** tant que les pré-requis (clés, check OK, paper fait, plafonds lus)
   ne sont pas tous cochés.
3. Choisit "RÉEL" -> modale récap (paire, stratégie, stop/objectif, plafonds config.py).
4. Doit taper **exactement** `OUI JE CONFIRME`. Une faute -> annulation, zéro ordre.
5. En live : bandeau rouge permanent + "Arrêter immédiatement" toujours visible.

### 5.4 Parcours d'échec à dessiner (anti happy-path)
- **Kraken indisponible / réseau** pendant un job de recherche -> message clair +
  bouton Réessayer, jamais d'écran blanc.
- **SSL intercepté** au check -> message truststore actionnable (pas un stacktrace).
- **Pas de données stats** -> état vide pédagogique, pas une erreur.
- **Job déjà en cours** (un seul à la fois) -> l'app propose d'attendre/annuler le job
  courant plutôt que d'en empiler.

---

## 6. Modèle de sécurité côté UI (traduction des garde-fous en UX)

| Garde-fou (code) | Traduction UX |
|---|---|
| Bind `127.0.0.1` | Indicateur permanent "Local 127.0.0.1" en nav ; page d'aide explique "rien n'est exposé au réseau". |
| `host_allowed` (anti-DNS-rebinding) | Transparent ; page 403 lisible "Host non autorisé" si déclenché. |
| CSRF token (`csrf_valid`) | Transparent ; page 403 "jeton CSRF invalide" si POST forgé. Tout nouveau formulaire POST embarque le token caché. |
| `VERIFY_SSL=True` + truststore | Indicateur "SSL ✓/✗" en nav ; check explique l'état ; **aucune option UI pour désactiver SSL** (volontairement absente). |
| Clés `.env` seules, jamais affichées | Champs `type=password`, placeholders neutres, état booléen OUI/NON ; jamais de valeur dans le HTML/log/réponse. |
| Clés session = mémoire seule | Case "Enregistrer dans .env" décochée par défaut -> rien sur disque ; libellé explicite. |
| Clé sans Withdraw | Texte d'aide insistant (gras + couleur warn) à chaque endroit où on parle de clés. |
| Wallet lien-only | Bloc Wallet = **lien sortant** vers Kraken + "cette app ne fait jamais de retrait". Aucun champ d'adresse, aucun bouton de transfert. |
| Live dry-run + double confirmation + plafonds | Live hors nav principale ; pré-requis ; modale ; phrase exacte ; plafonds config.py affichés ; "Arrêter" toujours visible. |
| `assert_paper_only` (lanceur) | L'écran Paper ne peut structurellement pas construire une commande live. |
| Pas de secret en erreur | Toutes les pages d'erreur réutilisent les messages génériques existants (jamais de valeur sensible). |

Principe : **aucun garde-fou existant n'est relâché par l'UI**. L'UI les rend visibles
et les renforce par de la friction là où l'argent réel est en jeu.

---

## 7. Contraintes & stack techniques

### 7.1 Serveur
- **Un seul process Python**, `http.server.ThreadingHTTPServer` (stdlib), comme
  `monitor.py` aujourd'hui. Pas de framework web, pas de Node, **zéro build JS**.
- Pages servies = HTML assemblé en Python (fonctions pures testables, comme
  `render_fragment` / `render_options_page`) + CSS inline + JS vanilla minimal
  (fetch pour fragments/jobs).
- Nouvelles routes ajoutées au même `Handler` (GET/POST) avec **les mêmes gardes**
  (`_host_ok`, CSRF sur POST). Chaque nouvelle page POST = un token caché.

### 7.2 Jobs asynchrones (backtest/compare/optimize/walkforward/portfolio)
Ces commandes peuvent durer (surtout walk-forward multi-actifs / source binance). Elles
ne doivent **jamais** bloquer le thread HTTP d'une requête.
- Modèle proposé : **un job à la fois** (file simple), exécuté dans un thread worker.
  Routes : `POST /research/<type>` crée le job et renvoie un `job_id` ; `GET
  /job/<id>/status` (polling JS, ex. toutes les 1-2s) renvoie état + log partiel ; à la
  fin, redirection vers la page de résultat (`/report/<id>` ou la vue dédiée).
- Le panneau de job affiche : barre indéterminée, log live (réemploi du style `.log` du
  monitor), bouton **Annuler**.
- **Tension assumée** : le stdlib `http.server` est mono-jeu/léger ; un seul job
  concurrent est un choix délibéré (un utilisateur solo, pas un service multi-tenant).
  Si l'utilisateur lance un 2e job, l'UI propose d'attendre/annuler le courant.

### 7.3 Offline / vendoring (corrige une dette existante)
- `dashboard.py` charge **Chart.js + polices Google via CDN** -> casse hors-ligne et
  fait fuiter une requête sortante. **Décision : vendoriser** Chart.js (un fichier
  `static/chart.umd.min.js` servi localement) et les polices (ou fallback polices
  système). Le reste de l'app n'utilise aucun CDN.
- Servir un dossier `static/` (CSS partagé, JS, Chart.js vendorisé, éventuelles polices)
  via une route statique simple du Handler.
- **Tension assumée** : vendoriser ajoute ~200-300 Ko au dépôt mais garantit l'offline et
  l'absence de requête tierce — cohérent avec local-first et AV-proof.

### 7.4 Perf & robustesse
- Relecture des fichiers à chaque requête (déjà le modèle monitor) = données fraîches,
  pas de cache à invalider. Suffisant pour un usage solo.
- Toute exception du Handler -> page d'erreur lisible **sans** donnée sensible (déjà le
  cas dans `do_GET`).
- Respect des gotchas machine : `.bat`/`.ps1` en ASCII pur ; vérification d'écriture FUSE ;
  process paper lancé en `Start-Process` survivant (MEMORY.md).

### 7.5 Intégration avec `lancer.bat` / `lancer.sh` / `lancer.py`
- Le lanceur reste le point d'entrée "double-clic" : `check` -> démarre l'app web ->
  ouvre le navigateur. Aujourd'hui il démarre paper + monitor ; demain il démarre **l'app
  complète** (le serveur sert toutes les pages), le paper devenant démarrable **depuis
  l'écran Paper** plutôt que codé en tête de `lancer.py`.
- **Garde-fou conservé** : le lanceur reste incapable de lancer `live` (`assert_paper_only`).
  Le live ne se déclenche **que** depuis l'écran /live, jamais depuis le lanceur.

---

## 8. Accessibilité & responsive

- **Cible principale : desktop** (navigateur local). Responsive "courtoisie" jusqu'au
  format tablette ; le walk-forward et les tableaux peuvent défiler horizontalement sur
  petit écran (déjà `overflow-x:auto` dans le dashboard).
- **Clavier** : tous les formulaires navigables au Tab ; bouton "Lancer" atteignable ;
  modale live focus-trap, Échap = annuler (jamais Échap = confirmer).
- **Contraste** : le thème sombre actuel (#0e1116 / #d7dee8) a un bon ratio ; vérifier
  que les accents (or #d6aa5a, vert #46c46f, rouge #e5534b) atteignent AA sur fond sombre
  pour le texte porteur de sens. Ne jamais coder une info **uniquement** par la couleur :
  doubler par un mot ("VERDICT : PAS D'EDGE", "IN-SAMPLE", icône + texte).
- **Tailles de cible** : boutons >= 40px de haut ; champs de saisie confortables.
- **Lisibilité** : monospace pour les chiffres (alignement), serif pour les titres ;
  pas de densité excessive (principe 3).
- **Daltonisme** : verdict walk-forward = couleur + libellé + position, jamais couleur seule.

---

## 9. Roadmap d'implémentation incrémentale (par lots, sans tout casser)

> Ordre conçu pour partir de l'existant (monitor + options déjà en prod) et monter
> progressivement. Chaque lot livrable et testable (gate SQA : pytest vert, pas de P0/P1).

**Lot 0 — Socle commun (ré-habillage, zéro régression).**
Extraire un thème CSS partagé + une coquille de nav commune ; vendoriser Chart.js et les
polices (corrige la dette CDN). Brancher Options et Monitoring existants sur la nav. Aucun
changement de comportement métier. Tests d'intégration loopback conservés (cf. BUG-008).

**Lot 1 — Accueil + Diagnostic.**
Page hub `/` (ou redirection) + `/check` web (réemploi `run_check`/`diagnose_error`).
Premier vrai bénéfice utilisateur visible sans toucher au trading.

**Lot 2 — Labo de stats web (`/stats`).**
Lecture seule, réemploi `summarize`/`format_summary`. Faible risque, forte valeur.

**Lot 3 — Infrastructure de jobs async.**
Worker mono-job + routes `/job/<id>/status` + panneau de progression. Pré-requis des
écrans de recherche. À tester isolément (un faux job long).

**Lot 4 — Recherche : Backtest + Rapport inline.**
`/research/backtest` -> job -> `/report/<id>` (réemploi `dashboard.py` vendorisé). Le
dashboard cesse d'être un fichier à ouvrir.

**Lot 5 — Recherche : Compare + Optimize + Portfolio.**
Réemploi `cmd_compare` / `optimizer` / `portfolio`. Tableaux + train/test + corrélation.

**Lot 6 — Recherche : Walk-forward (LE JUGE).**
L'écran le plus soigné (bandeau verdict, holdout, --final avec modale). Mis en avant
typographiquement. Incarne la doctrine d'honnêteté.

**Lot 7 — Paper pilotable depuis l'UI.**
Démarrer/arrêter le paper depuis `/paper` (remplace les constantes en tête de `lancer.py`).
Conserver le garde-fou paper-only.

**Lot 8 — Live verrouillé (`/live`).**
En dernier, avec le maximum de revue (P0 par nature). Mur de friction complet, plafonds
config.py, phrase exacte, dry-run par défaut. Gate SQA renforcée avant merge.

**Lot 9 — Polish & accessibilité.**
Contraste AA vérifié, clavier/focus-trap, états vides/erreur peaufinés, aide complète.

> À chaque lot : respecter le gate SQA (§4 de `docs/SQA.md`) — pytest vert, garde-fous
> live intacts, aucun secret commité, `VERIFY_SSL=True`, test de non-régression par bug
> corrigé.

---

## 10. Tensions & risques (honnêteté de conception)

- **Offline vs richesse graphique** : vendoriser Chart.js est la bonne réponse, mais
  ajoute un binaire au dépôt à maintenir/mettre à jour. Alternative dégradée : graphiques
  SVG maison (plus légers, moins riches). Recommandation : vendoring.
- **stdlib http.server vs charge** : suffisant pour un solo, fragile si plusieurs jobs
  lourds simultanés. Choix : **un job à la fois**, assumé et expliqué à l'utilisateur.
- **Friction live vs ergonomie** : la friction est volontairement anti-ergonomique. Le
  risque inverse (live trop facile) est inacceptable -> on tranche pour la friction.
- **Réutilisation du `/` actuel** : déplacer le monitoring de `/` vers `/monitoring`
  peut surprendre un utilisateur habitué. Mitigation : redirection douce + lien direct
  (décision à valider, §11).
- **Tiers à terme** : si l'app est partagée, un tiers pourrait lier ses propres clés ;
  l'absence de Withdraw et le wallet lien-only restent les garde-fous clés.

---

## 11. Décisions de l'utilisateur (ACTÉES le 2026-06-18)

1. **Route de l'Accueil** : ✅ **Accueil sur `/`**, monitoring déplacé sur `/monitoring`
   avec redirection douce et lien direct. (Bascule au Lot 0/1, sans casser les usages.)
2. **Vendoring offline** : ✅ **On vendorise** Chart.js + polices en local (~200-300 Ko au
   dépôt). 100% offline, zéro requête tierce ; corrige la dette CDN de `dashboard.py`.
3. **Bouton "Tester la liaison Kraken" dans Options** : ✅ **Oui**, appel `Query Funds` en
   **lecture seule**, résultat OK/échec, **solde masqué par défaut** (masquable). Réutilise
   les clés session si présentes ; ne révèle jamais de valeur sensible sans action explicite.

---

*Fin de la spec. Document de conception uniquement — aucune ligne de code à livrer ici.
Toute implémentation passe par le `ui-programmer` sous revue, lot par lot, avec gate SQA.*

