# Gate indépendante — Lot 8 (écran Live verrouillé, `/live`)

> **Statut : GATE INDÉPENDANTE (V3).** Auditeur = `qa-tester`, n'a pas produit ce
> code. Référentiel gelé : `docs/design/LOT8_LIVE_SPEC.md` (12 critères NO-GO
> §6, ~35 tests §5.1-5.4). Périmètre audité : `trading/live_control.py`,
> `trading/live_page.py`, routes `/live*` de `trading/monitor.py`,
> `trading/home_page.py`, `main.py::cmd_live`, `config.py`, et les 4 fichiers
> de tests `tests/test_live_page.py` / `test_live_arm.py` / `test_live_server.py`
> / `test_launcher.py`. Code non commité (working tree, `git status` :
> `?? trading/live_control.py`, `?? trading/live_page.py`, etc.). 592 tests
> `pytest` verts (MESURÉ, `pytest -q` → `592 passed in 58.89s`).
>
> **VERDICT : NO-GO.** Un défaut P0 reproductible (10/10) permet de démarrer
> **deux process live réels concurrents** sur le même compte via un scénario
> parfaitement légitime (double armement + double confirmation, ex. deux
> onglets). Détail FAIL-1 ci-dessous. Le reste de la construction (12/12
> critères NO-GO littéraux, nonce, phrase, cloisonnement des clés, nav,
> lanceur paper-only) est solide et empiriquement vérifié.

---

## 1. FAIL — défauts bloquants

### FAIL-1 — Race TOCTOU : deux process live réels peuvent démarrer concurremment (viole §1.4.6/§2.2, hors-lettre des 12 NO-GO mais dans leur périmètre explicite — scénario d'attaque (g) demandé par le brief)

**Sévérité : P0/Critique.** **Statut : MESURÉ, reproduit 10/10.**

**Le fait.** `trading/monitor.py:1399-1401` (chemin réel) vérifie
`live_control.live_identity(root)` puis, si `running` est faux, poursuit
jusqu'à `live_control.start_live_process(...)` (`monitor.py:1414`). Ce
dernier **spawn d'abord** (`live_control.py:331`,
`spawn_live_detached(...)`) **puis écrit** le fichier PID
(`live_control.py:333`, `lancer.write_pid_file(...)`). Entre la lecture et
l'écriture, **aucun verrou** ne protège la séquence — ni dans
`trading/live_control.py` (aucun `threading.Lock` dans tout le fichier,
MESURÉ par grep), ni autour du bloc `_live_start_post` dans `monitor.py`. Le
serveur est un **`http.server.ThreadingHTTPServer`**
(`trading/monitor.py:1867`, MESURÉ) : chaque requête HTTP tourne dans son
propre thread. Deux `POST /live/start` concurrents, chacun porteur d'un
**nonce distinct et individuellement valide** (deux armements légitimes,
p. ex. deux onglets du navigateur, ou un double-clic après un rechargement
de `/live`), peuvent tous deux lire « aucun live en cours » avant que l'un
des deux n'ait écrit son fichier PID.

**Preuve empirique (scratchpad, ne modifie aucun fichier de production,
`spawn_live_detached` monkeypatché comme dans la suite officielle — jamais
de vrai process lancé)** :

```
essai 0: spawns reels = 2
essai 1: spawns reels = 2
... (10/10)
Essais: 10 | doubles spawns observes: 10 | detail: [2, 2, 2, 2, 2, 2, 2, 2, 2, 2]
```

Script : deux `POST /live/arm` légitimes (host+CSRF+prereqs+3 attestations
+mode=reel, tous vrais) produisant deux nonces **distincts**, puis deux
`POST /live/start` **concurrents**, chacun avec **son propre nonce** et la
phrase exacte `OUI JE CONFIRME`. Résultat : **2 appels réels à
`spawn_live_detached` avec `--execute`**, à chaque essai, sur 10.

