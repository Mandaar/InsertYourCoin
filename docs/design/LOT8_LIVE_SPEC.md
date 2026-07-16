# Lot 8 — Live verrouille (`/live`) : spec d'implementation detaillee

> Statut : **SPEC DE CONCEPTION — NON IMPLEMENTE.** P0 (argent reel).
> Ne PAS implementer sans **feu vert explicite de l'utilisateur** (cf. roadmap
> `docs/UI_UX_WEBAPP_SPEC.md` §9, Lot 8 ; `docs/RAPPORT_WEBAPP_SUITE.md` §4).
> Auteur : UX/UI Designer. Cible : rendre l'implementation future **rapide et
> sure** — l'implementeur ne doit prendre **AUCUNE decision de securite** lui-meme.
> Ancrage (lecture directe) : `main.py` `cmd_live` (l.258-279), `trading/live_trader.py`,
> `config.py`, `trading/options.py`, `trading/monitor.py`, `trading/jobs.py`,
> `trading/webui.py`, `trading/paper_trader.py`, `lancer.py`, `tests/test_monitor_server.py`.
> Convention : chaque fait tire du code est cite `fichier:ligne`.

---

## 0. Resume executif + recommandation d'architecture

Le Lot 8 expose l'equivalent web de `python main.py live --execute` **sans jamais**
le rendre facile ni accidentel. Par defaut **dry-run**. La friction est un **choix
de securite**, pas un defaut UX (`docs/UI_UX_WEBAPP_SPEC.md` §4.13, §0 ligne 37).

**Recommandation d'architecture process : PROCESS LIVE DETACHE** (patron
`paper`/`lancer.py`), pas un thread dans le serveur web, pas un job `JobManager`.
Justification detaillee en §3. En une phrase : le `JobManager` (`trading/jobs.py`)
attend un `target` qui **retourne** un resultat fini et gere l'annulation de facon
**cooperative** (`jobs.py:44-65`, `JobProgress.cancelled`), or la boucle du trader
est un `while True` infini qui ne s'arrete que sur `KeyboardInterrupt`
(`trading/paper_trader.py:194,211-213`) et **ne lit jamais** `progress.cancelled` ;
et le patron detache isole les cles API du process **reseau-facing**, tout en
reutilisant les gardes anti-recyclage de PID **deja durcies** (BUG-009,
`lancer.py:182-238` `is_our_process`).

**Phrase exacte de confirmation** (source de verite, `main.py:276`) :

```
OUI JE CONFIRME
```

(le serveur devra la comparer **apres `.strip()`**, a l'identique de la CLI :
`input(...).strip() != "OUI JE CONFIRME"`, `main.py:276`.)

**Defense en profondeur (3 remparts, tous obligatoires)** :
1. **Web** : escalier a **deux round-trips serveur** (arm puis start), nonce
   d'armement a usage unique, pre-requis re-valides serveur, phrase exacte.
2. **Process** : `cmd_live` **re-verifie** les cles (`main.py:260-261`) **et** la
   phrase (`main.py:276`) au niveau du process detache (voir §3.4 : la phrase lui
   est transmise via stdin, `cmd_live` reste **inchange** et sert de 3e garde).
3. **Trader** : les plafonds sont appliques **dans** `LiveTrader._rebalance`
   (`trading/live_trader.py:89-91`), lus de `config.py` a l'execution — **l'UI ne
   peut pas les contourner** (aucun parametre ne les surcharge, cf. §6 NO-GO).

---

## 1. Flux exact multi-etapes (l'escalier de friction)

> Reprend `docs/UI_UX_WEBAPP_SPEC.md` §4.13 / §5.3 et precise **tout**. Chaque
> transition qui engage de l'argent reel est un **round-trip serveur** distinct.

### 1.0 Acces (hors nav principale)
- **Live n'est PAS un onglet de la nav** (`trading/webui.py` `NAV_ITEMS` l.110-123
  et `ENABLED_SCREENS` l.127-129 : `live` **absent**, et doit le rester — cf. §6).
- Acces par un **lien discret** `<a href="/live">` depuis l'Accueil
  (`trading/home_page.py`) et/ou Options — jamais un clic depuis partout
  (`docs/UI_UX_WEBAPP_SPEC.md` §3.1 l.145-146).

### 1.1 Route `GET /live` — le mur (page verrouillee)
Rendue par une nouvelle page pure `trading/live_page.py` (meme patron que
`render_options_page`, `trading/monitor.py:488-568`), enveloppee par `page_shell`
(`trading/webui.py:201`). Le serveur calcule **cote serveur** :

- **Bandeau rouge permanent** : "ARGENT REEL. Pertes possibles jusqu'a la totalite
  du capital. Outil sans garantie." (`docs/UI_UX_WEBAPP_SPEC.md` §4.13 l.517-518).
- **Plafonds lus de `config.py`** (toujours visibles, avant toute action) :
  - `MAX_TRADE_VALUE_USD` = 100.0 (`config.py:57`),
  - `MAX_POSITION_VALUE_USD` = 500.0 (`config.py:58`),
  - `MIN_TRADE_INTERVAL_SEC` = 3600 (`config.py:59`, a afficher "3600 s (1 h)").
  Libelle reutilise de la CLI : "Ordre max : {MAX_TRADE_VALUE_USD} $ | Exposition
  max : {MAX_POSITION_VALUE_USD} $" (`main.py:274`).
