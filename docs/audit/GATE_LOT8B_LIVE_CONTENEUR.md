# GATE INDÉPENDANTE — Lot 8B (live production-ready en conteneur)

> Acteur : `qa-tester` (gate indépendante, V3 — je n'ai pas produit ce code, je le
> juge). Référentiel gelé : `docs/design/LOT8B_LIVE_CONTENEUR_SPEC.md` (§0-§9) +
> `docs/design/LOT8_LIVE_SPEC.md` §6 (N1-N12, en vigueur). Méthode : lecture du
> code cité dans le brief, ligne par ligne, contre chaque critère de la checklist
> §8, exécution complète de la suite `pytest`, revue des diffs git réels (pas des
> résumés de commit). Aucun commit, aucune modification de code effectuée.
>
> Verdict rendu : **NO-GO**. Un FAIL P0 — précisément le mode de défaillance que
> ce lot devait éliminer.

---

## FAIL — 1 (P0, bloquant)

### `LiveTrader.reconcile()` existe, est testé en isolation, mais N'EST JAMAIS
### APPELÉ dans le chemin d'exécution réel. Le danger n°1 nommé par la spec
### (position ouverte sans stop après restart) N'EST PAS CORRIGÉ.

**MESURÉ.** Le chemin réel d'exécution d'un live conteneurisé est :

```
docker-compose.live.yml  command: python -u /app/main.py live-run
  -> main.py cmd_live_run (main.py:372-381)
  -> trading/live_supervisor.py run_supervisor() -> supervisor_tick()
  -> trading/live_control.py start_live_process() -> spawn_live_detached()
     (spawne un SUBPROCESS : "main.py live [--execute]")
        -> main.py cmd_live (main.py:260-281)
           -> LiveTrader(KrakenExchange(), ..., dry_run=dry_run, **_bt_kwargs(args)).run()
```

`main.py::cmd_live` (l.260-281) est **textuellement identique** avant/après ce
lot — confirmé par `git diff main.py` : le hunk qui ajoute le code Lot 8B
commence à `@@ -280,6 +281,106 @@`, c'est-à-dire **après** la dernière ligne de
`cmd_live`. Zéro caractère de `cmd_live` n'a changé.

`cmd_live` construit `LiveTrader(...)` et appelle **directement `.run()`** — il
n'appelle **jamais** `.reconcile()`. Or `LiveTrader.reconcile()`
(`trading/live_trader.py:103-157`) est la **seule** méthode qui restaure
`entry_price`/`peak`/`entry_ts`/`entry_cost` depuis `live_state.json` au
démarrage. Sans elle, `LiveTrader.__init__` laisse `entry_price = None`
(`live_trader.py:57`), **par construction** (le docstring du module le dit
explicitement : *« `reconcile()` est appelée EXPLICITEMENT par l'appelant
(superviseur/CLI), APRÈS la construction et AVANT `run()` — jamais dans
`__init__` »*, `live_trader.py:19-22`) — et `_risk_overlay`
(`paper_trader.py:159-160`, hérité tel quel par `LiveTrader`) sort
**immédiatement** dès que `entry_price` est faux :

```python
ep = self._entry_price()
if not (self._is_invested(price) and ep):
    return desired, None          # <- AUCUN stop, AUCUN trailing
```

**J'ai vérifié qu'aucun autre appelant n'existe.** `grep -rn "reconcile"` sur
tout le dépôt (hors doc/tests) ne retourne que :
- `trading/live_trader.py:103` — la définition de la méthode ;
- `tests/test_live_reconcile.py` — 8 tests qui appellent `lt.reconcile()`
  **directement sur l'objet `LiveTrader`**, jamais via `cmd_live` ni via le
  superviseur ;
- `docs/DEPLOY_DOCKER.md:383` — une **affirmation documentaire fausse** (voir
  ci-dessous).

