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
- **Lecon** : "le port repond" != "MON service tourne" (un squatteur peut repondre) -- la verification de signature du monitor (FIX 4) et l'identite des PID (FIX 1) existent precisement pour ca, et ont bien fonctionne.

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