- **Etat des pre-requis** (voir 1.2), chacun **calcule serveur**, avec pastille
  OK/manquant.
- **Selecteur de mode** : radio **`(*) Simulation (dry-run)` selectionne par defaut**,
  `( ) REEL` (`docs/UI_UX_WEBAPP_SPEC.md` §4.13 l.526, "dry-run par defaut").
- **Formulaire de config** (memes composants que Paper, `docs/UI_UX_WEBAPP_SPEC.md`
  §4.0 l.167-176) : strategie (registre `STRATEGIES`, `trading/strategies.py`),
  `symbol` (defaut `config.DEFAULT_SYMBOL` = ETH/USD, `config.py:18`), `timeframe`
  (defaut `config.DEFAULT_TIMEFRAME` = 1d, `config.py:19`), risque (stop/objectif/
  trailing/sizing). **Jamais** de `source` (live = 100% Kraken,
  `docs/UI_UX_WEBAPP_SPEC.md` §2 l.96-98).
- **Champ CSRF cache** (`csrf_token`, comme `/options`, `trading/monitor.py:525`).

### 1.2 Pre-requis bloquants (tous obligatoires)
Deux familles — a ne **jamais** confondre dans l'implementation :

**(A) Pre-requis VERIFIABLES par le serveur** (re-testes a CHAQUE round-trip) :
1. **Cles Kraken configurees** : `options.keys_configured()` (`trading/options.py:137-154`)
   — lit le `.env`, renvoie un **booleen** (jamais la valeur). Requis pour dry-run
   **et** reel : meme en dry-run, `LiveTrader._base_balance` appelle
   `exchange.fetch_balance()` (`trading/live_trader.py:49-53`) qui exige les cles.
   Message si absent : reutiliser "Cles API manquantes. Renseigne .env (voir
   .env.example) avant le mode live." (`main.py:261`).
2. **Diagnostic `check` OK** : le serveur garde en memoire `_last_check`
   (`trading/monitor.py:642`, alimente uniquement par `GET /check?run=1`,
   `trading/monitor.py:890-897`). Pre-requis satisfait si `_last_check["value"]`
   existe et indique une connexion OK **cette session**. (Reset au redemarrage du
   serveur = friction assumee : re-lancer le check avant d'armer le reel.)
3. **Paper deja lance au moins une fois** : `state_path.exists()` (le
   `paper_state.json` n'est cree que par `PaperTrader._save`,
   `trading/paper_trader.py:296-297`). **Honnetete** : le serveur ne peut verifier
   que "un paper a tourne au moins une fois", **pas** "sur CETTE config" (le
   `paper_state.json` ne stocke ni strategie ni symbole, `trading/paper_trader.py:292-294`)
   — le "sur cette config" reste une **attestation** utilisateur (famille B).

**(B) Attestations utilisateur** (cases a cocher — **presentes** dans le POST mais
non verifiables comme "vraies") :
4. "Mes cles n'ont **PAS** le droit **Withdraw** (Query Funds + Orders seulement)."
   Le serveur **ne peut pas** verifier le scope d'une cle. La **vraie** garantie
   est double : (a) l'app **n'a aucun chemin de code** de retrait (wallet = lien
   sortant seul, `trading/monitor.py:558-564`), (b) le scope est fixe **cote Kraken**
   a la creation de la cle. La case est une reconnaissance, pas une preuve.
5. "J'ai lance un paper sur cette config et **compris le risque**."
6. "J'ai **lu les plafonds** : ordre max 100 $ / position max 500 $."

**Regle d'implementation** : tant qu'un pre-requis (A) echoue **ou** qu'une
attestation (B) manque dans le POST, le chemin **REEL** est **inaccessible cote
serveur** (pas seulement bouton grise cote client — cf. §2). Le **dry-run** ne
requiert que (A.1) cles + CSRF + host.

### 1.3 Round-trip 1 du reel : `POST /live/arm` (armement)
Declenche par "Continuer en REEL". Le serveur, **avant tout** :
1. `_host_ok()` (`trading/monitor.py:669-673`) sinon 403.
2. CSRF valide (`csrf_valid`, `trading/monitor.py:571-575`) sinon 403.
3. **Re-valide** les 3 pre-requis (A) cote serveur (pas de confiance au client).
4. Verifie que **les 3 attestations (B)** sont **presentes** dans le POST.
5. Verifie que **`mode == "reel"`** (exactement).
6. Si un seul echoue -> **REFUS** : re-rend le mur avec le pre-requis fautif
   surligne, **aucun nonce emis**, aucune suite possible.
7. Si tout passe -> **emet un nonce d'armement** (`secrets.token_hex`, cf.
   `trading/monitor.py:635` pour le patron), **usage unique**, **TTL court**
   (recommande **120 s**), stocke **en memoire serveur** (dict `_arm_tokens`, patron
   `_session_keys`/`_last_check`, `trading/monitor.py:638,642`), **lie aux
   parametres valides** (strategie/symbole/timeframe/risque figes a cet instant).
