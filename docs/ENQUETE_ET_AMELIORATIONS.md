# Enquete, etude & ameliorations — InsertYourCoin

> Carnet **vivant**. Il capitalise la demarche d'enquete (bug / debug / comprehension)
> et tient le backlog d'etude & d'ameliorations. A enrichir a chaque incident ou retour.
> Doctrine source : enquete multifacteur + comprehension par comparaison.

---

## 1. Doctrine d'enquete (appliquee au trading)

Un bug est *un meurtre a elucider, pas un marathon*. On ne corrige jamais a l'aveugle.

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