`trading/live_supervisor.py` ne construit **jamais** de `LiveTrader` — il
spawne un **process séparé** (`spawn_live_detached`, patron délibéré pour
isoler les clés du process réseau-facing, spec §3.4) et ne peut donc, par
construction, pas appeler `reconcile()` lui-même : cette responsabilité
retombe **exclusivement** sur `cmd_live`, qui ne l'exerce pas.

**Conséquence concrète (scénario h du brief, dérivé) :** `docker compose stop
live` / crash / OOM-kill avec une position ouverte → Docker relance le
conteneur (`restart: unless-stopped`) → le superviseur relit le marqueur
`armed.json` (toujours présent, mode=reel) → il respawn `main.py live
--execute` → ce nouveau process démarre avec `entry_price=None` → **AUCUN
stop-loss, AUCUN trailing-stop, AUCUN take-profit ne peut se déclencher**
jusqu'à ce qu'un signal de STRATÉGIE (pas de risque) ferme la position. C'est
très exactement le « danger n°1 » formulé en toutes lettres au §0ter de la
spec elle-même — celui que toute la §1 (persistance/reconciliation) devait
éliminer.

**Aggravant — la documentation affirme le contraire du code.**
`docs/DEPLOY_DOCKER.md:381-384` :

> « Au redémarrage (`start`/`up -d`), le superviseur relit l'état persisté et
> **reconcilie** avec Kraken avant de reprendre (cf. workstream A —
> `LiveTrader.reconcile()`, spec §1.4) — ce n'est **pas** une liquidation,
> seulement une pause. »

Cette phrase décrit un comportement **qui n'existe pas dans le code livré**.
Un opérateur qui lit cette doc croira, à raison de sa lecture, que la
reprise est sûre. C'est un P0 aggravé par un P1 documentaire (fausse
assurance de sécurité).

**Ce qui EST correct** (pour cadrer précisément la faute, ne pas la noyer) :
la persistance elle-même fonctionne — `_save_state()` est bien appelée à
chaque mutation (`_set_peak`, achat, vente — `live_trader.py:177,218,242`),
en écriture atomique (`tmp` + `os.replace`, `live_trader.py:99-101`), sans
clé ni solde (vérifié par `test_live_state_sans_cle_ni_solde`). La méthode
`reconcile()` elle-même, **prise isolément**, implémente correctement la
table de vérité à 4 cas de la spec §1.4 (les 8 tests de
`tests/test_live_reconcile.py` passent et couvrent chaque branche). **Le
défaut n'est pas dans la logique de reconciliation — il est dans son
câblage : elle n'est reliée à rien.**