8. Rend un **ecran de recapitulation servi par le SERVEUR** (pas une modale JS) :
   - recap identique a `cmd_live` (`main.py:264-275`) : paire, strategie (nom
     lisible via `build_strategy(...).name`, `main.py:267`), stop/objectif,
     trailing, sizing, **plafonds `config.py`** ;
   - **champ texte** "Tape exactement `OUI JE CONFIRME`" ;
   - le **nonce** en champ cache + le **CSRF** en champ cache ;
   - bouton "DEMARRER EN REEL" (POST vers `/live/start`) ;
   - bouton "Annuler" (retour `GET /live`, aucun ordre).

### 1.4 Round-trip 2 du reel : `POST /live/start` (demarrage)
Le serveur, **avant tout spawn** :
1. `_host_ok()` sinon 403 ; CSRF valide sinon 403.
2. **Nonce** present, **connu**, **non consomme**, **non expire** -> sinon REFUS
   (aucun spawn). Un `POST /live/start` **sans** nonce valide ne peut **jamais**
   demarrer le reel (§2).
3. **Re-valide encore** les 3 pre-requis (A) cote serveur (defense : ne pas se
   fier au fait que `arm` a reussi il y a 2 s ; l'etat a pu changer).
4. **`mode == "reel"`** exact ; sinon on ne demarre **rien** de reel (§2, fail-safe).
5. **Phrase exacte** : `submitted.strip() == "OUI JE CONFIRME"` (identique
   `main.py:276`). Toute difference (casse, texte partiel, vide) -> REFUS, message
   "Annule. (Aucun ordre envoye.)" (reutilise `main.py:277`), le nonce **reste
   valide** jusqu'a TTL/plafond de tentatives (recommande **3**), puis invalide.
6. **Un seul live a la fois** : si `run/live.pid` pointe un process **confirme live**
   (`is_our_process(pid, "live", start_ts)`, `lancer.py:182-238`) -> REFUS, on
   redirige vers l'etat "live en cours".
7. Tout OK -> **consomme le nonce** (usage unique) et **spawn le process live
   detache en mode REEL** (§3.4), ecrit `run/live.pid` + le sidecar `run/live.json`
   (§3.5), puis rend la page "live en cours" (1.6).

### 1.5 Demarrage dry-run : `POST /live/start` (mode `dry`)
Chemin court (le dry-run ne passe **aucun** ordre, `trading/live_trader.py:96-97,
119-120`) : `_host_ok` + CSRF + pre-requis (A.1) cles. **`mode == "dry"` explicite**
requis. Spawn detache **sans** `--execute` (dry-run par defaut, `main.py:262`),
stdin=DEVNULL. Sidecar `run/live.json` `mode="dry"`. **Aucune** exigence de
nonce/phrase (friction reservee au reel). Si `mode` absent/autre -> **aucun spawn**
(on ne demarre jamais rien d'implicite, cf. §2/§6).

### 1.6 Live en cours : `GET /live`
Quand un process live est detecte (via `run/live.pid` + `is_our_process`), la page
affiche l'etat "en cours" (§4) : bandeau permanent (**rouge REEL** ou **ambre
SIMULATION**, lu du sidecar `run/live.json`), plafonds, PnL, journal des ordres, et
un bouton **"Arreter immediatement"** (POST `/live/stop`, CSRF) **toujours visible**.

### 1.7 Arret : `POST /live/stop`
`_host_ok` + CSRF -> confirme l'identite du PID (`is_our_process(pid, "live", ...)`,
`lancer.py:182`) -> `terminate_pid(pid)` (`lancer.py:298-328`) -> supprime
`run/live.pid` + `run/live.json`. **Ne tue jamais** un PID non confirme (patron
BUG-009, `lancer.py:391-395`). L'arret **stoppe le bot** ; il **ne liquide PAS** la
position ouverte sur Kraken (message explicite a l'utilisateur, §4).

---

## 2. Modele de menace cote serveur (le coeur)

> Hypothese d'attaque : bind `127.0.0.1` uniquement (`trading/monitor.py:1121`,
> `host_allowed` l.578-586), mais un **site malveillant** ouvert dans le meme
> navigateur peut tenter un POST vers `127.0.0.1` (CSRF), et un script local peut
> **forger** un POST arbitraire. **Regle absolue** : un POST forge ne doit **JAMAIS**
> pouvoir demarrer le mode reel sans que **TOUTES** les conditions soient
> **re-validees cote serveur**. **La double confirmation = deux round-trips serveur
> distincts, pas deux clics JS.** Aucun controle ne vit **uniquement** en JS.

### 2.1 Tableau menace -> garde serveur (par etape)