**Pourquoi c'est un vrai défaut P0 et pas un artefact de test.** Aucune
étape d'authentification n'est contournée — les DEUX requêtes sont
pleinement légitimes (host OK, CSRF valide, prereqs re-testés OK,
attestations cochées, phrase exacte). Le bug n'est PAS un contournement des
remparts (N1/N2/N5/N10 tiennent chacun individuellement) : c'est une
**violation de l'invariant « un seul live à la fois »** que la spec pose
explicitement (§1.4.6 : *« Un seul live a la fois : … REFUS, on redirige
vers l'etat "live en cours" »* ; §2.2 : *« Verrou "un seul live" natif via
le fichier PID »*). Deux process `LiveTrader(dry_run=False)` tournant en
parallèle sur le **même compte Kraken** enfreignent en pratique le plafond
d'exposition : chaque process applique `MAX_POSITION_VALUE_USD` contre **sa
propre lecture** de `fetch_balance()` (`trading/live_trader.py:89-91`),
sans coordination entre eux — l'exposition agrégée réelle peut dépasser
500 $ alors que chaque process, pris isolément, croit respecter le plafond.
C'est exactement le mode de défaillance que toute l'architecture « process
détaché + verrou PID » (spec §3.2) prétend éliminer.

**Non-couverture par la suite existante (lien avec N12).** Le test
`test_route_live_un_seul_live` (`tests/test_live_server.py:319-334`)
monkeypatche `live_control.live_identity` pour renvoyer `(pid, True, ts)`
**avant** l'appel — il prouve la logique **séquentielle** (si déjà en
cours → refus), mais ne teste **aucune concurrence réelle** (pas de
threads, pas de requêtes simultanées). C'est précisément l'angle mort qui
laisse passer ce défaut : le garde-fou existe et sa version séquentielle
est correcte, mais rien ne protège sa version concurrente.

**Correctif recommandé (ciblé, peu coûteux)** : un `threading.Lock` unique
(module-level ou attaché au serveur, à côté de `_arm_tokens`) englobant, à
l'intérieur de `_live_start_post` (chemins `reel` **et** `dry`), la
séquence *lecture de `live_identity()` → `start_live_process()`*. Aucun
changement d'architecture (le process reste détaché, cf. §3.1-3.2 de la
spec) ; le verrou protège uniquement la fenêtre de démarrage, pas la durée
de vie du trader.

---

## 2. MARGINAL — constats significatifs, non bloquants

### MARGINAL-1 — Champ `symbol` non whitelisté avant construction de la commande

**Statut : MESURÉ (lecture de code) + raisonné (pas de PoC d'exploitation
réussie).** `trading/live_page.py::parse_live_params` (l.117-145) whiteliste
`strategy` (contre `STRATEGIES`, l.126) et `timeframe` (contre
`TIMEFRAME_CHOICES`, l.132), mais **`symbol` ne subit aucune validation**
au-delà d'un `.strip()` (l.129). Ce texte libre finit littéralement en
argument `--symbol` de `build_live_command` (`live_control.py:194`).

**Pourquoi ce n'est PAS un FAIL** : le spawn passe par `subprocess.Popen(cmd, ...)`
avec `cmd` en **liste**, jamais `shell=True`
(`live_control.py:300-304`, MESURÉ) → aucune injection shell possible. Le
pire cas réaliste : (a) une valeur ressemblant à un flag connu
(`--execute`) fait échouer le `argparse` du subprocess avec un code de
sortie non nul (fail-safe : aucun ordre) ; (b) une valeur non reconnue par
Kraken fait échouer `KrakenExchange` à la première requête (fail-safe :
aucun ordre). Dans les deux cas, le pire résultat mesuré/raisonné est un
**arrêt en échec du process live**, pas une exécution non voulue.

**Recommandation** : whitelist ou regex (`^[A-Z0-9]+/[A-Z0-9]+$`) sur
`symbol`, par cohérence avec `strategy`/`timeframe` et en défense en
profondeur — coût trivial, aligné avec l'esprit N4 (aucun champ libre ne
doit pouvoir influer sur la forme de la commande).

### MARGINAL-2 — Garde `_host_ok()` non re-testée par un test dédié à `/live*`

