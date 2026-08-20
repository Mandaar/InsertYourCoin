# Enquete, etude & ameliorations — InsertYourCoin

> Carnet **vivant**. Il capitalise la demarche d'enquete (bug / debug / comprehension)
> et tient le backlog d'etude & d'ameliorations. A enrichir a chaque incident ou retour.
> Doctrine source : enquete multifacteur + comprehension par comparaison.

---

## 1. Doctrine d'enquete (appliquee au trading)

Un bug est *un meurtre a elucider, pas un marathon*. On ne corrige jamais a l'aveugle.

- **Etape 0 — s'inspirer du vecu** : avant d'enqueter, consulter le **registre des bugs**
  (`docs/SQA.md` §5) et le journal ci-dessous (§2). Un cas similaire a-t-il deja ete vecu/resolu ?
- **Ne jamais conclure au 1er indice.** Croiser : **chronologie** x **type de message**
  x **surface** (le code suspect tourne-t-il vraiment la ?) x **categorie**
  (reseau / SSL / logique / donnees / alimentation) x **correlation != causalite**.
- **Lire les logs** (`paper_trades.log`, `live_trades.log`) et, si besoin, les logs
  systeme (veille, reboot). **Pas de logs = premier bug a corriger** : on ne diagnostique
  pas sans trace.
- **Comprendre par comparaison** : comparer a une reference / baseline. Exemples :
  l'appel marche-t-il *maintenant* ? quel *type* d'erreur exact ? le volume d'appels
  est-il sous les limites Kraken ? le drawdown vs le buy & hold ?
- **Correction durable, pas contournement** : cause racine -> garde-fou par construction
  (logs typuees, backoff, detection) -> **documente ici**. Une erreur vue 2 fois est la derniere.

## 2. Journal d'enquete (capitalisation)

### Incident #1 — 2026-06-05 — "Erreur recurrente Kraken" (nuit)
- **Symptome** : `kraken GET .../OHLC` repete dans la console ; collecte interrompue
  (~00:18 -> matin) ; le process paper retrouve mort.
- **Hypotheses concurrentes** : (a) refus Kraken / rate-limit ; (b) timeout reseau ;
  (c) plusieurs paper en parallele martelant l'API.
- **Preuves croisees** : aucun log paper (= aveugle) ; Kraken repond normalement au matin ;
  un **seul** process paper ; message tronque **sans** code 429 / "Rate limit" (signature
  d'un *timeout*, pas d'un refus applicatif) ; logs systeme Windows = mise en veille ;
  volume reel = ~2 appels / 5 min (tres sous les limites).
- **Conclusion** : timeouts reseau nocturnes en boucle, **absorbes par le retry** (comportement
  voulu), MAIS **absence totale de logs paper** = le vrai defaut (diagnostic impossible).
  Mort du process = cause externe (veille / arret).