| Etape / Menace | Ce qu'un client forge/malveillant tente | Garde serveur **obligatoire** (independante du client) |
|---|---|---|
| Toute requete | Requete depuis un autre hote / DNS-rebinding | `_host_ok()` (`monitor.py:669-673`, `host_allowed` l.578) -> 403 |
| Tout POST | POST cross-site avec le CSRF vole | `csrf_valid` temps constant (`monitor.py:571-575`) -> 403. **Le CSRF seul ne suffit jamais** a demarrer le reel (remparts suivants). |
| `GET /live` | Se faire afficher un bouton REEL actif | L'etat "reel accessible" est **calcule serveur** (pre-requis A re-testes) ; le client ne peut pas "activer" le reel en bricolant le HTML. |
| `POST /live/arm` | Pre-requis contournes cote client (cases cochees en JS, bouton force) | Serveur **re-teste** `keys_configured()` (`options.py:137`), `_last_check` OK (`monitor.py:642`), `paper_state.json` present (`paper_trader.py:296`) + **exige** les 3 attestations dans le corps + `mode=="reel"`. Un seul manque -> **aucun nonce**. |
| `POST /live/start` **direct** (sans arm) | Sauter l'ecran de recap et demarrer le reel | **Nonce d'armement** exige : absent/inconnu/expire/consomme -> REFUS, **aucun spawn**. Le nonce n'existe que si `/live/arm` a **reellement** reussi cote serveur. |
| `POST /live/start` | Champs bricoles : `mode=reel` injecte, attestations falsifiees | Pre-requis (A) **re-valides une 2e fois** au start ; phrase exacte exigee ; nonce exige. La falsification des cases (B) ne suffit pas : les gardes A + nonce + phrase tiennent. |
| `POST /live/start` | Phrase approximative ("oui", "OUI je confirme", vide) | `submitted.strip() == "OUI JE CONFIRME"` (exact, `main.py:276`) -> sinon REFUS, 0 ordre. |
| `POST /live/start` | **Champ manquant** (mode, phrase, nonce...) | **Fail-safe** : aucun champ requis absent ne demarre le reel ; `mode` absent/!="reel" -> pas de reel. On ne demarre **jamais** un process implicitement (ni reel ni dry) : seul un `mode` explicite + sa grille complete spawn quelque chose. |
| `POST /live/start` | **Rejeu** d'un start reussi (resubmit du meme POST) | Nonce **usage unique** consomme au 1er start reel -> rejeu trouve le nonce consomme -> REFUS. + verrou "un seul live" (PID). |
| `POST /live/start` | Substituer les parametres apres le recap (swap strategie/symbole) | Le serveur **utilise les parametres LIES au nonce** (figes a l'armement), **pas** ceux resoumis au start. |
| `POST /live/start` (dry) | Demarrer un dry-run sans cles pour sonder | Dry-run exige quand meme `keys_configured()` (le dry-run lit le solde reel, `live_trader.py:50-53`) + CSRF + host. |
| Plafonds | Passer un montant/plafond via un parametre | **Impossible par construction** : les plafonds sont appliques dans `LiveTrader._rebalance` (`live_trader.py:89-91`) depuis `config.py`, **aucun** argument CLI ne les surcharge (`main.py` `live` parser l.485-488 : pas de `--max-*`). L'UI ne construit **jamais** de plafond. |
| Cles | Faire fuiter une cle via la page/le log/la reponse | Le serveur n'affiche **jamais** de valeur (booleen seul, patron `render_options_page`, `monitor.py:514-516`) ; la commande live **ne recoit jamais** les cles en argument (le process les lit du `.env` via `config.py:14-15`, cf. §3.3). |
| Spawn live | Un autre chemin (lanceur, job) construit `live --execute` | `lancer.py` **ne peut pas** (`assert_paper_only`, l.60-72 + test). **Seul** `POST /live/start` (apres toute la grille) spawn `live --execute`. Aucun autre chemin autorise (§6). |

### 2.2 Invariants a coder (resume)
- **Deux round-trips serveur** irreductibles pour le reel : `/live/arm` (emet le
  nonce) **puis** `/live/start` (exige le nonce + phrase). Pas de raccourci JS.
- **Nonce** : `secrets.token_hex`, en memoire serveur, **usage unique**, **TTL
  120 s**, **lie aux parametres valides**, **plafond de 3 tentatives** de phrase.
- **Re-validation serveur a chaque round-trip** (arm ET start) des pre-requis (A).
- **Fail-safe** : absence/ambiguite -> **on ne demarre rien de reel** ; le dry-run
  ne demarre que sur `mode=="dry"` explicite + cles.
- **Aucune donnee sensible** dans HTML/log/reponse (deja garanti cote Options,
  `monitor.py:456-459,514-516` ; a maintenir).

---

## 3. Architecture process : **process live detache** (recommande + justifie)

### 3.1 Les 3 options examinees
1. **`JobManager`** (`trading/jobs.py`) : **REJETE**. Concu pour des jobs
   **finis** dont le `target` **retourne** (`jobs.py:123-149`, etat `done` +
   `result`) et une annulation **cooperative** que le `target` doit lire
   (`JobProgress.cancelled`, `jobs.py:62-65`). Or la boucle du trader est un
   `while True` **infini** (`paper_trader.py:194`) qui **ne lit jamais**
   `cancelled` et ne s'arrete que sur `KeyboardInterrupt` (`paper_trader.py:211-213`).
   L'utiliser laisserait un job "running" **eternel**, non annulable proprement,
   monopolisant le mono-job (`jobs.py:91-101`, `JobBusy`) et **bloquant la
   recherche**. Inadapte.
2. **Thread dans le serveur web** : **REJETE**. (a) Meme probleme d'arret : il
   faudrait **modifier** `_Trader.run()` (boucle partagee avec le **paper**) pour
   lire un drapeau d'arret -> risque de regression sur le paper. (b) Les **cles
   live** vivraient dans le process **reseau-facing** (le serveur ecoute sur un
   port) -> surface d'attaque accrue. (c) Un crash/exception d'un handler HTTP
   partage l'etat du thread live. (d) Si le serveur meurt, la position ouverte est
   **abandonnee sans surveillance ni stop** -> dangereux (argent reel).
3. **Process detache** (patron `paper`/`lancer.py`) : **RECOMMANDE** (§3.2).

### 3.2 Pourquoi le process detache
- **Reutilise l'outillage deja durci** : `spawn_detached` (`lancer.py:275-286`),
  fichiers PID `pid:ts` anti-recyclage (`write_pid_file` l.136-140), **verification
  d'IDENTITE** `is_our_process` (l.182-238, durcie par **BUG-009** `docs/SQA.md`),
  `terminate_pid` (l.298-328), `pid_alive` (l.150-179). Rien a reinventer.
- **Isolation des cles** : le process live lit les cles du `.env` via `config.py:14-15`
  et **n'a aucun listener reseau** -> les cles ne transitent jamais par le process
  qui ecoute le port.
- **Arret fiable et rapide** : `terminate_pid` envoie SIGTERM/taskkill au niveau
  **OS** -> interrompt immediatement le `time.sleep(poll_seconds)` du cycle
  (`paper_trader.py:223`, poll jusqu'a 3600 s en 1h) ; le process meurt en **< 5 s**
  (timeout `terminate_pid`), **independamment** de l'intervalle de poll.
- **Verrou "un seul live"** natif via le fichier PID + `is_our_process` (patron
  `_start_service`, `lancer.py:406-422`).

### 3.3 Cles : pourquoi le live exige des cles **.env persistees**
- Le process detache `python main.py live` **relit** `config.KRAKEN_API_KEY/SECRET`
  (`config.py:14-15`) charge du `.env` par `dotenv` (`config.py:7-11`) **a son
  propre demarrage**. Les cles "**session seulement**" gardees en **memoire du
  serveur** (`_session_keys`, `monitor.py:638,1103`) **n'atteignent pas** le
  subprocess.
- **Decision** : le live (dry **et** reel) exige des cles **ecrites dans `.env`**
  (`keys_configured()` lit le `.env`, `options.py:137-154`). C'est **coherent** :
  le pre-requis A.1 = `keys_configured()` = cles dans `.env`. Les cles session
  restent utiles pour le **test de liaison** en lecture seule d'Options
  (`docs/UI_UX_WEBAPP_SPEC.md` §11.3), pas pour passer des ordres.
- **Interdit** : passer les cles au subprocess par **argument** (fuite dans la
  liste des process) **ni** par variable d'environnement injectee (fuite dans
  l'inspection du process). Le subprocess les lit du `.env`, point.

### 3.4 Spawn du process live (detail)
- **Dry-run** : `spawn_detached([python, main.py, "live", "--strategy", S,
  "--symbol", SYM, "--timeframe", TF, <risque>], log=logs/live_console.log,
  cwd=root)` (**sans** `--execute`), `stdin=DEVNULL` comme
  `lancer.py:284`. `cmd_live` part en dry-run (`dry_run = not args.execute`,
  `main.py:262`) : **aucun ordre**.
- **Reel** : **meme commande + `--execute`**, mais **`stdin=PIPE`** : le serveur
  **ecrit `OUI JE CONFIRME\n`** dans le stdin du subprocess puis **ferme** stdin.
  Ainsi **`cmd_live` reste INCHANGE** : son `input(...).strip() != "OUI JE
  CONFIRME"` (`main.py:276`) lit **notre** phrase pipee et **re-valide au niveau
  process** ; sa verification des cles (`main.py:260-261`) tourne aussi -> **3e
  rempart**. Si le serveur etait force a spawner sans phrase, `cmd_live` recevrait
  EOF -> abandon, 0 ordre.
  > Cela impose une **petite variante** de `spawn_detached` acceptant `stdin=PIPE`
  > (ecrire les bytes puis close), sans jamais `wait()` (le process reste detache).
  > `creationflags = DETACHED_PROCESS | CREATE_NO_WINDOW` conserves
  > (`lancer.py:279-280`).
- **Refactor recommande (petit, testable)** : extraire les helpers process purs
  (`spawn_detached`, `read/write/remove_pid_file`, `read_pid_start`, `pid_alive`,
  `is_our_process`, `terminate_pid`) de `lancer.py` vers un module partage
  **`trading/proc.py`**, importe par `lancer.py` **et** par le controle live.
  Motif : le serveur ne doit **pas** importer les **constructeurs de commande** de
  `lancer.py` (qui portent `assert_paper_only`, l.60-72) — ceux-la restent
  paper-only. Seuls les helpers **neutres** sont partages. `is_our_process` accepte
  deja un `service` -> l'appeler avec `service="live"` (la cmdline contient "live").

### 3.5 Sidecar d'etat `run/live.json` (autorite serveur)
Ecrit par le serveur **au moment du spawn** (jamais par le client) :
`{ "mode": "reel"|"dry", "strategy", "symbol", "timeframe", "pid", "start_ts" }`.
**Sans aucune cle.** Sert a la page "live en cours" pour afficher le **bon
bandeau** (reel vs simulation, non confondable) et le recap. Ne **jamais** deduire
le mode d'une donnee cliente. (Alternative acceptable : lire la 1re ligne
"LiveTrader initialise en mode ..." de `live_trades.log`, `trading/live_trader.py:46-47`
— mais le sidecar serveur est plus robuste.)

### 3.6 Survie au crash du serveur web : **le live SURVIT** (recommande)
- **Recommandation : le process live SURVIT** a l'arret/crash du serveur web (il
  est detache : `DETACHED_PROCESS` / `start_new_session`, `lancer.py:278-282`).
