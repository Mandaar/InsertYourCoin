# Audit READ-ONLY — App web InsertYourCoin (Lots 0-5)

> Auteur : qa-tester. Date : 2026-07-16. Portee : preparation du Lot 9
> (polish & accessibilite). Methode : sonde HTTP GET reelle sur le serveur
> `http://127.0.0.1:8765/` (process paper en cours, port ephemere non touche),
> lecture du code source (`trading/webui.py`, `trading/monitor.py`,
> `trading/*_page.py`, `trading/dashboard.py`, `trading/jobs.py`,
> `trading/research_runners.py`, `trading/stats.py`, `config.py`), calcul
> **programmatique** des ratios de contraste WCAG (formule de luminance
> relative officielle, pas d'estimation a l'oeil) sur les paires de couleurs
> du theme. Aucune modification de fichier hors ce rapport. Aucun POST, aucun
> job lance, aucun secret lu.

**Avertissement methodologique important** : le serveur interroge a servi des
reponses refletant un etat de code **legerement anterieur** au HEAD du depot.
Le disque contient deja du code de **Lot 6 (walk-forward) en cours** (routes
`/research/walkforward` cablees dans `trading/monitor.py`, `RESEARCH_SUBNAV`
avec `walkforward` a `enabled=True` dans `trading/webui.py`), alors que le
process en cours d'execution (paper demarre 2026-07-16 16:07, donc lance
avant ces edits) affiche encore Walk-forward en "bientot" et un texte legerement
different sur `/research/backtest` ("Le walk-forward (bientot dans l'app) est
le juge." au lieu du texte avec lien deja present sur le disque). **Ce n'est
pas une regression Lots 0-5** : c'est un serveur qui n'a pas encore ete
redemarre pendant qu'un chantier Lot 6 tourne en parallele. Les constats
ci-dessous portent sur les ecrans **Lots 0-5** (stables, non concernes par ce
chantier), sauf mention explicite.

---

## Decompte des findings

| Severite | Nombre |
|---|---|
| P0 | 0 |
| P1 | 0 |
| P2 | 4 |
| P3 | 7 |

Aucun P0/P1 trouve : aucun risque financier, aucun contournement de
garde-fou live, aucun crash serveur, aucune fuite de secret constatee sur le
perimetre sonde.

---

## 1. Parcours HTTP reel (GET seulement)

Toutes les routes demandees ont ete sondees en GET pur (`curl`, sans cookie,
sans session).

| Route | Statut | Content-Type | Observation |
|---|---|---|---|
| `/` | 200 | text/html | Accueil, nav "Accueil" active, 4 cartes + bandeau avertissement |
| `/check` | 200 | text/html | Diagnostic, nav "Diagnostic" active, etat neutre "non lance cette session" |
| `/monitoring` | 200 | text/html | Page complete + fragment initial + script JS 7s |
| `/fragment` | 200 | text/html | Fragment seul (pas de `<html>`), identique au contenu de `/monitoring` |
| `/stats` | 200 | text/html | Donnees reelles (947 cycles), cartes + barres heure/jour + encart honnetete |
| `/options` | 200 | text/html | Formulaire complet, CSRF token present, aucune valeur de cle affichee |
| `/research/backtest` | 200 | text/html | Formulaire pre-rempli defauts (SMA, ETH/USD, 1d, 720j) |
| `/research/compare` | 200 | text/html | Formulaire, sous-nav "Comparer" active |
| `/research/optimize` | 200 | text/html | Formulaire, sous-nav "Optimiser" active |
| `/research/portfolio` | 200 | text/html | Formulaire, sous-nav "Portefeuille" active |
| `/static/chart.umd.min.js` | 200 | application/javascript | 205 399 octets servis, vendoring OK (aucun CDN) |
| `/this-route-does-not-exist` | 404 | text/html | `<h1>404</h1>` brut (cf. P3-4) |
| `/job/<32 zeros>/status` | 404 | application/json | `{"error": "job introuvable"}` — propre, pas de fuite |
| `/job/not-a-valid-id/status` | 404 | text/html | Rejete par la regex AVANT JobManager (`<h1>404</h1>` brut) — defense en profondeur confirmee empiriquement |
| `/stats?file=../../../../windows/win.ini` | 200 | text/html | Retombe sur `paper_stats.csv` (whitelist tient, confirme empiriquement — pas de traversal) |
| `/stats?file=doesnotexist_stats.csv` | 200 | text/html | Idem, fallback propre |

**Verdict** : routage sain, coherence de nav verifiee sur toutes les pages
(item actif correctement surligne `class='tab active'` sur chaque ecran testé,
sous-nav Recherche idem), items "bientot" (Paper, Aide, Walk-forward au
moment du test) rendus systematiquement en `<span class='...disabled'>`
jamais en lien mort — **conforme au patron demande par le code lui-meme**
(`trading/webui.py` `_render_nav`/`research_subnav_html`).

---

## 2. Accessibilite (spec §8)

### 2.1 Contraste — calcul WCAG reel (formule de luminance relative)

Calcule programmatiquement (pas a l'oeil) sur toutes les paires
texte/fond du theme (`trading/webui.py` `THEME_CSS` + CSS des pages).
Seuil AA texte normal = 4.5:1, AA grand texte (>=24px ou >=18.66px gras) = 3:1.

**PASS (large marge, 4.15:1 a 13.96:1)** : `--txt` (#d7dee8), `--muted`
(#7f8c9c), `--gold` (#d6aa5a), `--gold-bright` (#f0b429), `--up` (#46c46f),
`--down` (#e5534b — 4.62:1 sur panel, limite mais passe), `--blue` (#6cb6ff),
sur `--bg`/`--panel` ; tous les badges/callouts (`.ok-cat`, `.ssl`,
`.network`, `.saved`, `.in-sample-badge`, `.no-edge`, job-panel states,
cartes fees) ; les couleurs du gabarit `dashboard.py` (`--up`/`--down`/
`--gold`/`--muted` du rapport, sur son propre fond `--panel`/`--bg` dedies).

**FAIL — `--muted2` (#6b7787)** :
- Sur `--bg` (#0e1116) : **4.15:1** (< 4.5 requis).
- Sur `--panel` (#171c24) : **3.76:1** (< 4.5 requis).
- **Aggrave par `opacity:.55`** applique sur les elements desactives
  (`.nav span.tab.disabled`, `.research-subnav span.sub-tab.disabled`,
  `.nav .tab .soon`) : la couleur RENDUE reellement (blend alpha sur le fond
  nav ~#0b0d11) tombe a **#404752**, soit un ratio de **2,08:1** — echec
  severe, sous le seuil AA-large (3:1) lui-meme.
- Usages concrets : items de nav desactives ("Paper", "Aide", et
  "Walk-forward" au moment du test), badge "bientot", `.disabled-link`
  ("Aide (bientot)" sur l'Accueil, `trading/home_page.py` `_settings_card`),
  et **`.barval`** dans `trading/stats_page.py` (`_bars_card`) — donnee
  chiffree porteuse de sens (nombre de cycles/trades par heure/jour), a
  pleine opacite (ratio 3.76:1 sur panel, echec meme sans le facteur opacite).

C'est le seul echec de contraste trouve sur l'ensemble du theme partage.
Portee : nav (tous ecrans), sous-nav Recherche, Accueil, Labo de stats.

### 2.2 Information portee par la couleur seule

**PASS, verifie a la source** : aucun cas trouve ou la couleur est le SEUL
vecteur de sens.
- `metrics_format.pct()` (utilise par Comparer/Optimiser/Portefeuille) emet
  toujours un signe explicite `+`/`-` en plus de la classe CSS up/down/neu —
  la couleur ne fait que renforcer un texte deja explicite.
- Pill SSL : texte different selon l'etat ("SSL verif. actif" vs
  "SSL VERIF. DESACTIVEE"), pas juste une couleur de point.
- Diagnostic (Accueil + `/check`) : marqueurs textuels `[OK]`/`[ECHEC]`/`[!]`
  systematiquement doubles de couleur, jamais l'inverse.
- Table Trades ordres (monitoring) : `BUY`/`SELL` est le texte de la cellule
  elle-meme, la couleur (vert/rouge) ne fait que souligner.
- Tableau Comparer : Buy & Hold toujours affiche en ligne separee avec
  libelle "(reference)", jamais seulement une teinte differente.

### 2.3 Hierarchie de titres (h1/h2/h3)

**PASS sur 8 des 9 templates verifies** (Accueil, Diagnostic, Labo de stats,
Options, Backtest formulaire, Comparer formulaire+resultat, Portefeuille
formulaire+resultat, Rapport backtest/dashboard.py qui a son propre
h1→h2 interne coherent).

**FAIL localise** : `trading/optimize_page.py` `render_optimize_done` — la
page a un `<h1>Recherche — Optimiser</h1>` mais les panneaux Train/Test
utilisent directement `<h3>` (`_tt_panel`, ligne ~246-259) **sans aucun
`<h2>` intermediaire**. Saut de niveau h1→h3. (P3-1)

### 2.4 Labels de formulaire / association input

**PASS** sur tous les formulaires POST examines (`/research/backtest`,
`/research/compare`, `/research/optimize`, `/research/portfolio`,
`/options`, `/check`) : chaque `<input>`/`<select>` a soit un
`<label class='flabel' for='id'>` correctement apparie a un `id=` identique,
soit (radios/checkbox) le `<input>` est **enveloppe** par le `<label>`
(association implicite valide).

**FAIL localise** : `trading/stats_page.py` `_file_picker_html` — le
selecteur de fichier CSV (`<select name='file'>`) n'a **ni `id`, ni
`<label for=...>` associe** ; le texte "Source :" est du texte brut hors
`<label>`. Un lecteur d'ecran annoncera la combobox sans le contexte
"Source". (P3-2)

### 2.5 Navigabilite clavier

**PASS**. Aucune regle `outline:none` ni `:focus{...}` (recherche exhaustive
sur `trading/`) : aucune suppression de l'anneau de focus par defaut du
navigateur. Aucun widget custom (div-bouton, JS-only) — uniquement des
`<a>`/`<button>`/`<input>`/`<select>` natifs partout : ordre de tabulation
et activation clavier fonctionnent nativement, sans plomberie
supplementaire necessaire.

### 2.6 Tailles de cible (spec §8 : "boutons >= 40px de haut")

Calcule (font-size × line-height 1.5 + paddings verticaux, `box-sizing:
border-box`, aucune `min-height` explicite) :

| Element | Hauteur calculee | vs cible 40px |
|---|---|---|
| `.btn` (formulaires recherche/options/check) | ≈ 39.0 px | -1px, marginal |
| `.btn-cancel` (panneau job) | ≈ 33.5 px | -6.5px |
| `.nav a.tab` | ≈ 36.2 px | -3.8px |
| bouton "Charger" (`/stats` file-picker) | ≈ 31.5 px | -8.5px |

Aucun n'atteint le seuil que la spec se fixe elle-meme. Le `.btn` principal
est proche (marginal), les boutons secondaires (Annuler job, Charger stats)
sont clairement en dessous. (P3-3)

---

## 3. Honnetete UI

**PASS, largement verifie** :
- **Badge IN-SAMPLE** present et correctement redige sur **Backtest**
  (`report_page.render_report_done`, "IN-SAMPLE — non valide
  hors-echantillon...") et **Comparer** (`compare_page.render_compare_done`,
  `.in-sample-badge`).
- **Buy & Hold** toujours visible sur Comparer, ligne dediee
  `bh-row`, jamais masque ; callout honnete automatique **"0 strategie ne bat
  Buy & Hold sur cette periode"** quand c'est le cas (`.no-edge`).
- **Optimiser** : le panneau **Test (hors-echantillon)** est
  typographiquement dominant (bordure or, police plus grande) vs Train —
  conforme a l'esprit spec §4.5 ("c'est le TEST qui compte"). Encart
  "Surapprentissage probable" auto-declenche si test < 50% du train.
- **Portefeuille** : etat "actif ignore" jamais avale silencieusement (liste
  explicite avec l'erreur par symbole) ; note de correlation honnete avec
  seuil >0.7 ("la diversification lisse, ne protege pas d'un krach
  systemique") — coherent avec le constat deja documente dans
  `CLAUDE.md` racine.
- **Bandeau pied de page** ("Performances passees ne prejugent en rien...")
  present sur le Rapport (`dashboard.py` footer).
- Aucune valeur `NaN`/`Infinity` brute trouvee : `metrics_format` et
  `dashboard._pf`/`_pct` gerent explicitement NaN → "n/a", inf → "inf"/"∞".

**FAIL localise (2 constats)** :

**(a) Frais Kraken perimes dans l'encart d'honnetete du Labo de stats.**
`trading/stats.py:171-176`, `HONESTY_NOTE` (source UNIQUE partagee CLI+web,
verifiee live sur `/stats`) affirme *"les frais Kraken (0,26%/ordre) pesent
lourd"*. Or `config.py:27-31` fixe `FEE_TAKER = 0.0080` (0,80%) depuis le
correctif BUG-003 (registre `docs/SQA.md`, applique 2026-07-09) — soit un
**facteur ~3x de sous-estimation** dans le texte affiche sur l'ecran meme
dedie a la transparence sur les frais. Les cartes chiffrees (`fees_total`,
`fees_share`) restent EXACTES (calculees depuis les vraies donnees de trade,
confirme live : 974,77 / ~45% affiches correctement) — seule la phrase
d'explication statique est fausse. Vu que le principe n°1 de la spec est
"Honnetete avant tout", c'est le type de defaut le plus genant a laisser
trainer. (P2-2)

**(b) Lien "passer en live (verrouille)" trompeur sur l'Accueil.**
`trading/home_page.py` `_settings_card` (ligne ~104-114) :
```html
<a class='hublink' href='/options'>Options</a>
<span class='disabled-link'>Aide (bientot)</span>
<a class='hublink' href='/options'>passer en live (verrouille)</a>
```
**Deux liens differents pointent tous les deux vers `/options`.** Le second,
libelle "passer en live (verrouille)", ne mene a AUCUN mur de friction (Lot
8 pas encore construit) — il atterrit silencieusement sur la page Options.
C'est exactement le pattern que le reste du code applique correctement
ailleurs pour les fonctionnalites pas encore livrees (`<span
class='...disabled'>...<span class='soon'>bientot</span></span>`, jamais un
lien "actif" vers une mauvaise destination) — ici l'exception rompt la
coherence, et le concept concerne (le live) est justement celui que la spec
traite avec le plus d'exigence de friction/clarte. Aucun danger reel (la
destination est benigne), mais c'est une incoherence de navigation sur le
point le plus sensible de l'app. (P2-1)

---

## 4. Robustesse des etats (lecture du code des `render_*`)

Verifie sur `home_page.py`, `check_page.py`, `stats_page.py`,
`research_page.py`, `compare_page.py`, `optimize_page.py`,
`portfolio_page.py`, `report_page.py`, `research_runners.py` :

- **Etats vides couverts et honnetes** : Accueil ("Aucun paper en cours",
  "Aucune analyse lancee"), Check ("Diagnostic non lance cette session" —
  confirme live), Stats ("Aucune donnee de stats..." + message EXACT levé
  par `load_stats`), Rapport (`render_report_unknown`/`_pending`/`_error`/
  `_cancelled`), Comparer/Optimiser/Portefeuille (formulaire invalide →
  reaffiche avec erreurs + valeurs soumises, jamais de crash).
- **Un seul job a la fois** : `JobBusy` gere sur les 4 ecrans (Backtest,
  Comparer, Optimiser, Portefeuille) via `render_*_busy` (panneau du job en
  cours + choix d'attendre/annuler) — jamais de 2e job silencieux.
- **Messages techniques bruts** : `research_runners.py` capture toute
  exception reseau/donnees et la re-emballe en `ResearchError` avec un
  prefixe FR actionnable ("Donnees indisponibles pour ce symbole/timeframe/
  source. Detail : {exc}"). Le `str(exc)` brut (ex. message ccxt) PEUT
  apparaitre en suffixe — techniquement peu poli mais **jamais de secret,
  jamais de stack-trace** (confirme : `JobManager._run` ne retient que
  `str(exc)`, jamais la trace). Acceptable, pas un defaut bloquant.
- **Traversal `/stats?file=`** : confirme empiriquement (GET reel) que
  `../../../../windows/win.ini` et un nom hors liste blanche retombent tous
  deux proprement sur `paper_stats.csv`, HTTP 200, aucune fuite. Le garde
  `resolve_stats_path` tient en pratique, pas seulement sur le papier.
- **`/job/<id>/status` avec id malforme** (`not-a-valid-id`, pas 32 hex) :
  rejete par la regex AVANT meme d'atteindre `JobManager` → 404 generique,
  confirme empiriquement. Defense en profondeur qui fonctionne reellement.

---

## 5. Cohesion visuelle

**PASS** : pas de faute d'accord/mot anglais errant repere dans le texte FR
lu (hormis l'absence d'accents generalisee, cf. P2-3 ci-dessous, qui n'est
pas une faute de langue mais une question d'orthographe/encodage).

**Findings** :

**(P3-4) Pages d'erreur HTTP brutes, hors coquille de theme.** Toutes les
reponses 404 (`<h1>404</h1>`) et 403 (`<h1>403 - Host non autorise</h1>`,
`<h1>403 - jeton CSRF invalide</h1>`) dans `trading/monitor.py`
(`do_GET`/`do_POST`, plusieurs occurrences de
`self._send_html("<h1>...</h1>", code=...)`) **contournent `page_shell`** :
pas de `<!DOCTYPE>`, pas de `<meta charset>`, pas de nav, pas de theme sombre
— rupture visuelle brutale (texte noir sur fond blanc du navigateur) au
milieu d'une app par ailleurs entierement themee. Confirme live sur
`/this-route-does-not-exist` (404 brut).

**(P3-5) Liens de navigation redondants (breadcrumb vs nav globale).**
Chaque ecran secondaire porte un lien de retour contextuel qui pointe vers
la MEME URL qu'un item de la nav globale : Options "&larr; Retour au
monitoring" (= onglet nav "Monitoring"), Stats "&larr; Monitoring" (idem),
tous les ecrans Recherche "&larr; Nouvelle analyse"/"&larr; Formulaire"
(= onglet nav "Recherche", qui pointe deja vers `/research/backtest`).
Pattern courant et inoffensif (breadcrumb + nav globale), signale uniquement
parce que le perimetre d'audit le demandait explicitement — pas d'action
requise sauf volonte de simplification en Lot 9.

**(P3-6) Badge IN-SAMPLE absent sur `/research/optimize`.** La spec §4.0
liste le badge IN-SAMPLE comme "composant transverse... reutilise partout",
explicitement "sur tout resultat de backtest/optimize/compare". Backtest et
Comparer l'ont (`.in-sample-badge`), **Optimiser non** — ni le HTML
(`render_optimize_done`) ni le CSS de `optimize_page.py` ne definissent
cette classe. Mitige en pratique par le design Train/Test (panneau Test
dominant), mais s'ecarte de la reutilisation de composant prevue par la
spec. Severite basse car l'intention honnete est bien presente sous une
autre forme.

**(P3-7) `/static/chart.umd.min.js` sans en-tete de cache.** Reponse
confirmee sans `Cache-Control` ni `ETag` (205 399 octets, re-telecharges en
entier a chaque page qui embarque un Rapport). Polish de performance, pas
une question de correction.

---

## 6. Ce qui a ete verifie et qui est deja bon (a ne pas re-auditer)

- Routage : tous les statuts HTTP attendus (200/404) confirmes, y compris
  sur les cas limites demandes (route inconnue, job id bidon, job id
  malforme).
- Nav active-state correct sur 100% des ecrans testes.
- Aucun lien mort : le patron `<span class='...disabled'><span
  class='soon'>bientot</span></span>` est applique de facon systematique
  pour toute fonctionnalite non livree (sauf l'exception notee en P2-1).
- Securite formulaire : CSRF present et non-vide sur tous les formulaires
  POST vus ; aucune valeur de cle Kraken presente dans le HTML (`/options`
  confirme "Cles configurees : NON" avec champs `type=password` vides) ;
  wallet = lien sortant uniquement, `target='_blank' rel='noopener'`, vers
  l'URL officielle Kraken.
- Traversal / whitelist `/stats?file=` : tenu empiriquement, pas seulement
  sur le papier.
- Contraste : le theme est globalement TRES bon (la majorite des paires
  testees depassent 7:1-10:1, tres au-dessus du seuil AA) — seul `--muted2`
  echoue (P2-4).
- Couleur jamais seule porteuse de sens sur les ecrans audites.
- Focus clavier natif preserve (aucune suppression CSS trouvee).
- Honnetete : badge in-sample, Buy & Hold, encart correlation, footer
  d'avertissement — tous presents et corrects la ou la spec les exige
  (sauf les 2 ecarts notes en §3).

---

## 7. Liste priorisee pour le Lot 9

1. **(P2)** Corriger `HONESTY_NOTE` (`trading/stats.py:171-176`) : remplacer
   "0,26%/ordre" par la valeur reelle de `config.FEE_TAKER` (0,80%) — idealement
   interpoler la constante plutot que la re-coder en dur, pour que ce type
   d'ecart ne puisse plus se reproduire silencieusement au prochain
   changement de `config.FEE`.
2. **(P2)** Corriger le lien "passer en live (verrouille)" de l'Accueil
   (`trading/home_page.py` `_settings_card`) : soit le desactiver en `<span
   disabled>` + badge "bientot" (coherent avec le reste de l'app tant que
   `/live` n'existe pas), soit le faire pointer vers une ancre reelle une
   fois le Lot 8 livre — jamais vers `/options` sous ce libelle.
3. **(P2)** Restaurer les accents francais dans TOUT le code de rendu web
   (`trading/webui.py`, `monitor.py`, `home_page.py`, `check_page.py`,
   `stats_page.py`, `research_page.py`, `compare_page.py`, `optimize_page.py`,
   `portfolio_page.py`, `report_page.py`, `jobs.py`) — confirme
   systematique par un comptage de caracteres accentues (0 partout, contre
   13 dans `dashboard.py` qui, lui, les a). C'est exactement le gotcha deja
   identifie et corrige dans la maquette (`docs/RAPPORT_WEBAPP_SUITE.md` §6,
   "sur-application de la regle ASCII pur qui ne vaut que pour les .ps1")
   mais jamais reporte sur le code Python de production. Le HTML est en
   UTF-8 (`<meta charset='utf-8'>` present partout) : rien ne l'empeche
   techniquement.
4. **(P2)** Corriger le contraste de `--muted2` (#6b7787) : soit l'eclaircir
   pour atteindre 4.5:1 sur `--bg`/`--panel`, soit **retirer/reduire
   l'`opacity:.55`** sur les elements desactives de nav (qui aggrave le
   probleme jusqu'a 2,08:1) et sur `.barval` (Labo de stats) qui porte une
   donnee chiffree, pas juste un accent decoratif.
5. **(P3)** Ajouter un `<h2>` avant les `<h3>` Train/Test de
   `optimize_page.py` `_tt_panel` (heading hierarchy).
6. **(P3)** Associer un `<label for=...>` au `<select name='file'>` de
   `trading/stats_page.py` `_file_picker_html`.
7. **(P3)** Habiller les pages d'erreur HTTP (404, 403 host, 403 CSRF) avec
   `page_shell` (ou a minima un doctype + charset + theme minimal) au lieu
   de `<h1>...</h1>` brut.
8. **(P3)** Revoir les hauteurs de bouton sous le seuil spec (`.btn-cancel`,
   bouton "Charger" du file-picker, `.nav a.tab`) pour se rapprocher des
   40px cibles (spec §8).
9. **(P3, optionnel)** Ajouter le badge IN-SAMPLE (ou un equivalent
   explicite) sur `/research/optimize` pour une reutilisation stricte du
   composant transverse §4.0.
10. **(P3, optionnel)** `Cache-Control`/`ETag` sur `/static/chart.umd.min.js`.
11. **(P3, informationnel, pas d'action requise)** Liens breadcrumb
    redondants avec la nav globale — a laisser sauf volonte explicite de
    simplification.

---

## Fichiers references dans ce rapport

- `trading/webui.py` (THEME_CSS, `_render_nav`, `research_subnav_html`,
  `job_panel_html`, `serve_static`)
- `trading/monitor.py` (routes GET/POST, pages d'erreur brutes, `do_GET`/
  `do_POST`)
- `trading/home_page.py` (`_settings_card` — lien live trompeur)
- `trading/stats.py` (`HONESTY_NOTE` — frais perimes)
- `trading/stats_page.py` (`_file_picker_html` — label manquant, `.barval`
  contraste)
- `trading/optimize_page.py` (`_tt_panel` — saut de titre, badge in-sample
  absent)
- `config.py` (`FEE_TAKER = 0.0080`)
- `docs/SQA.md` (BUG-003, reference du changement de frais)
- `docs/RAPPORT_WEBAPP_SUITE.md` (§6 — gotcha accents deja documente)
- `docs/UI_UX_WEBAPP_SPEC.md` (§4.0, §8 — composants transverses,
  accessibilite)