- **Correction durable** :
  - `b9cf6d0` — `describe_error` (classe l'erreur, **detecte un refus Kraken / DDoSProtection**),
    `backoff_seconds` (exponentiel plafonne, plus long si refus), `_trace` (log console **+ fichier**
    `paper_trades.log`, lazy, ne crashe jamais), compteur d'echecs consecutifs, timeout ccxt 10s -> 30s.
  - `42ae373` — dashboard de monitoring (voir l'etat + le journal en direct).
- **Lecon** : *sans logs persistes, on est aveugle.* Tout process long DOIT logger en fichier.

### Incident #0 (rappel) — SSL `CERTIFICATE_VERIFY_FAILED` (Avast)
- Avast intercepte le HTTPS et re-signe les certificats (CA absente de `certifi`).
- Corrige par `truststore` (magasin de certificats de l'OS), **sans** desactiver `VERIFY_SSL`.
  Cf. `CLAUDE.md` (section environnement) + `SETUP.md` (section Antivirus/SSL).

### Incident #2 — 2026-06-07 — `compare`/`walkforward` crashent (UnicodeEncodeError)
- **Etape 0 (vecu)** : variante du gotcha cp1252 deja connu (cote `.ps1`), ici applique a **stdout Python** sur Windows.
- **Cause** : la console Windows encode en cp1252 ; un caractere non-cp1252 dans une sortie `print()` (sigma de Bollinger, accents FR, fleches/emoji du verdict) leve `UnicodeEncodeError`. `walkforward` (le juge) etait inutilisable.
- **Correction durable** : `main.py` force `stdout/stderr` en **UTF-8** (`errors='replace'`). Cf. SQA BUG-004 (+ test garde-fou).

### Resultat d'etude #1 — 2026-06-07 — SMA daily : in-sample flatteur, OOS negatif
- Test (Etape 1 du panel) : `SMA` sur ETH/USD en **daily**, frais 0.40%, ~2 ans d'historique.
- **In-sample** (`compare`) : **+43.8%** vs Buy&Hold **-53.6%** -> semble exceller (sort en death-cross pendant le bear).
- **Hors-echantillon** (`walkforward`, optimise glissant, 4 fenetres) : **-13.6%**, 25% de fenetres profitables -> **verdict : ne pas trader**.
- **Lecon** : l'in-sample ET l'**optimisation** des parametres FLATTENT ; le walk-forward demasque le mirage. Prochain test a faire : `SMA` **50/200 FIGE** (sans optimisation) pour distinguer 'pas d'edge' de 'overfit d'optimisation'.

### Resultat d'etude #2 — 2026-06-08 — SMA 50/200 fige & TSMOM 365 fige (moteur REPARE, frais 0.80%)
- Test : parametres FIGES (zero optimisation), walk-forward 4 fenetres OOS (~1 an), daily, taker futur 0.80%.
- **SMA 50/200 fige** : OOS cumule **+21.4%** MAIS porte par UNE SEULE fenetre (+94.5% en bull) ; les 3 autres flat/perte -> **1/4 profitable** = non robuste (coup concentre, pas un edge). Profil DEFENSIF (sort en bear) a creuser.
- **TSMOM 365 fige** : OOS cumule **-6.6%**, **2/4** fenetres profitables -> pas d'edge net (mais mieux reparti que SMA).
- **Lecon** : aucune pepite ; surtout l'echantillon OOS est **trop court (~1 an, ETH baissier)** pour conclure (cf. AUDIT B12). Le frais 0.80% ne penalise PAS ces strategies (bas turnover) -> la basse frequence est la bonne voie. Pour juger vraiment : **multi-actifs + plus d'historique + holdout + Deflated Sharpe** (= Phase B / harness).

### Resultat d'etude #3 — 2026-06-10 — SMA 50/200 fige MULTI-ACTIFS (harness complet : holdout 20%, slippage, DSR)
- Test : BTC/ETH/SOL daily, params figes, holdout 20% sacre (144 bougies/actif jamais vues), frais 0.80% + slippage 5 bps.
- **Verdict : NON robuste — ne pas trader.** BTC -24.4% / ETH +20.2% / SOL -24.9% (OOS cumule), 1/3 actifs positif, moyenne -9.7%. Le +21.4% d'ETH (etude #2) etait bien un artefact d'actif/periode unique, pas un edge.
- **Limite decouverte (B11 a fonctionne)** : l'API OHLC publique de Kraken ne sert que ~720 bougies par timeframe -> en daily on n'a QUE ~2 ans, quel que soit --days. Pour juger sur un cycle complet il faudra une source d'historique longue (CSV d'archives Kraken, autre API). -> backlog.
- Etat des pistes du panel : SMA 50/200 fige REJETE multi-actifs ; TSMOM 365 deja negatif mono-actif. Prochaines pistes : TSMOM multi-actifs, filtre regime + vol-targeting par-dessus, et SURTOUT plus d'historique avant de re-conclure.

### Incident #3 — 2026-06-10 — process du lanceur morts silencieusement (~1 min apres lancement)
- **Symptome** : paper+monitor demarres par `lancer.py` morts sans trace (consoles vides, 1 seul cycle CSV) ; `--status` les declare orphelins alors que le port 8765 repond encore (squatte par le Preview de l'outil Claude qui avait relance ses propres monitors).
- **Cause racine** : les process lances DEPUIS une commande Bash/PowerShell de la session Claude appartiennent au *job* de cette commande -> ils sont TUES a la fin de la commande, meme "detaches" (DETACHED_PROCESS ne suffit pas face a un Job Object kill-on-close). Preuve inverse : un paper lance via `Start-Process` (hors job) avait survecu 2 jours.
- **Correction durable** : depuis la session Claude, TOUJOURS lancer le long-vivant via `Start-Process` (PowerShell). Le DOUBLE-CLIC utilisateur (`lancer.bat`) n'est PAS affecte (cmd.exe normal, pas de job). Verification de survie = controler les process dans une COMMANDE SEPAREE de celle qui les a lances.
- **Nuance (2e occurrence, meme jour)** : `Start-Process lancer.py` ne suffit PAS -- les petits-enfants Popen de lancer.py meurent aussi (~quelques minutes). Seul le `Start-Process` DIRECT du process final (python main.py paper ...) est prouve (2 jours). Depuis la session : un Start-Process PAR service. La validation du double-clic `lancer.bat` (hors session) reste a faire par l'utilisateur -- attendue OK (pas de job).
- **Lecon** : "le port repond" != "MON service tourne" (un squatteur peut repondre) -- la verification de signature du monitor (FIX 4) et l'identite des PID (FIX 1) existent precisement pour ca, et ont bien fonctionne.

### Resultat d'etude #4 — 2026-06-10 — PREMIER SIGNAL D'EDGE : TSMOM 3/3 et SMA 2/3 sur ~8 ans
- Test : source longue Binance (BTC/ETH depuis 2017-08, SOL depuis 2020-08), params FIGES, holdout 20% sacre (INTACT, --final jamais lance), frais 0.80% + slippage, walk-forward 4 fenetres, DSR.
- **TSMOM 365j : 3/3 actifs positifs** — BTC +118.9% (Sharpe 1.05, DSR 97%), ETH +4.9% (DSR 83%), SOL +308.6% (Sharpe 1.35, DSR 98%). OOS moyen +144%.
- **SMA 50/200 : 2/3 positifs** — BTC +75.9% (DSR 89%), ETH -11.7%, SOL +48.7%. Le verdict "non robuste" de l'etude #3 venait bien de l'echantillon trop court (2 ans baissiers), pas forcement d'une absence d'edge.
- **Nuances d'honnetete (a relire avant toute decision)** : (1) PAS de comparaison Buy&Hold affichee -- sur 2017-2026 le B&H BTC bat probablement ces cumuls en rendement BRUT ; l'edge attendu de TSMOM est le rendement AJUSTE DU RISQUE (Sharpe/drawdown), pas de battre le B&H en absolu. (2) ETH a peine positif (+4.9%). (3) Recherche sur Binance USDT, execution future sur Kraken USD. (4) Periode = 1 cycle et demi seulement. (5) Le HOLDOUT RESTE VIERGE : la validation finale --final = decision explicite de Mandar, UNE seule fois.
- **Prochaines etapes proposees** : comparer Sharpe/DD vs B&H par actif ; couche vol-targeting + filtre regime (panel #3) par-dessus TSMOM ; puis decision --final.

### Resultat d'etude #5 — 2026-07-16 — TSMOM vs BUY & HOLD : crisis-alpha, PAS batteur de marche (rapport : `ETUDE_5_TSMOM_VS_BH.md`)
- Test : TSMOM 365 FIGE, B&H compare sur les MEMES fenetres OOS (walk-forward 4 fen., holdout 20% INTACT, frais 0.80% + slippage, Binance long). Script `scripts/etude5_tsmom.py` (importe les modules, ne modifie aucun code). TSMOM ret du script = identique au CLI (Loi 2 : BTC +55.9%, ETH +98.2%, SOL +264.6%).
- **Q1 — TSMOM bat-il le B&H ? NON de facon fiable.** DD max reduit 3/3 (la "moins de casse" est REELLE : BTC -53 vs -77, ETH -57 vs -79, SOL -53 vs -60), mais rendement ET Sharpe battus seulement 2/3 (BTC, ETH). Sur **SOL, B&H ecrase TSMOM : +1317.8% vs +264.6%** (Sharpe 1.66 vs 1.12). Decompo BTC : tout l'avantage vient de la fenetre 2022 (TSMOM en CASH 0% vs B&H -55%) ; en bull il RETARDE (+43% vs +122%). **Edge = crisis-alpha (evitement de krach), pas generation de rendement.** Les gros cumuls OOS de l'etude #4 sont surtout du BETA.
- **Q2 — Sensibilite lookback (anti-data-mining) : ELEVEE.** Seul 365 donne 3/3 positif ; 180 -> 2/3 (BTC -25.7%), 540 -> 1/3 (BTC -32.1%, ETH -39.9%). Que 365 (valeur canonique) soit pile le pic = signal de FRAGILITE a documenter, pas parametre a selectionner. Les DSR affiches (n_trials=1) ne deflatent PAS l'exploration des 3 lookbacks.
- **Q3 — Temoin SMA 50/200 : meme conclusion en plus faible** (bat B&H en rendement sur ETH seul, DD reduit BTC/ETH, ecrase par SOL). Profil "reducteur de DD, pas batteur de marche" = STRUCTUREL au trend-following.
- **Caveats persistants** : comparaison regime-dependante (split 50/50 fait demarrer l'OOS SOL au creux absolu -> B&H imbattable) ; instabilite forte des chiffres par actif (+36 bougies entre #4 et #5 ont fait passer ETH de +4.9% a +98.2%, moyenne restant ~+140%) ; USDT vs USD ; **holdout TOUJOURS VIERGE** (--final = decision de Mandar, une fois).
- **Reco** : positionner TSMOM comme outil de PRESERVATION du capital (garde-fou n.2), pas comme "bat le marche". Prochaine brique OOS : filtre regime + vol-targeting (panel #3) par-dessus, valide au Sharpe/DD hors-echantillon, avant tout --final.

### Resultat d'etude #6 — 2026-08-20 — PAPER SERVEUR 11 JOURS : le signal gagne brut, les frais mangent tout (le "palier" est arithmetique)
- Donnees : export complet du paper eunivers (3166 cycles 5m, 2026-08-09 -> 2026-08-20, SMA/ETH-USD, fichier fourni par Mandar : `EUnivers/home/default/paper_stats.csv`). Outil natif `main.py stats --file` + decomposition pandas.
- **Decomposition MESUREE** : equity -35.30% (DD max reel -43.17% — le -5.08% du dashboard etait le DD *intra-session*, etiquette corrigee commit 8d72e59). 39 allers-retours en 11 jours (detention mediane 3.3 h). **Frais 4 707 $ = 47.1% du capital initial** ; PnL net -3 530 $ ; **PnL BRUT hors frais : +1 177 $ (+11.8%)**. Reussite 5% (37/39 ventes perdantes ; seules les 2 TAKE-PROFIT gagnent : +530 $, +477 $). Temoin B&H ETH sur la periode : +18.3%. **Le signal ne se trompe pas de sens — il paie 0.80% par cote, 7 fois par jour.** Confirmation en conditions reelles de l'etude #1.
- **LE PALIER (arithmetique pure, ne depend d'aucune donnee)** : mouvement de prix minimal pour rembourser un aller-retour = `1/(1-fee)^2 - 1` -> **+1.62% par trade en taker (0.80%/cote)**, **+0.80% en maker (0.40%/cote)**. Mesure sur les 39 trades serveur : mouvement capture **mediane -0.03%**, moyenne +0.52% ; **2/39 seulement au-dessus du palier taker**. Le 5m fait jouer un jeu dont le ticket d'entree est 1.62% a une strategie qui capture ~0%.
- **Illustration bande morte** (in-sample sur les 11 jours, simulateur VALIDE par reproduction : k=0 -> -35.5% / 37 A/R vs -35.3% / 39 reels) : k=0.10% -> 18 A/R, -14.7% ; k=0.25% -> 8 A/R, -1.0% ; k=0.50% -> 1 A/R, +18.0% (~B&H). Le mecanisme est net : la bande tue le churn, les frais passent de 4 498 $ a 239 $, le brut reste ~stable. ⚠️ **Choisir k sur ces 11 jours = seuil derive des points testes (interdit)** — l'illustration montre le MECANISME, pas la valeur.
- **Reco** : (1) le k legitime se fixe par le palier de frais (>= 1.62%, marge 2x -> viser des mouvements attendus >= 3%) puis se VALIDE au walk-forward sur historique long Binance, en jugeant NET de frais et la robustesse SUR TOUTE la grille de k (pas le pic) ; (2) parametre `band` a ajouter a la strategie SMA (petit lot, avec tests) ; (3) piste complementaire : ordres maker (fee 0.40% -> palier /2) — a etudier avec le risque de non-execution ; (4) converge avec `docs/design/MODE_ADAPTATIF_SPEC.md` : en journalier, ~2 trades/mois -> ~3.2%/an de frais au lieu de 47% en 11 jours.

### Resultat d'etude #6bis — 2026-08-20 — bande anti-churn IMPLEMENTEE + grille walk-forward (le lot de l'etude #6)
- Implementation : `SMACrossover(fast, slow, band)` -- `band` = MARGE en multiples du cout d'aller-retour (`round_trip_cost()`, ancre sur `config.FEE` : si les frais changent, le seuil SUIT ; regle user "pas des delais dans le marbre mais des marges"). Hysteresis : ACHAT si ecart > seuil, VENTE si ecart < -seuil, zone neutre = on garde l'etat. `band=0` = comportement historique bit-identique (teste). Chaque decision est journalisee en clair dans le paper ("TEST : ecart -0.30% vs marge 2.43% -> zone neutre", verifie en runtime reel sur Kraken). Plomberie : `--params "k=v,..."` sur backtest/paper/live (meme format que `--fixed`), `PAPER_PARAMS` dans les deux compose (defaut `band=1.5`). 707+7 tests verts.
- **Grille walk-forward GELEE AVANT les runs** (bands {0, 0.5, 1, 1.5, 2}, SMA 50/200 1d fige, BTC/ETH/SOL, Binance ~2900j, holdout 20% intact, frais 0.80%+slippage). Resultats OOS cumules :
  BTC : +73.9 / +72.6 / +80.5 / +89.6 / +54.5 -- SOL : +47.4 / +50.8 / +103.3 / +83.0 / +92.3 -- ETH : -35.1 / -43.9 / -42.8 / -39.5 / -39.1.
- **Lecture honnete (toute la grille, pas le pic)** : la bande NE DEGRADE PAS les configs profitables (BTC/SOL stables-a-mieux sur toute la grille) ; ETH est negatif AVEC ou SANS bande (et s'est degrade depuis l'etude #4 : -11.7% -> -35.1% avec 2 mois de donnees en plus -- l'instabilite par actif deja documentee). En 1d, peu de trades -> l'effet frais de la bande y est marginal ; **sa vraie cible est le churn intraday, non validable en OOS long (pas d'historique 5m)** -> le FORWARD TEST serveur est le juge du 5m.
- **Config serveur retenue (A/B propre, une seule variable)** : ETH/5m/SMA 20/50 inchanges, `band=1.5` ajoute. Le 1.5 est ARITHMETIQUE (plancher de remboursement +1.62% x 1.5 de marge = declenchement a ~2.43%), PAS calibre sur les 11 jours (V3 respectee). Baseline de comparaison : les 11 jours a band=0 (39 A/R, frais 47%, -35.3%). Criteres du forward test, poses d'avance : ordres/jour en chute franche, frais/semaine ~nuls hors vrais mouvements, et le journal doit montrer des refus motives ("marge non atteinte").

## 6. Backlog technique (issu des reviews du 2026-06-10)
- **Source d'historique LONGUE** (limite API Kraken ~720 bougies/timeframe) : CSV d'archives Kraken ou autre source, pour juger sur >= 1 cycle complet. PRIORITAIRE pour la recherche d'edge.
- `lancer.py --status` : faux negatif transitoire sur le port juste apres le demarrage (course au bind, ~1s) -> petit retry possible.
- Holdout : ancrer la frontiere sur une DATE explicite + journaliser chaque --final (registre des validations consommees).
- `psutil` installe et requis -> protection maximale du --stop active (sans lui : fallback image python* seulement).

## 3. Etude du logiciel — quoi observer

Donnees : `paper_stats.csv` (1 ligne / cycle), `paper_trades.log` (events + erreurs typuees),
`paper_state.json` (etat). Synthese : `python main.py stats`.

- **Fiabilite / robustesse** : frequence et **type** des erreurs ; trous de cycles
  (le process a-t-il tenu ?) ; le backoff s'est-il declenche ?
- **Economique (honnetete)** : **frais cumules vs P&L** (les 0,26 %/ordre dominent-ils ?) ;
  nombre de trades ; win-rate ; drawdown max.
- **Comportement de la strategie** : temps en position vs cash ; faux signaux
  (achat -> stop rapide) ; le signal a-t-il un lien avec la perf ?
- **Regle d'or** : aucune conclusion de rentabilite depuis le paper seul.
  Le **walk-forward** (hors-echantillon) reste le seul juge.

## 4. Backlog d'ameliorations (calme, priorise)

- **Court terme** : analyser le week-end (cf. §3) ; **relance auto** du paper s'il meurt
  (tache planifiee / wrapper) ; choix anti-veille permanent vs run "PC allume seulement".
- **Moyen terme** : **filtre de tendance long terme** (ne trader que dans le sens du marche) ;
  route `/data` JSON pour le dashboard ; ponderation par risque du portefeuille.
- **Recherche d'edge** : tester d'autres strategies / parametres, **toujours** valides au
  walk-forward (jamais sur le backtest in-sample).
- *Discipline* : une amelioration = un benefice **mesurable** vise (drawdown, frais, robustesse).
  Pas de complexite gratuite.

## 5. Checklist "retour" (apres le week-end)

- [ ] `python main.py stats` -> rendement, drawdown, win-rate, **part des frais**, ventilation heure/jour.
- [ ] Parcourir `paper_trades.log` -> erreurs (type, frequence), trous de cycles, backoff.
- [ ] Le process paper a-t-il tenu tout le week-end ? Sinon : quand / pourquoi -> noter en §2.
- [ ] Relancer le dashboard (preview) si Claude a ete ferme entre-temps.
- [ ] **Reactiver la veille** : `powercfg /change standby-timeout-ac 30`.
- [ ] Capitaliser tout retour / incident dans §2.