- **Pour** (retenu) : la boucle de **gestion du risque** (stop-loss/trailing/
  take-profit, `paper_trader.py:153-178`) **continue de proteger le capital** meme
  si l'UI tombe ; modele **identique au paper** ; le process est **retrouve** au
  prochain `GET /live` via `run/live.pid` + `is_our_process` (patron
  `lancer.py:354-371` `do_status`) -> jamais "perdu".
- **Contre** (mitige) : un live detache pourrait etre "oublie" -> **mitigation** :
  (a) l'Accueil et `/live` **re-detectent** et affichent en evidence "LIVE REEL EN
  COURS (PID x, depuis HH:MM)" + bouton Arreter ; (b) afficher l'horodatage de
  demarrage (sidecar) ; (c) option future : duree max de run.
- **Alternative rejetee** ("mourir avec le serveur") : fermer le navigateur **ne
  tue pas** le serveur (process separe lance par `lancer.bat`) ; seul un
  crash/arret du serveur declencherait la mort -> abandonnerait une **position
  ouverte sans stop** -> **mode de defaillance dangereux**. Rejete comme defaut.

### 3.7 Monitoring du live (lecture seule)
Reutiliser le patron read-only du monitor (relecture fichiers a chaque requete,
`trading/monitor.py:644-650`) mais sur les **fichiers live** :
`live_trades.log` (`trading/live_trader.py:20`) et `live_stats.csv`
(`trading/live_trader.py:34`, ecrit par `StatsRecorder`). Le serveur **ne touche
jamais** le trading (il lit) — invariant deja pose (`trading/monitor.py:5-7`).