**Statut : MESURÉ.** `_host_ok()` (`monitor.py:968-980`) est appelée à
l'identique sur les 4 routes `/live*` (`monitor.py:1544/1561, 1697/1711/
1725/1739`, confirmé par grep — 31 occurrences du même motif
`if not self._host_ok(): return` sur toutes les routes de l'app) et repose
sur `host_allowed()`, unitairement testée (`tests/test_options.py:309-319`,
accepte loopback/refuse hôte étranger). Un test HTTP générique existe
seulement contre `/` (`tests/test_monitor_server.py:294`). **Aucun test
n'envoie un `Host` falsifié à `/live`, `/live/arm`, `/live/start` ou
`/live/stop`.**

**Pourquoi ce n'est pas un FAIL** : le code appelé est **textuellement
identique** sur toutes les routes (même méthode, même garde, en tête de
chaque handler, avant toute autre logique) — ce n'est pas un chemin
alternatif non couvert, c'est le **même** chemin déjà couvert ailleurs. Un
test dédié serait un filet de non-régression légitime (et bon marché à
ajouter : `_post(base + "/live/arm", ..., headers={"Host": "evil.example"})`
→ 403 attendu) mais son absence ne signale pas un comportement différent
mesuré ou suspecté sur `/live*`.

### MARGINAL-3 — Substitution de paramètres au `start` : protégée par construction, pas par un test HTTP dédié

**Statut : MESURÉ (lecture de code).** Le chemin `reel` de
`_live_start_post` (`monitor.py:1356-1427`) **ne lit jamais**
`form["strategy"]`/`form["symbol"]`/`form["timeframe"]` — il n'utilise que
`confirmed_params = _arm_tokens.consume(nonce)` (l.1403), c'est-à-dire les
paramètres **figés à l'armement**. La substitution de paramètres au
`POST /live/start` est donc **structurellement impossible**, pas seulement
non observée : le code n'a même pas de branche qui lirait un `strategy`
resoumis pour ce chemin. `test_nonce_lie_aux_parametres`
(`tests/test_live_arm.py:31-47`) le prouve au niveau du store ; il n'existe
pas de test HTTP qui soumette explicitement des champs différents au
`/live/start` pour le documenter au niveau route — recommandé pour la
lisibilité de la suite, non bloquant.

---

## 3. Les 12 critères NO-GO (§6 de la spec) — un par un, preuve à l'appui

| # | Critère | Statut | Preuve (fichier:ligne) |
|---|---|---|---|
| **N1** | Garde uniquement JS | **PASS** — MESURÉ | Le bouton réel porte `disabled` calculé serveur (`live_page.py:297`, `reel_disabled = "" if prereq.get("ok") else " disabled"`) mais c'est **cosmétique** : `_live_arm_post` (`monitor.py:1286-1313`) re-teste `prereq`/`attest_ok`/`mode_ok` **sans aucune confiance au HTML** — une requête forgée qui ignore le `disabled` échoue quand même côté serveur. Le sélecteur de mode du mur est explicitement `disabled` + décoratif (`live_page.py:288-290`). |
| **N2** | Reel en 1 seul round-trip | **PASS** — MESURÉ | `POST /live/start` sans nonce préalable échoue systématiquement : `params = _arm_tokens.peek_params(nonce)` renvoie `None` pour un nonce absent/inconnu (`live_control.py:141-146`) → branche refus (`monitor.py:1358-1368`). Test `test_route_live_start_sans_nonce_refuse_sans_spawn` (`tests/test_live_server.py:226-234`) : `calls == []`. Nonce = `secrets.token_hex(32)` (256 bits, `live_control.py:118`) → incassable par force brute. **Nuance (voir FAIL-1)** : le couple `arm→start` est bien à deux round-trips par nonce, mais **deux couples distincts** peuvent s'exécuter en parallèle — ceci ne viole pas la lettre de N2 (chaque nonce est bien issu de son propre `/live/arm`), mais viole l'invariant « un seul live » énoncé ailleurs dans la même spec (§1.4.6/§2.2). |
| **N3** | Dry-run pas par défaut / mode ambigu démarre le réel | **PASS** — MESURÉ | `resolve_execute()` (`live_control.py:71-75`) : `True` **ssi** `form["mode"].strip().lower() == "reel"` exactement ; absent/vide/`"dry"`/toute autre valeur → `False`. `render_live_wall` affiche `dry` `checked` par défaut (`live_page.py:288`). Test `test_route_live_start_mode_absent_ne_demarre_rien` (`tests/test_live_server.py:271-278`) : POST sans `mode` → `calls == []`. |
| **N4** | Contournement des plafonds | **PASS** — MESURÉ | `build_live_command` (`live_control.py:178-209`) ne construit **jamais** `--max-*` ; le parser CLI `live` (`main.py:485-488`) n'expose **aucun** flag de plafond (confirmé par lecture directe du parser). `LiveTrader._rebalance` lit `config.MAX_TRADE_VALUE_USD`/`MAX_POSITION_VALUE_USD` **directement depuis `config.py`** (`live_trader.py:89-90`), sans paramètre substituable. Test `test_build_live_command_reel_a_execute_sans_override_plafond` (`tests/test_live_arm.py:92-104`). **Nuance liée à FAIL-1** : le plafond par-process est bien inattaquable, mais l'**agrégat** de deux process concurrents n'est *pas* couvert par ce garde-fou (deux plafonds individuellement respectés peuvent sommer au-delà de l'exposition voulue). |
| **N5** | Phrase non exacte | **PASS** — MESURÉ | `phrase_ok()` (`live_control.py:78-84`) : `str(phrase).strip() == "OUI JE CONFIRME"`, sensible à la casse, sans `startswith`. Test `test_phrase_exacte_requise` (`tests/test_live_arm.py:82-89`) couvre casse, préfixe, vide, `None`, double-espace interne — tous rejetés sauf l'exact + espaces externes. |
| **N6** | Clés exposées | **PASS** — MESURÉ | `render_live_wall`/`render_live_recap`/`render_live_running` ne reçoivent **que des booléens** (`keys_ok`), jamais de valeur. `build_live_command` ne construit aucun argument de clé (`live_control.py:184-189`, commentaire explicite + test `test_build_live_command_ne_contient_jamais_de_cle`). Le subprocess relit `.env` lui-même (`config.py:14-15`) — les clés ne transitent jamais par le process réseau-facing. `spawn_live_detached` ne passe **que la phrase** en stdin (`live_control.py:308-313`), jamais de clé. Test `test_live_page_ne_contient_jamais_de_cle` (`tests/test_live_page.py:39-49`) injecte un faux secret et vérifie son absence. |
| **N7** | Live dans la nav / lanceur capable de live | **PASS** — MESURÉ | `NAV_ITEMS`/`ENABLED_SCREENS` (`webui.py:110-129`) : `"live"` absent des deux. Lien discret uniquement depuis l'Accueil (`home_page.py:120`, hors nav principale). `lancer.py::assert_paper_only` (l.67-79) lève `RuntimeError` si `"live"` apparaît dans un token de commande construit ; `lancer.py` n'importe pas `live_control` et n'expose pas `build_live_command` — vérifié positivement par `test_lanceur_ne_construit_jamais_live` (`tests/test_launcher.py:559-577`, incluant `assert not hasattr(lancer, "build_live_command")` et `assert "live_control" not in inspect.getsource(lancer)`). |
| **N8** | Boucle live dans JobManager/thread serveur | **PASS** — MESURÉ | Le live est un **process détaché** (`spawn_live_detached`, `live_control.py:271-314`, `Popen` sans `wait()`), jamais un `JobManager` ni un thread du serveur web. Aucune référence à `trading.jobs`/`JobManager` dans `live_control.py` ou dans la portion `/live*` de `monitor.py` (vérifié par lecture complète du fichier). |
| **N9** | « Arrêter » cosmétique | **PASS** — MESURÉ | `_live_stop_post` (`monitor.py:1429-1442`) : confirme l'identité (`live_identity` → `is_our_process`, patron BUG-009) **avant** `lancer.terminate_pid(pid)` réel (l.1439) ; si non confirmé, **aucun** `terminate_pid` n'est appelé (nettoyage du seul fichier PID). Tests `test_route_live_stop_termine_pid_confirme` et `test_route_live_stop_refuse_pid_non_confirme` (`tests/test_live_server.py:371-402`) vérifient les deux branches, y compris `terminated == []` sur PID non confirmé. |
| **N10** | Re-validation manquante au start | **PASS** — MESURÉ | `prereq = self._live_prereq()` est appelé **à nouveau** au tout début de `_live_start_post` réel (`monitor.py:1369`), **avant** de consommer le nonce — indépendant du résultat d'`/live/arm`. Test `test_route_live_start_reel_refuse_si_cles_disparues_au_start` (`tests/test_live_server.py:301-316`) fait disparaître les clés **entre** arm et start et vérifie `calls == []`. |
| **N11** | VERIFY_SSL touché | **PASS** — MESURÉ | `grep -n "VERIFY_SSL" trading/live_control.py trading/live_page.py trading/home_page.py` → aucune occurrence. `git diff -- trading/monitor.py \| grep VERIFY_SSL` → vide. `config.py:61` : `VERIFY_SSL = True`, inchangé. |
| **N12** | Couverture de test absente | **PASS pour les gardes listées §2 ; MARGINAL sur la dimension concurrence** | Les 35 tests spec (§5.1-5.4) sont **tous présents avec les noms exacts** (compte exhaustif : 8 dans `test_live_page.py`, 5 dans `test_live_arm.py`, 22 dans `test_live_server.py`, 1 dans `test_launcher.py` = 36 correspondances pour 35 items nommés — `test_nonce_inconnu_ou_vide_toujours_invalide` est un test bonus non listé dans la spec). **Mais** : le garde « un seul live à la fois » n'a de test QUE pour son cas séquentiel (`test_route_live_un_seul_live`), jamais pour le cas concurrent — c'est l'angle mort qui a laissé passer FAIL-1. Ce point n'est pas un FAIL de N12 au sens littéral (la garde listée §2 a bien un test), mais c'est la preuve que « garde testée » ≠ « garde thread-safe ». |

---

## 4. Les 10 scénarios d'attaque du brief — un par un

| Scénario | Statut | Détail |
|---|---|---|
| **(a)** POST `/live/start` avec CSRF volé + nonce deviné | **PASS** — MESURÉ/DÉRIVÉ | CSRF : comparaison temps constant (`csrf_valid`, `monitor.py:862-866`) ; sans token valide → 403 avant tout traitement (`monitor.py:1711-1722` etc.). Nonce : `secrets.token_hex(32)` = 256 bits d'entropie — deviner un nonce actif est **calculatoirement infaisable** (DÉRIVÉ : espace de recherche 2²⁵⁶, aucune fuite d'entropie identifiée dans le code). |
| **(b)** Nonce réutilisé 2× | **PASS** — MESURÉ empiriquement | Store isolé : stress-test 300 essais × 24 threads sur le **même** nonce → **0 double-consommation** observée (`ArmTokenStore.consume`). Séquentiel : `test_nonce_usage_unique` (`tests/test_live_arm.py:11-17`) et `test_route_live_start_nonce_consomme_pas_de_rejeu` (`tests/test_live_server.py:252-268`, rejeu HTTP explicite : 2e POST identique → `len(calls) == 1`). **Note** : ce test empirique porte sur le MÊME nonce ; il ne couvre pas le cas de DEUX nonces distincts (→ FAIL-1). |
| **(c)** Nonce périmé > 120 s | **PASS** — MESURÉ | `ARM_TOKEN_TTL_SEC = 120` (`live_control.py:38`, valeur recommandée par la spec §2.2). `test_nonce_expire_apres_ttl` (`tests/test_live_arm.py:20-28`) : valide à `t0+119`, expiré à `t0+200`, `consume()` renvoie `None` au-delà du TTL. |
| **(d)** Params modifiés entre arm et start (swap stratégie/symbole) | **PASS** — MESURÉ (structurel, cf. MARGINAL-3) | Le chemin réel de `_live_start_post` ne lit **jamais** `form["strategy"/"symbol"/"timeframe"]` — seuls les `confirmed_params` issus du nonce sont utilisés (`monitor.py:1403,1414`). La substitution est impossible **par construction**, pas seulement non observée. |
| **(e)** 2 `arm` consécutifs — l'ancien nonce meurt-il ? | **VÉRIFIÉ, comportement conforme à la spec (pas un défaut)** | `ArmTokenStore.create()` n'invalide jamais les nonces précédents (`live_control.py:113-125`) : plusieurs nonces valides peuvent coexister. La spec ne l'interdit pas (§2.2 ne parle que des propriétés PAR nonce). Chaque nonce reste individuellement soumis à TOUTES les gardes (host/CSRF/prereqs/phrase/TTL/plafond tentatives). **C'est précisément cette coexistence qui rend possible FAIL-1** : ce n'est pas un défaut en soi, mais c'est la condition nécessaire du défaut ci-dessus. |
| **(f)** Clés retirées entre arm et start | **PASS** — MESURÉ, test dédié | `test_route_live_start_reel_refuse_si_cles_disparues_au_start` (`tests/test_live_server.py:301-316`) : clés présentes à l'arm, retirées avant le start → `calls == []`. Correspond à N10. |
| **(g)** Spawn d'un 2e live pendant qu'un tourne | **FAIL** — MESURÉ, reproduit 10/10 | Cf. **FAIL-1**. Le garde séquentiel existe et fonctionne (`test_route_live_un_seul_live`) ; sa version concurrente ne tient pas. |
| **(h)** Stop sur PID recyclé (BUG-009) | **PASS** — MESURÉ | `live_identity()` (`live_control.py:223-238`) appelle `lancer.is_our_process(pid, "live", start_ts)`, qui exige `"main.py"` **ET** `"live"` dans la cmdline **et** une tolérance de 5 s sur `create_time()` (`lancer.py:224-258`) — un PID recyclé par un process tiers échoue ces trois tests → traité comme « arrêté », jamais tué. Test `test_route_live_stop_refuse_pid_non_confirme` (`tests/test_live_server.py:388-402`) : `terminated == []`. |
| **(i)** `mode=''` ou absent | **PASS** — MESURÉ | `resolve_execute({})` → `False` (`live_control.py:71-75`, test `test_resolve_execute_defaut_dry_run`, `tests/test_live_arm.py:74-79`). Côté route start, `mode` absent → ni branche `dry` ni branche `reel` valide n'est atteinte correctement : `mode = (form.get("mode") or "").strip().lower()` → `""` ; `if mode == "dry"` faux → tombe dans le chemin réel, où `if mode != "reel":` (`monitor.py:1377`) refuse explicitement. Test `test_route_live_start_mode_absent_ne_demarre_rien` confirme `calls == []`. |
| **(j)** Injection dans un champ de formulaire finissant dans la cmdline | **MARGINAL** — cf. MARGINAL-1 | Pas d'injection shell possible (`Popen` liste, jamais `shell=True`) ; `strategy`/`timeframe` whitelistés ; `symbol` libre mais le pire cas mesuré/raisonné est un échec fail-safe du subprocess (argparse ou ccxt), pas une exécution non voulue. Recommandation de durcissement émise, non bloquante. |

---

## 5. Gate SQA (`docs/SQA.md` §4)

- **`pytest -q`** → **MESURÉ** : `592 passed in 58.89s`, 0 échec, 0 erreur, 0 skip.
- **Secrets** : `grep -niE "kraken_api_(key|secret)\s*=\s*['\"][A-Za-z0-9]|sk_live|api[_-]?secret\s*=\s*['\"]"` sur les 8 fichiers du Lot 8 → **seule occurrence** = le faux secret de test `sk_live_SUPER_SECRET_KRAKEN_TOKEN_1234567890` (`tests/test_live_page.py:43`), utilisé pour PROUVER son absence du HTML rendu — pas une fuite.
- **VERIFY_SSL/config** : aucune occurrence de `VERIFY_SSL` dans les fichiers Lot 8 ; `config.py` non modifié par ce lot (`git diff --stat -- config.py` vide) ; `VERIFY_SSL = True` intact.

---

## 6. Compromis (M20) — ce que ce livrable obtient / abandonne / coûte à corriger

- **Obtenu (chiffré)** : 11 des 12 critères NO-GO littéraux **PASS avec preuve fichier:ligne** ; 9 des 10 scénarios d'attaque du brief **PASS empiriquement ou structurellement vérifiés** ; 592/592 tests verts ; zéro fuite de clé (testé activement, pas supposé) ; cloisonnement process/nav/lanceur intact.
- **Abandonné (nommé)** : l'invariant « un seul live à la fois » n'est **pas** garanti sous concurrence réelle — reproduit 10/10 dans un scénario entièrement légitime (deux armements + deux confirmations valides).
- **Coût de la correction** : un `threading.Lock` unique autour de la séquence `live_identity()` → `start_live_process()` dans `_live_start_post` (chemins `reel` et `dry`). Modification locale, pas de changement d'architecture, pas de nouveau test d'intégration lourd (un test avec 2 threads suffit à figer la non-régression). Estimation : quelques lignes + 1 test de concurrence.

---

## Verdict final

**NO-GO** pour exposer `/live` à l'utilisateur en l'état. Le défaut FAIL-1 est
P0 par nature du lot (argent réel), reproductible à volonté, et atteignable
sans aucune malveillance (un double armement légitime suffit). Corriger
FAIL-1 (verrou autour du démarrage), puis idéalement traiter MARGINAL-1
(whitelist `symbol`) et ajouter les 2 tests de non-régression MARGINAL-2/3,
avant re-soumission à cette même gate.

### Une ligne par point (FAIL/MARGINAL)

- FAIL-1 : race TOCTOU sur « un seul live à la fois » — 2 process réels concurrents possibles, reproduit 10/10 (`trading/monitor.py:1399-1427`, `trading/live_control.py:317-343`, aucun verrou).
- MARGINAL-1 : champ `symbol` non whitelisté avant construction de la commande (`trading/live_page.py:129`) — pas d'injection possible, fail-safe si abusé, durcissement recommandé.
- MARGINAL-2 : `_host_ok()` non re-testée par un test HTTP dédié à `/live*` — même code que le reste de l'app, déjà couvert ailleurs, test dédié recommandé.
- MARGINAL-3 : substitution de paramètres au start protégée par construction (le code ne lit jamais les champs resoumis) mais sans test HTTP dédié qui le documente.