**Correctif minimal identifiable (pour information, non appliqué ici — hors
mandat de gate) :** insérer un appel `.reconcile()` entre la construction et
`.run()` dans `cmd_live` (main.py:280-281) — un test d'intégration devrait
alors vérifier que `cmd_live` appelle bien `reconcile()` avant `run()` (ce qui
n'existe dans AUCUN test actuel : voir C13 ci-dessous).

**Statut : MESURÉ** (lecture directe du code + `git diff` + `grep` exhaustif
+ les 8 tests de `test_live_reconcile.py` relus un par un).

---

## FAIL — 2 (C13, bloquant par construction de la spec elle-même)

### La garde C1 (reconciliation au démarrage) n'a AUCUN test qui l'exerce dans
### son chemin d'exécution réel — seulement la fonction prise isolément.

Le plan de tests §7 promet 8 tests « Persistance & reprise ». Les 8 existent
(`tests/test_live_reconcile.py`) et testent `LiveTrader.reconcile()` en
l'appelant **directement sur l'instance**. **Aucun** ne teste que `cmd_live`
(le point d'entrée réellement exécuté par le superviseur) appelle
`reconcile()`. Un test d'intégration minimal — patcher `LiveTrader.reconcile`
avec un espion, appeler `cmd_live(args)`, vérifier que l'espion a été appelé
une fois avant `run()` — **n'existe nulle part** dans les 5 fichiers de tests
Lot 8B. Par la définition même de la spec (§8, C13 : *« Une garde de §8/§7
sans test de non-régression → bug ouvert par définition »*), cette lacune de
test est elle-même un finding séparé, indépendamment du FAIL-1 : même si
quelqu'un avait câblé l'appel correctement, rien dans la suite ne l'aurait
protégé d'une régression future.

**Statut : MESURÉ** (les 5 fichiers de tests Lot 8B relus intégralement,
`grep "reconcile"` sur `tests/`).

---

## MARGINAL — 1

### « Position ouverte NON GÉRÉE » ne s'affiche pas quand le marqueur est
### encore armé mais qu'aucun enfant ne tourne réellement (clés absentes /
### échec de spawn).

`trading/live_page.py::render_live_container` (l.556-563) :

```python
non_geree_html = ""
if live_state and live_state.get("invested") and (armed is None or stop_requested_flag):
    non_geree_html = ("...POSITION OUVERTE NON GÉRÉE...")
```

Le déclencheur est `armed is None` (désarmé) **ou** `stop_requested_flag`.
Il ne couvre PAS le cas où `armed` reste présent (mode=reel) mais où le
superviseur est en `erreur_cles` ou `erreur_spawn` (clés retirées/invalidées
après l'armement, ou spawn qui échoue en boucle) — dans ces deux cas, un
enfant réel ne tourne PAS, la position reste sans trailing/stop, et pourtant
la bannière rouge « NON GÉRÉE » ne s'affiche jamais. **Confirmé par le test
existant** `test_route_live_position_geree_pas_de_banniere_quand_arme`
(tests/test_live_server.py:641-651) : ce test pose `armed` présent et
n'exige explicitement **aucune** bannière, sans jamais vérifier qu'un enfant
tourne réellement.

Le statut du superviseur (« ERREUR — clés API absentes ») reste néanmoins
visible dans la carte « Superviseur » de la même page (§3.3 n'est donc pas
totalement bafouée — l'opérateur attentif verra l'ERREUR, juste pas la
bannière de risque dédiée). Ce n'est pas un des 13 critères C1-C13 nommés
littéralement, mais c'est un écart direct à l'exigence §3.3 de la spec
(*« si l'état dit investi:true mais qu'aucun process live n'est détecté
[…], la position est non protégée […] Jamais masquer cet état »*) et une
zone grise M9. Sévérité : ne bloque pas le GO à elle seule, mais mérite
correction avant mise en production réelle (ajouter la condition
`sup_status and sup_status.get("status") in ("erreur_cles", "erreur_spawn")`).

**Statut : MESURÉ** (code + test relus).

---

## MARGINAL — 2

### L'hypothèse spec §5 (« clés invalides → l'enfant CRASH ») est fausse au
### regard du code réel — la boucle `_Trader.run()` avale TOUTE exception.

`trading/paper_trader.py::_Trader.run()` (l.194-223), hérité tel quel par
`LiveTrader`, encapsule tout le corps du cycle dans :

```python
try:
    ...
except KeyboardInterrupt:
    break
except Exception as e:
    ... backoff ... time.sleep(wait); continue
```

Une erreur d'authentification Kraken (`ccxt.AuthenticationError`, levée par
`fetch_balance()`/`fetch_ohlcv()` sur des clés invalides ou révoquées) est un
`Exception` ordinaire : elle est **capturée**, journalisée
(`live_trades.log`, visible dans le Journal `/live`), suivie d'un `sleep` et
d'un `continue` — **le process ne crashe jamais** ; il boucle indéfiniment
avec un backoff plafonné à 600 s (`backoff_seconds`, `paper_trader.py:59-67`).

Conséquence : le superviseur voit `is_our_process(...) == True` en
permanence (le PID vit), écrit `live_status = "en_cours"` — **alors que
l'enfant ne fait plus rien d'utile depuis l'invalidation des clés**. La page
`/live` affichera « En cours » (rassurant) et non une erreur explicite au
niveau du superviseur ; seul le Journal (tail de `live_trades.log`) porte le
symptôme, noyé dans les lignes de cycle normales. Ce n'est pas un `C8`
strict au sens littéral (l'échec N'EST PAS silencieux — il est journalisé),
mais l'assertion de la spec elle-même (§5, *« Clés invalides […] → l'enfant
crash sur la 1ère `fetch_balance` »*) ne décrit pas le comportement réel du
code livré, et le statut superviseur affiché (« En cours ») est trompeur
dans ce cas précis.

**Statut : MESURÉ pour le mécanisme de capture (lecture directe de
`_Trader.run()`) / DÉRIVÉ pour la conséquence sur `live_status` (pas
reproduit en environnement réel Kraken, cohérent avec le code lu).**

---

## Checklist C1–C13 (Lot 8B)

| # | Critère | Statut | Preuve |
|---|---|---|---|
| **C1** | Reprise aveugle (pas de persistance, ou reprise sans restaurer le trailing/stop) | **FAIL** | Voir FAIL-1. La persistance existe ; la restauration au démarrage (`reconcile()`) n'est jamais invoquée dans le chemin réel. `main.py:280-281`, `trading/live_trader.py:19-22,103-157`. |
| **C2** | État prime sur l'exchange | **N/A (subsumé par C1)** | Aucune reconciliation n'ayant lieu, ni l'état ni l'exchange ne « priment » — le code démarre nu. Le défaut relève de C1, pas d'un choix erroné entre état et exchange. |
| **C-BUG15** | Plusieurs `live --execute` sur le même compte | **PASS** | Web : `_live_start_lock` (monitor.py:1025, séquence identité→consommation nonce→spawn→pid en un seul bloc, l.1526,1595) reproduit et testé par `test_route_live_start_concurrence_un_seul_spawn_reel` (tests/test_live_server.py:337). Superviseur : `_spawn_lock` (live_supervisor.py:38,127) + `is_our_process` (jamais `pid_alive`) avant spawn, testé par `test_tick_un_seul_enfant_anti_toctou`. |
| **C3** | Marqueur `reel` sans phrase / sans TTY / écrit par le web ou le superviseur | **PASS** | Seul `cmd_live_arm` (main.py:310-357) écrit `armed.json` mode=reel, après `input()` == phrase exacte. `write_armed_marker` n'est appelé nulle part ailleurs (`grep` confirmé : monitor.py et live_supervisor.py ne l'appellent jamais). EOF sans TTY → `EOFError` non intercepté → aucun marqueur (`test_cli_live_arm_sans_tty_eof_aucun_marqueur`). |
| **C4** | Démarrage accidentel (ordres réels sans marqueur `reel` valide) | **PASS** | `read_armed_marker` renvoie `None` si `mode` ∉ {reel,dry} (`live_control.py:336-344`, `test_read_armed_marker_absent_ou_invalide`). `supervisor_tick` ne spawn qu'après lecture d'un marqueur valide. |
| **C5** | Web mal cloisonné (start non neutralisé, ou stop non fonctionnel) | **PASS** | `_live_arm_post`/`_live_start_post` testent `_live_container_disabled()` **en première ligne**, avant tout parsing (monitor.py:1459,1497) ; `_live_stop_post` reste actif en conteneur (branche dédiée, monitor.py:1631-1634). Testé par `test_route_live_arm_refuse_en_conteneur_aucun_nonce`, `test_route_live_start_refuse_en_conteneur_reel_et_dry_avant_tout_spawn`. |
| **C6** | Arrêt cosmétique cross-namespace (`terminate_pid` appelé en conteneur) | **PASS** | `_live_stop_post` en conteneur écrit sentinelle + désarme, **n'appelle jamais** `terminate_pid` (monitor.py:1631-1634, confirmé par grep : `terminate_pid` n'apparaît que dans la branche `else` locale, l.1644). Testé par `test_route_live_stop_conteneur_ecrit_sentinelle_et_desarme_sans_terminate_pid`. |
| **C7** | Clés mal montées (paper/monitor, non-ro, argument/env de l'enfant) | **PASS (code) / À CONFIRMER SUR DEBIAN** | `docker-compose.live.yml:44-48` : `.env` monté `:ro` sur le service `live` **uniquement** ; ni `docker-compose.yml` ni `docker-compose.eunivers.yml` (base) ne montent `.env` sur `paper`/`monitor` (confirmé par lecture des 3 fichiers). `build_live_command` ne passe jamais de clé en argument (`live_control.py:178-209`, testé `test_build_live_command_ne_contient_jamais_de_cle`). `spawn_live_detached` n'injecte aucun `env=` custom (hérite l'environnement du superviseur, qui n'a lui-même pas les clés en variables d'env — elles vivent dans `.env`, lu par `dotenv` via `config.py`). **Non exécutable ici** (pas de Docker sur cette machine) : le merge Compose 3-fichiers (`environment:` du service `monitor` étendu par l'overlay) et la résolution effective de `load_dotenv()` depuis `/app/.env` avec `working_dir: /data` restent **à valider sur le Debian réel** — voir note dédiée en fin de rapport. |
| **C8** | Échec silencieux des clés (absentes ou invalides) | **PASS (absentes) / MARGINAL (invalides)** | Absentes : `keys_configured()` testé avant spawn, statut `erreur_cles` explicite + backoff 30s (`live_supervisor.py:118-125`, `test_tick_cles_absentes_erreur_explicite_pas_de_spawn`). Invalides : voir MARGINAL-2 — pas silencieux (log dans le journal) mais le statut superviseur reste trompeur (« en_cours »). |
| **C9** | Arrêt qui liquide (vente sur stop web/disarm/SIGTERM) | **PASS** | `grep` exhaustif : `trading/live_supervisor.py` et `trading/live_control.py` (chemins d'arrêt) ne contiennent **aucun** appel à `create_market_sell`/`create_market_buy`/`fetch_balance`/`ccxt` — confirmé par grep dédié, 0 résultat sur les deux fichiers. `_terminate_confirmed_child` ne fait que `terminate_pid` + nettoyage de fichiers. Testé par `test_tick_sigterm_meme_geste_que_sentinelle` (garantie « par absence de mécanisme, pas par un `if` », commentaire du code lui-même, live_supervisor.py:214-217). |
| **C10** | Plafonds surchargeables en conteneur | **PASS** | `build_live_command` (live_control.py:178-209) ne construit **aucun** flag `--max-*` (le parser `live` de `main.py` n'en expose aucun, confirmé par lecture de `build_parser()` l.608-611). Les plafonds restent lus de `config.py` par `LiveTrader._rebalance`, dans l'image, changeables uniquement par rebuild. |
| **C11** | Désarmement inefficace | **PASS (par lecture de code) / test dédié incomplet** | `supervisor_tick` : `if stop or marker is None: _terminate_confirmed_child(root)` — la branche s'exécute que ce soit un `stop_request` OU une simple absence de marqueur (`live-disarm` direct). Le code est correct par construction (branche partagée). **Mais** aucun test ne pose explicitement « pid file présent + `live-disarm` (marqueur retiré SANS stop_request) + tick → enfant terminé » : les tests existants couvrent soit « marqueur absent, aucun pid » (`test_tick_desarme_aucun_spawn`) soit « stop_request posé » (`test_tick_sentinelle_termine_enfant_et_desarme`), jamais la combinaison exacte du scénario `live-disarm` CLI sur un enfant déjà vivant. Gap de couverture (C13-adjacent), pas un défaut de comportement observé. |
| **C12** | Régression du paper ou du live local quand les flags/fichiers sont absents | **PASS** | `test_paper_control_independant_du_flag_live`, `test_route_live_local_flux_nonce_inchange_sans_flag` : PASS. `_live_container_disabled()` lit `os.environ.get("IYC_DISABLE_LIVE_CONTROL", "")` — absent par défaut sur `docker-compose.yml`/`docker-compose.eunivers.yml` de base (confirmé : la variable n'apparaît QUE dans `docker-compose.live.yml`). `cmd_live` textuellement inchangé (`git diff` vérifié). |
| **C13** | Garde sans test | **FAIL** | Voir FAIL-2 (C1/reconcile sans test d'intégration) et le gap de C11 ci-dessus (désarmement direct sur enfant vivant, non testé explicitly). |

---

## Checklist N1–N12 (Lot 8, en vigueur)

Ces gardes sont portées par du code **non modifié** par ce lot (le chemin
local, `IYC_DISABLE_LIVE_CONTROL` absent, reste inchangé — confirmé C12) ou
étendues de façon strictement additive (refus serveur AVANT toute logique
locale). Aucune régression détectée.

| # | Critère | Statut | Preuve |
|---|---|---|---|
| N1 | Garde uniquement en JS | **PASS** | Aucun JS dans `live_page.py` ; tous les refus (§C5) sont serveur, avant lecture du form. |
| N2 | Reel en un seul round-trip | **PASS** | Chemin local inchangé (nonce arm→start). Chemin conteneur : `live-arm` (interactif) → marqueur → superviseur (2 étapes distinctes, séparées dans le temps). |
| N3 | Dry-run pas par défaut | **PASS** | `resolve_execute` : `False` sauf `mode=="reel"` exact (`live_control.py:71-75`). |
| N4 | Chemin qui contourne les plafonds | **PASS** | Voir C10. |
| N5 | Phrase non exacte | **PASS** | `phrase_ok` : comparaison stricte `.strip() == PHRASE_CONFIRMATION` (`live_control.py:78-84`), identique CLI. |
| N6 | Clés exposées | **PASS** | Voir C7. |
| N7 | Live dans la nav / lanceur capable de live | **PASS** | `lancer.py` non modifié par ce lot (aucun diff sur ce fichier — confirmé par `git status`) ; `assert_paper_only` intact. |
| N8 | Boucle live dans JobManager/thread serveur | **PASS** | Architecture process détaché inchangée + superviseur = process séparé dédié (conforme §3.1 rejeté ailleurs). |
| N9 | « Arrêter » cosmétique | **PASS** | Voir C6 (conteneur) ; local inchangé. |
| N10 | Re-validation manquante au start | **PASS** | Chemin local inchangé (`_live_prereq()` rappelé à `_live_start_post`, monitor.py:1559). |
| N11 | VERIFY_SSL touché | **PASS** | `config.py:61` : `VERIFY_SSL = True`, aucune option UI ne le référence (aucun résultat `grep VERIFY_SSL` hors `config.py`). |
| N12 | Couverture de test absente | **FAIL (hérité de C13)** | Voir FAIL-2. |

---

## Scénarios d'attaque / de panne (a → k)

| # | Scénario | Verdict | Ligne(s) qui décide(nt) |
|---|---|---|---|
| a | POST `/live/start` forgé, `IYC_DISABLE_LIVE_CONTROL=1` | **PASS** | `monitor.py:1497-1501` (refus avant tout parsing) + `test_route_live_start_refuse_en_conteneur_reel_et_dry_avant_tout_spawn`. |
| b | POST `/live/arm` forgé, flag actif | **PASS** | `monitor.py:1459-1463` + `test_route_live_arm_refuse_en_conteneur_aucun_nonce`. |
| c | `/live/stop` fonctionne sans `terminate_pid` cross-namespace | **PASS** | `monitor.py:1631-1634` + `test_route_live_stop_conteneur_ecrit_sentinelle_et_desarme_sans_terminate_pid`. |
| d | Marqueur forgé/copié à la main (mode invalide, champs manquants) | **PASS (mode invalide) / MINEUR (champs manquants)** | `read_armed_marker` refuse tout mode ∉ {reel,dry} (`test_read_armed_marker_absent_ou_invalide`). Un marqueur `mode="reel"` avec `symbol` manquant/vide **passerait** la validation de forme et ferait spawn un `main.py live --execute --symbol ""` qui échouerait au premier appel Kraken (capturé par le `except Exception` de `_Trader.run()`, boucle sans crash — cf. MARGINAL-2) : pas d'ordre erroné, mais pas nettement testé non plus. Nécessite un accès disque hôte déjà équivalent à `live-arm` — pas une élévation de privilège nouvelle. |
| e | `live-arm` sans TTY (EOF) | **PASS** | `test_cli_live_arm_sans_tty_eof_aucun_marqueur` — `EOFError` propagée, aucun marqueur. |
| f | Deux `supervisor_tick()` concurrents | **PASS (par conception mono-thread) / non testé en concurrence réelle** | `run_supervisor()` est une boucle **mono-thread** (`live_supervisor.py:184-222`) : la concurrence entre deux `tick()` n'existe pas en usage réel (un seul superviseur par conteneur). `_spawn_lock` documente l'invariant pour un futur thread annexe mais n'est jamais exercé par un test multi-thread (contrairement à l'équivalent web `_live_start_lock`, lui testé avec 2 vrais threads). Le vrai risque BUG-015 (web) EST testé en concurrence réelle. |
| g | PID recyclé | **PASS** | `test_tick_ne_tue_pas_pid_non_confirme` : `is_our_process` (jamais `pid_alive`) protège contre BUG-009. |
| h | Crash conteneur avec position ouverte → reprise protégée au restart | **FAIL** | **C'est FAIL-1.** `reconcile()` jamais appelée : la position redevient invisible au risk-overlay. |
| i | Désarmement pendant que l'enfant tourne → arrêt effectif | **PASS (code) / gap de test (cf. C11)** | Branche partagée `if stop or marker is None` — correcte par lecture, non testée dans cette combinaison exacte. |
| j | Clés absentes/invalides → échec explicite, pas de restart-loop silencieux | **PASS (absentes) / MARGINAL (invalides)** | Voir C8/MARGINAL-2. |
| k | Le superviseur peut-il vendre/passer un ordre lui-même | **PASS** | `grep` exhaustif sur `live_supervisor.py` et `live_control.py` : 0 occurrence de `create_market_*`/`fetch_balance`/`ccxt`/`KrakenExchange`. |

---

## Qualité des tests (hors checklist)

- **675 tests exécutés, 675 PASS** (`pytest -q`, 71 s, aucun réseau/clé,
  machine locale, **MESURÉ** par exécution directe ce jour).
- Aucune assertion existante affaiblie repérée dans `git diff tests/test_trader.py`
  (diff volumineux mais liste de fonctions identique avant/après ; seule
  addition : redirection `live_trader.STATE_FILE` vers `tmp_path`, cohérente
  avec E2/L3 — écriture hors dépôt).
- Les tests ajoutés (anti-BUG-015 web et superviseur, PID recyclé, EOF sans
  TTY, nonce, container web) sont **falsifiables** : chacun a été relu avec
  son assertion et peut échouer si le code régresse (pas de test qui ne
  teste rien). Le seul point structurellement faible est l'absence de test
  d'intégration `cmd_live → reconcile()` (FAIL-2) et la combinaison
  « live-disarm CLI sur enfant vivant » (C11).
- **Zéro secret dans le git status** : `.env` gitignored, non présent dans
  les fichiers modifiés/nouveaux (`git status --porcelain` relu, seuls
  `.env.deploy.example` — un template — est modifié).
- `VERIFY_SSL = True` intact (`config.py:61`, non touché par le diff).

---

## Non-régression

- **Paper (prod) intact** : `docker-compose.yml`/`docker-compose.eunivers.yml`
  service `paper` non modifié par ce diff (seul `monitor` gagne `--live-root
  /data`, sans effet tant que l'overlay `live` n'est pas ajouté — `--live-root`
  est un flag mort en son absence, confirmé par lecture de `monitor.py:990-997`).
- **Live LOCAL intact** : `test_route_live_local_flux_nonce_inchange_sans_flag`
  PASS ; `cmd_live` textuellement inchangé (`git diff` vérifié caractère par
  caractère sur le hunk).
- **Défaut sans flag/overlay strictement inchangé** : `IYC_DISABLE_LIVE_CONTROL`
  absent de `docker-compose.yml`/`docker-compose.eunivers.yml` de base — code
  confirmé par grep, présent uniquement dans l'overlay `docker-compose.live.yml`.

---

## Ce qui reste À VALIDER SUR LE DEBIAN RÉEL (non testable ici, pas de Docker)

1. **Le merge Compose 3-fichiers** (`docker compose -f docker-compose.yml -f
   docker-compose.live.yml`) — en particulier que `environment:` du service
   `monitor` fusionne bien en UNION (`IYC_DISABLE_PAPER_CONTROL=1` de la base
   **+** `IYC_DISABLE_LIVE_CONTROL=1` de l'overlay, les deux présents) et non en
   REMPLACEMENT (qui ferait perdre `IYC_DISABLE_PAPER_CONTROL`). Comportement
   documenté comme acquis (Docker Compose fusionne les listes `environment`
   par union de clés) mais **jamais exécuté** dans cette gate.
2. **La résolution effective de `.env`** par `python-dotenv` : `config.py`
   appelle `load_dotenv()` sans argument, dont le comportement par défaut
   recherche `.env` en remontant depuis le fichier appelant (`config.py`,
   situé à `/app/`), pas depuis le `cwd` du process (`working_dir: /data`).
   Le montage `./.env:/app/.env:ro` (et non `/data/.env`) semble conçu en
   connaissance de cause pour ce comportement — cohérent avec la doc
   `python-dotenv`, mais **jamais exécuté** dans cette gate (pas de conteneur
   disponible ici).
3. **Le healthcheck / `init: true` (tini)** — que SIGTERM se propage
   effectivement du conteneur au superviseur PID 1, testé unitairement
   (`test_sigterm_handler_sets_stop_event`) mais jamais en conditions Docker
   réelles.

---

## VERDICT

**NO-GO.**

- **FAIL** : 2 (FAIL-1 P0 — `reconcile()` jamais appelée dans le chemin réel,
  danger n°1 de la spec non corrigé ; FAIL-2 — garde C1 sans test
  d'intégration, C13/N12).
- **MARGINAL** : 2 (bannière « position non gérée » incomplète ; hypothèse
  spec « clés invalides = crash » fausse au regard du code, statut
  superviseur trompeur dans ce cas).
- Sur 25 items de checklist (C1-C13 hors C2 subsumé, N1-N12), **22 PASS**, une
  fois FAIL-1/FAIL-2/N12 comptés une seule fois chacun malgré leurs
  répercussions croisées.

Ce lot ne peut pas être committé en l'état pour un déploiement avec de
l'argent réel : le scénario que toute la spec existait pour couvrir — crash
ou redémarrage du conteneur avec une position ouverte — laisse cette
position **sans aucune protection de risque** jusqu'à ce qu'un signal de
stratégie la ferme. Le correctif est localisé (un appel manquant dans
`cmd_live`, plus le test d'intégration qui l'aurait empêché de manquer) mais
il est **du code**, hors du mandat de cette gate en lecture seule — à
renvoyer au producteur (`lead-implementer`) avec ce rapport.