---

## 4. Ce qui s'affiche (et ce qui ne s'affiche JAMAIS)

- **Plafonds `config.py` toujours visibles** avant toute execution : `MAX_TRADE_VALUE_USD`
  (100 $, `config.py:57`), `MAX_POSITION_VALUE_USD` (500 $, `config.py:58`),
  `MIN_TRADE_INTERVAL_SEC` (3600 s, `config.py:59`). Sur le mur **et** dans le recap.
- **Etat dry-run vs reel IMPOSSIBLE a confondre** (accessibilite : couleur
  **+ libelle + position**, jamais la couleur seule, `docs/UI_UX_WEBAPP_SPEC.md`
  §8 l.695) :
  - **REEL** : bandeau **rouge** permanent, libelle "ARGENT REEL — ordres passes".
  - **SIMULATION** : bandeau **ambre/bleu**, libelle "SIMULATION (dry-run) — aucun
    ordre reel". Le mode vient du sidecar serveur (§3.5).
- **Journal des ordres** : tail de `live_trades.log` (lecture seule, patron
  `tail_log`, `trading/monitor.py:121-131`). Distinguer visuellement les lignes
  **`[DRY-RUN] ACHAT prevu`** (`live_trader.py:97`) des **`ACHAT EXECUTE`**
  (`live_trader.py:100`).
- **PnL / equity / exposition** : derives de `live_stats.csv` (patron
  `read_last_stats` + `compute_view`, `trading/monitor.py:83-118,188-244`) applique
  aux fichiers live.
- **"Arreter immediatement"** toujours visible en live + message : "Arrete le bot.
  **Ta position ouverte sur Kraken reste** — gere-la sur Kraken ; le bot ne
  liquide pas." (l'arret ne vend pas, §3.6/§1.7).
- **JAMAIS** : la valeur d'une cle (booleen OUI/NON seul, patron `monitor.py:514-516`),
  aucun secret dans un message d'erreur (patron `main.py:311-315`, `monitor.py:992-999`).

---

## 5. Plan de tests exige pour la gate (sans reseau ni cles reelles)

> Gate SQA (`docs/SQA.md` §4) : `pytest` vert sans reseau ; **chaque garde serveur
> a son test** ("pas de test = bug ouvert", `docs/SQA.md` §2). Patron d'integration :
> `tests/test_monitor_server.py` (vrai HTTP loopback, port ephemere, fixtures
> `server`/`server_with_jobs`, `_csrf_token`, `_post`). **Le spawn reel est
> monkeypatche** par un **enregistreur** (fake) qui capture la commande + le stdin
> pipe et ne lance **aucun** process ; `keys_configured`, `_last_check`,
> `state_path.exists`, `is_our_process`, `terminate_pid` sont monkeypatches.

### 5.1 Tests purs (`tests/test_live_page.py`)
1. `test_live_page_dry_run_selectionne_par_defaut` — radio dry-run `checked`, reel non.
2. `test_live_page_affiche_les_plafonds_config` — presence de 100 / 500 / 3600.
3. `test_live_page_ne_contient_jamais_de_cle` — meme cles positionnees, aucune valeur
   dans le HTML (patron `test_route_options_formulaire_et_liens`).
4. `test_live_page_reel_verrouille_si_prerequis_manquant` — un flag serveur "reel
   accessible" faux quand cles/check/paper manquent ; message du pre-requis fautif.
5. `test_resolve_execute_defaut_dry_run` — helper `resolve_execute(form)` : `True`
   ssi `form["mode"]=="reel"` ; absent/"dry"/autre -> `False`.
6. `test_phrase_exacte_requise` — `phrase_ok("OUI JE CONFIRME")` vrai (avec espaces
   externes via strip), faux pour "oui je confirme", "OUI", "", "OUI  JE CONFIRME".
7. `test_build_live_command_reel_a_execute_sans_override_plafond` — la commande reel
   contient `live` + `--execute`, **jamais** `--max-trade-value`/`--max-position`
   (aucun override) ; la dry n'a **pas** `--execute`.
8. `test_build_live_command_ne_contient_jamais_de_cle` — aucune cle en argument.

### 5.2 Tests du store de nonce (`tests/test_live_arm.py`)
9. `test_nonce_usage_unique` — consommer 2x echoue la 2e fois.
10. `test_nonce_expire_apres_ttl` — nonce plus vieux que le TTL -> invalide.
11. `test_nonce_lie_aux_parametres` — le start utilise les params **du nonce**, pas
    ceux resoumis (params swappes ignores).
12. `test_nonce_plafond_tentatives_phrase` — apres 3 phrases fausses, nonce invalide.

### 5.3 Tests d'integration HTTP (`tests/test_live_server.py`)
13. `test_route_live_get_mur` — 200, bandeau rouge, plafonds, dry-run par defaut,
    host verifie.
14. `test_route_live_absente_de_la_nav_principale` — `page_shell` ne rend **pas**
    `/live` en onglet actif/enabled ; lien discret seulement.
15. `test_route_live_arm_sans_csrf_403`.
16. `test_route_live_arm_prerequis_cles_manquantes_refuse` — `keys_configured`
    monkeypatch `False` -> pas de nonce, message ; aucun spawn.
17. `test_route_live_arm_check_non_ok_refuse` — `_last_check` vide -> refus.
18. `test_route_live_arm_paper_jamais_lance_refuse` — `state_path.exists` False -> refus.
19. `test_route_live_arm_attestation_manquante_refuse` — une case (B) absente -> refus.
20. `test_route_live_arm_tout_ok_emet_nonce_et_recap` — 200, ecran recap **servi
    serveur**, champ phrase + nonce + plafonds presents.
21. `test_route_live_start_sans_csrf_403`.
22. `test_route_live_start_sans_nonce_refuse_sans_spawn` — POST start direct sans
    nonce -> refus ; l'enregistreur de spawn **n'est pas appele**.
23. `test_route_live_start_phrase_incorrecte_refuse_sans_spawn` — nonce valide mais
    phrase "oui" -> refus, aucun spawn reel.
24. `test_route_live_start_nonce_consomme_pas_de_rejeu` — 1er start reel OK (spawn
    reel enregistre **une** fois) ; rejeu du meme POST -> refus, spawn **non** rappele.
25. `test_route_live_start_mode_absent_ne_demarre_rien` — POST valide CSRF mais
    `mode` absent -> aucun spawn (ni reel ni dry).
26. `test_route_live_start_reel_spawn_detache_execute_et_pipe_phrase` — chemin
    complet (tout monkeypatch OK) : l'enregistreur recoit `live --execute ...`
    **et** le stdin pipe == `OUI JE CONFIRME`. Aucun reseau.
27. `test_route_live_start_reel_refuse_si_cles_disparues_au_start` — nonce valide
    mais `keys_configured` re-teste `False` au start -> refus (re-validation start).
28. `test_route_live_un_seul_live` — `is_our_process` monkeypatch `True` (live deja
    en cours) -> nouveau start refuse, page "en cours".
29. `test_route_live_start_dry_run_exige_cles_pas_de_phrase` — `mode=dry` + cles OK
    -> spawn **sans** `--execute` ; cles absentes -> refus.
30. `test_route_live_stop_sans_csrf_403`.
31. `test_route_live_stop_termine_pid_confirme` — `is_our_process` True -> `terminate_pid`
    appele (monkeypatch), `run/live.pid` supprime.
32. `test_route_live_stop_refuse_pid_non_confirme` — `is_our_process` False ->
    `terminate_pid` **non** appele, pid file nettoye (patron BUG-009).
33. `test_route_live_bandeau_lit_mode_du_sidecar` — `run/live.json` mode=reel ->
    bandeau ROUGE ; mode=dry -> bandeau SIMULATION.
34. `test_route_live_journal_lit_live_log_lecture_seule` — tail de `live_trades.log`
    affiche ; le serveur n'ecrit jamais dedans.

### 5.4 Test de non-regression du garde paper-only
35. `test_lanceur_ne_construit_jamais_live` — conserver/renforcer le test existant
    de `assert_paper_only` (`lancer.py:60-72`, `tests/test_launcher.py`) : aucune
    commande du lanceur ne contient "live".

---

## 6. Criteres de NO-GO (font echouer la revue P0)

La revue **REJETTE** le Lot 8 si l'un de ces points est vrai :

- **N1 — Garde uniquement en JS.** N'importe quel controle (phrase, pre-requis,
  desactivation du bouton reel, mode) qui n'existe **que** cote client, sans
  re-validation serveur. (La double confirmation doit etre **deux round-trips
  serveur**, pas deux clics JS.)
- **N2 — Reel en un seul round-trip.** Le mode reel atteignable sans le couple
  `/live/arm` **puis** `/live/start` (nonce d'armement absent, ou non usage-unique,
  ou non lie aux parametres, ou sans TTL).
- **N3 — Dry-run pas par defaut.** Le mode par defaut n'est pas dry-run, **ou** un
  `mode` absent/ambigu peut demarrer du reel (fail-safe non respecte).
- **N4 — Chemin qui contourne les plafonds.** Tout parametre UI/CLI capable de
  surcharger `MAX_TRADE_VALUE_USD`/`MAX_POSITION_VALUE_USD`/`MIN_TRADE_INTERVAL_SEC`,
  ou tout code de trade qui n'applique pas `_rebalance` (`live_trader.py:89-91`).
- **N5 — Phrase non exacte.** La verification n'est pas `strip() == "OUI JE
  CONFIRME"` (`main.py:276`) cote serveur (ex. `startswith`, insensible a la casse).
- **N6 — Cles exposees.** Une valeur de cle apparait dans le HTML, un log, une
  reponse, un argument de commande ou une variable d'env du subprocess.
- **N7 — Live dans la nav / lanceur capable de live.** `/live` devient un onglet de
  `NAV_ITEMS`/`ENABLED_SCREENS`, **ou** `assert_paper_only` (`lancer.py:60-72`) est
  affaibli/retire, **ou** un autre chemin que `POST /live/start` peut spawner
  `live --execute`.
- **N8 — Boucle live dans le JobManager ou un thread serveur** (§3.1) : boucle
  infinie non annulable proprement, ou cles dans le process reseau-facing.
- **N9 — "Arreter" cosmetique.** Le bouton d'arret masque le bandeau sans
  `terminate_pid` reel, ou tue un PID **non confirme** (`is_our_process`, `lancer.py:182`).
- **N10 — Re-validation manquante au start.** Les pre-requis (A) ne sont pas
  **re-testes** au `POST /live/start` (confiance aveugle au fait que `/live/arm` a
  reussi).
- **N11 — VERIFY_SSL touche.** Toute option UI qui desactive/expose `VERIFY_SSL`
  (`config.py:61`) ; il reste `True` (`docs/SQA.md` §4).
- **N12 — Couverture de test absente.** Une garde serveur (§2) sans test de
  non-regression (§5) -> bug ouvert par definition (`docs/SQA.md` §2).

---

## 7. Annexe — routes, helpers, parametres

### 7.1 Routes a ajouter au `Handler` (`trading/monitor.py`, memes gardes que l'existant)
| Route | Methode | Gardes | Effet |
|---|---|---|---|
| `/live` | GET | `_host_ok` | Mur (verrouille) **ou** etat "live en cours" |
| `/live/arm` | POST | `_host_ok` + CSRF + pre-requis(A) + attestations(B) + `mode==reel` | Emet le nonce, rend le recap serveur |
| `/live/start` | POST | `_host_ok` + CSRF + (nonce+phrase+A pour reel / cles pour dry) | Spawn detache + PID + sidecar |
| `/live/stop` | POST | `_host_ok` + CSRF + `is_our_process` | `terminate_pid` + nettoyage |
| `/live/fragment` (option) | GET | `_host_ok` | Rafraichissement lecture seule (patron `/fragment`, `monitor.py:980-985`) |

### 7.2 Etat serveur a ajouter (en memoire, patron `monitor.py:635-642`)
- `_arm_tokens = {}` : `nonce -> {params, mode, created_ts, attempts}` (TTL 120 s,
  usage unique, plafond 3 tentatives).
- Reutiliser `_last_check` (`monitor.py:642`) pour le pre-requis "check OK".

### 7.3 Fichiers d'etat live (nouveaux, sous `run/` et racine)
- `run/live.pid` (format `pid:ts`, `write_pid_file`, `lancer.py:136-140`).
- `run/live.json` (sidecar mode/config, §3.5, **sans cle**).
- `live_trades.log` / `live_stats.csv` (deja definis, `live_trader.py:20,34`).

### 7.4 Parametres du live (formulaire -> commande)
Strategie (`STRATEGIES`), `symbol`, `timeframe`, `--stop-loss`, `--take-profit`,
`--trailing-stop`, `--position-sizing`, `--target-vol` — memes options que le
parser `live` (`main.py:485-488` + `_risk_args`/`_adv_risk_args` l.410-424).
**Jamais** `--source` (live = Kraken). **Jamais** de plafond en argument.

### 7.5 Messages reutilises tels quels (coherence CLI/web)
- Cles manquantes : "Cles API manquantes. Renseigne .env (voir .env.example) avant
  le mode live." (`main.py:261`).
- Annulation : "Annule. (Aucun ordre envoye.)" (`main.py:277`).
- Recap : paire / strategie (nom lisible) / stop-objectif / plafonds (`main.py:264-275`).
- Phrase exacte : `OUI JE CONFIRME` (`main.py:276`).

---

*Fin de la spec Lot 8. Document de conception uniquement — aucune ligne de code
livree ici. Toute implementation passe par `ui-programmer` sous revue P0
renforcee, apres feu vert utilisateur explicite, avec la gate SQA (`docs/SQA.md`
§4) et les 12 criteres de NO-GO (§6).*
