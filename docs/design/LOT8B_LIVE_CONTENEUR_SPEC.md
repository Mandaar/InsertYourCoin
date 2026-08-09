# Lot 8B — Live « production-ready en conteneur » : spec d'implementation detaillee

> Statut : **SPEC DE CONCEPTION — NON IMPLEMENTE.** P0 (argent reel).
> Ne PAS implementer sans **feu vert explicite de l'utilisateur**. Prolonge
> `docs/design/LOT8_LIVE_SPEC.md` (le live LOCAL, deja code) vers un deploiement
> **conteneurise avec restart-policy Docker**, internet-facing derriere SWAG.
> Auteur : Technical Director. Cible : l'implementeur ne prend **AUCUNE decision
> de securite ni d'architecture** lui-meme — tout est tranche ici.
> Convention : chaque fait tire du code porte `fichier:ligne` et un statut
> **MESURE** (lu dans le code) / **DERIVE** (deduit d'un fait mesure) / **SUPPOSE**
> (hypothese non verifiee, a valider a l'implementation).

---

## 0. Reference gelee, criteres d'acceptation, format de preuve (M19)

**Reference gelee (le patron a imiter, ne PAS reinventer) :**
- Persistance/reprise : `trading/paper_trader.py:284-347` (`_load_state`/`_save`/
  `_set_peak`/`_rebalance` qui persiste a chaque mutation). **MESURE.**
- Identite process anti-recyclage : `lancer.py:224-239` (`is_our_process`),
  `lancer.py:192-221` (`pid_alive`), `write_pid_file` `lancer.py:180-182`. **MESURE.**
- Spawn detache + phrase pipee sur stdin : `trading/live_control.py:271-342`
  (`spawn_live_detached`, `start_live_process`). **MESURE.**
- Verrou anti-TOCTOU du demarrage : `trading/monitor.py:1456,1525` (`_live_start_lock`,
  BUG-015). **MESURE.**
- Neutralisation web par flag d'env : `trading/paper_page.py:85-95` +
  `trading/monitor.py:1269-1289` (`IYC_DISABLE_PAPER_CONTROL`). **MESURE.**
- Friction reel (nonce/phrase) : `docs/design/LOT8_LIVE_SPEC.md` §1-§2. **MESURE.**

**Criteres d'acceptation (contrat, V9) :** les 6 problemes de §1 a §6 sont chacun
tranches avec une decision unique, justifiee, et couverte par au moins un test
nomme (§7). Les criteres de NO-GO (§8) sont tous verts.

**Format de preuve exige de la future gate :** `pytest` vert sans reseau ni cles ;
spawn Kraken + process **monkeypatches** ; chaque garde a son test (§7) ; la
checklist NO-GO (§8) cochee ligne par ligne par un acteur **independant** du
producteur (M19 aval). Rappel mesure : sur Lot 8, la gate independante a reproduit
un P0 (BUG-015) que le producteur declarait « 12/12 PASS »
(`docs/audit/GATE_LOT8_LIVE.md`, **MESURE** via SQA §5).

**Contrainte de conservation (L3, non negociable) :** apres l'implementation
future, **le paper en prod** (`docker-compose.yml` service `paper`) **et le live
LOCAL** (flux nonce web de Lot 8) doivent rester **strictement inchanges** quand
les nouveaux flags/fichiers sont absents. Tout comportement nouveau est active
**uniquement** par la presence d'un flag d'env ou d'un fichier marqueur ; leur
absence = comportement actuel a l'octet pres.

---

## 0bis. Corpus d'erreurs deja documente (M17) — ce qu'il impose au design

Recherche faite dans le corpus projet (`docs/SQA.md` §5 ; pas de `docs/errors/`).
Quatre bugs **directement** applicables — le design les honore par construction :

| Bug (SQA §5) | Ce qu'il a mordu | Ce que la spec en tire |
|---|---|---|
| **BUG-009** (P2) | PID Windows recycle → un pid rance pointe un process tiers ; decider sur `pid_alive` (existence) au lieu de `is_our_process` (identite) | Toute detection « live en cours » (reprise, verrou, arret) passe par `is_our_process(pid,"live",start_ts)` (lancer.py:224-239), jamais par la seule existence. **§1.4, §2.4, §3.2.** |
| **BUG-014** (P1) | Respawn : thread daemon tue avant le `Popen` ; `open(log,'ab')` bloque sur verrou exclusif ; `except OSError: pass` avale l'echec | Le superviseur : process non-daemon par construction (PID 1), **log dedie** `live_console.log` (patron live_control.py:329), **repli DEVNULL** si verrou (live_control.py:294-297), **jamais** d'echec avale (M9, §5). |
| **BUG-015** (P0) | **Race TOCTOU → DEUX `live --execute` concurrents sur le meme compte Kraken** ; chacun applique `MAX_POSITION_VALUE_USD` contre SA lecture du solde → exposition agregee reelle > plafond | Le superviseur garantit **un seul enfant vivant** (verrou + `is_our_process` avant tout spawn) ; le web conteneur ne spawne rien (§3). C'est LE mode de defaillance a prevenir. **§2.4, C-BUG15 en NO-GO.** |
| **BUG-016** (P2) | Meme TOCTOU cote paper (check→spawn→pid sans verrou) | Meme discipline de verrou pour toute sequence check→spawn→ecriture-pid nouvelle. **§2.4.** |

---

## 0ter. Le probleme, en une phrase, et les faits qui le fondent

Le live LOCAL suppose une **session attendue par un humain** : le process est
lance depuis le serveur web, le `peak` du trailing vit **en memoire seule**
(live_trader.py:42, commentaire *« suivi EN MEMOIRE »*, **MESURE**), et la
confirmation `OUI JE CONFIRME` est **interactive** (main.py:277, `input(...)`,
**MESURE**). Trois hypotheses qui **tombent toutes** en conteneur avec
`restart: unless-stopped` :

| Hypothese locale | Fait conteneur | Consequence si non traite |
|---|---|---|
| L'humain relance et re-confirme | Docker relance seul | Le prompt `input()` **bloque sans TTY** (`docs/DEPLOY_DOCKER.md:262-266`, **MESURE**) → le service ne demarre jamais, OU on retire la friction et il demarre **par accident** |
| L'etat de risque tient en memoire | Le conteneur redemarre → memoire perdue | Position ouverte **sans trailing/stop** apres restart (voir ci-dessous) |
| Le bouton web pilote le process local | Le web (monitor) et le live sont **2 conteneurs** | Un spawn web naitrait DANS le monitor → mort a son restart, isole du volume ; et `terminate_pid` ne traverse pas les namespaces PID |

**Le danger n°1, mesure dans le code :** au demarrage, `LiveTrader` **detecte**
qu'il detient une position via Kraken — `_is_invested(price)` renvoie vrai des que
`_base_balance()*price > 1.0` (live_trader.py:55-56, **MESURE**) — mais
`entry_price` et `peak` valent `None` (live_trader.py:41-42, **MESURE**). Or
`_risk_overlay` **sort immediatement** si `entry_price` est faux :
`if not (self._is_invested(price) and ep): return desired, None`
(paper_trader.py:159-160, **MESURE**). **DERIVE :** apres un restart conteneur,
une position ouverte n'a **plus aucun stop-loss ni trailing** jusqu'a ce qu'un
signal de strategie la ferme — exactement le mode de defaillance que ces
garde-fous existent pour empecher.

---

## 1. Persistance et reprise sure de l'etat live (le coeur)

### 1.1 Decision d'architecture

**Le `LiveTrader` persiste son etat de suivi sur le volume, et a chaque
demarrage il RECONCILIE cet etat avec les soldes reels Kraken, l'exchange faisant
foi.** On imite le patron paper (`_load_state`/`_save`, paper_trader.py:284-297)
mais avec une difference structurelle imposee par la nature du live.

**Difference structurelle (DERIVE) :** en paper, `cash` et `base_amount` sont
la **verite** (argent fictif, paper_trader.py:292-294). En live, la verite de
« combien je detiens » et « combien de cash » vient de **Kraken** :
`_base_balance()`/`_quote_balance()` appellent `fetch_balance()`
(live_trader.py:49-53, **MESURE**). Donc l'etat persiste **ne doit PAS** stocker
cash/quantite (Kraken les redonne) ; il stocke **uniquement** ce que Kraken ne
peut pas redonner : le prix d'entree, le plus-haut, l'horodatage et le cout
d'entree — les ancres du calcul de risque.

### 1.2 Fichier d'etat : `/data/live_state.json`

- **Ou :** racine du volume `iyc_data` (comme `paper_state.json`, docker-compose.yml:41-42).
  Le service `live` a `working_dir: /data` (§4) → chemin relatif `live_state.json`
  atterrit sur le volume. Le monitor le lit en absolu `/data/live_state.json` (§4).
- **Format :** JSON indente. Ecriture **atomique** : ecrire `live_state.json.tmp`
  puis `os.replace` (renommage atomique). **Justification (L7/E2) :** le volume
  peut etre un mount ou une ecriture longue est tronquee ; `paper_trader.py:296-297`
  fait un `write_text` direct — on **durcit** ici sans toucher au paper.
- **Schema (grille figee, aucun champ libre) :**

```json
{
  "version": 1,
  "mode": "reel",
  "symbol": "ETH/USD",
  "timeframe": "5m",
  "strategy": "sma",
  "invested": true,
  "entry_price": 3120.5,
  "peak": 3240.0,
  "entry_ts": 1765300000.0,
  "entry_cost": 98.7,
  "last_trade_ts": 1765300000.0,
  "updated_ts": 1765303600.0
}
```

- **AUCUNE cle API. AUCUN solde. AUCUN secret.** (Le solde vient de Kraken en
  direct ; l'ecrire figerait une valeur perimee.)
- **`last_trade_ts` DOIT etre persiste.** **MESURE :** il est en memoire
  (live_trader.py:45) et sert le garde-fou `MIN_TRADE_INTERVAL_SEC = 3600`
  (config.py:59, live_trader.py:74). **DERIVE :** sans persistance, un restart le
  remet a 0 → le delai minimum entre ordres est **contourne** par un simple
  redemarrage. Le persister ferme ce trou.

### 1.3 Quand ecrire

Aux memes points que le paper (paper_trader.py:305-346) : a chaque mutation de
`peak` (`_set_peak` persiste, comme paper_trader.py:305-308), a chaque achat et
a chaque vente (dans `_rebalance`, live_trader.py:82-131). Chaque ecriture met
`updated_ts = time.time()`.

### 1.4 Semantique de reprise (la table de verite — l'exchange fait foi)

Au demarrage, apres avoir instancie `LiveTrader`, appeler **une methode nouvelle
`reconcile()`** AVANT d'entrer dans `run()`. Elle lit l'etat persiste (s'il
existe), interroge `fetch_balance()` + `fetch_price()` une fois, et applique :

| Kraken dit | Etat persiste dit | Decision (l'exchange FAIT FOI) |
|---|---|---|
| **INVESTI** (`base*price > seuil`) | INVESTI, `entry_price` present | **REPRISE NORMALE** : restaurer `entry_price`/`peak`/`entry_ts`/`entry_cost`/`last_trade_ts` depuis l'etat. Le trailing reprend a partir du `peak` memorise. |
| **INVESTI** | FLAT, ou etat absent, ou `entry_price` absent | **DIVERGENCE — ADOPTION DEFENSIVE** : on detient une position sans base de cout connue. On **adopte** la position : `entry_price = peak = prix courant`, `entry_ts = now`, `entry_cost = base*price`, `invested = true`. **Log WARNING loud (M9)**. Puis persister. |
| **FLAT** (`base*price <= seuil`) | INVESTI | **DIVERGENCE — RETOUR A PLAT** : la position a ete fermee pendant l'arret (vente manuelle, stop ailleurs). On **est plat** : effacer `entry_price`/`peak`/`entry_ts`/`entry_cost`, `invested = false`. **Log WARNING (M9)**. Ne JAMAIS re-acheter sur un etat perime. |
| **FLAT** | FLAT / absent | **REPRISE NORMALE PLATE** : rien a restaurer. |

**Seuil « investi » :** reutiliser EXACTEMENT `_is_invested` (base*price > 1.0,
live_trader.py:55-56) — meme critere partout, jamais un seuil parallele (V12 :
pas de seuil derive ad hoc).

**Pourquoi l'adoption defensive et pas le refus/liquidation (justification du
compromis M20) :**
- *Ce qu'on obtient :* une position orpheline est **immediatement re-protegee**
  par un trailing/stop ancre a « maintenant ». Un stop ancre au prix courant ne
  peut declencher qu'une **vente de protection**, jamais un achat parasite —
  c'est conservateur par construction.
- *Ce qu'on abandonne :* la base de cout exacte de ce trade → son **PnL affiche
  sera approximatif** (live_trader.py:112-116 signale deja que le PnL live est
  approximatif — coherent).
- *Ce que ca coute :* il faut que **le solde de l'actif trade appartienne au
  bot** (voir 1.5). L'alternative « liquider a la reprise » est **REJETEE** : elle
  viole l'honnetete « arreter n'est pas liquider » (consigne user, §5) et pourrait
  vendre au pire moment.

### 1.5 Limite connue, nommee (M9, M20) : `fetch_balance` renvoie le TOTAL

**MESURE :** `fetch_balance()` renvoie le **total** de chaque actif detenu, filtre
> 0 (exchange.py:126-130). **DERIVE :** le bot **ne peut pas distinguer** l'ETH
qu'il a achete de l'ETH que l'utilisateur detenait deja. En cas d'adoption
defensive (1.4), le bot gererait **tout** le solde de l'actif.

**Decision (contrat, a documenter dans DEPLOY et sur la page /live) :** le live
conteneurise se lance sur un **(sous-)compte Kraken dedie au bot**, ou
l'utilisateur **accepte explicitement** (attestation existante famille B,
LOT8_LIVE_SPEC §1.2) que le bot gere l'integralite du solde de l'actif trade.
C'est le **compromis** (M20) : on ne peut pas resoudre l'attribution sans un
suivi d'ordres cote Kraken (hors scope) → on **borne l'usage** au lieu de
pretendre une precision qu'on n'a pas. Ce n'est **pas** un blocage :
« imparfaitement attribue » ≠ « inutilisable ».

---

## 2. Armement delibere UNE fois → marqueur persistant → reprise sans re-prompt

### 2.1 Decision d'architecture : un MARQUEUR d'armement + un SUPERVISEUR

Le service conteneur `live` **n'execute pas** `main.py live --execute`
directement (il bloquerait sur `input()`, main.py:277, et ne saurait pas
reprendre l'etat). Il execute un **superviseur** (`main.py live-run`, §2.4) qui :

1. lit un **marqueur d'armement** persistant sur le volume ;
2. si arme en `reel` → (re)lance un process enfant `main.py live --execute`
   (inchange), en lui **pipant la phrase** sur stdin (patron live_control.py:308-313) ;
3. surveille un **sentinelle d'arret** et le signal `SIGTERM` ;
4. si desarme / arret demande → termine l'enfant (meme namespace → `terminate_pid`
   fonctionne) **sans liquider** ;
5. si l'enfant crash → backoff + relance **tant que arme**.

### 2.2 Le marqueur : `/data/live/armed.json`

- **Contenu (grille figee, AUCUNE cle, AUCUNE phrase) :**

```json
{
  "version": 1,
  "mode": "reel",
  "strategy": "sma",
  "symbol": "ETH/USD",
  "timeframe": "5m",
  "stop_loss": 5, "take_profit": 10, "trailing_stop": 8,
  "position_sizing": "none", "target_vol": null,
  "armed_at": 1765300000.0,
  "armed_via": "cli-interactive"
}
```

- **Ecrit UNIQUEMENT par la sous-commande interactive `main.py live-arm`** (§2.3).
  Aucun autre chemin (ni web, ni superviseur) n'ecrit un marqueur `mode="reel"`.

### 2.3 Armer : `main.py live-arm` (interactif, TTY, one-shot)

Nouvelle sous-commande, lancee **une fois** par l'operateur :
`docker compose run --rm live python -u main.py live-arm --strategy sma --symbol ETH/USD --timeframe 5m --stop-loss 5 --take-profit 10 --trailing-stop 8`

Elle **reutilise a la lettre** la friction de `cmd_live` (main.py:259-278) :
1. verifie les cles (main.py:261-262) ; absentes → `sys.exit` (message main.py:262) ;
2. affiche le recap identique (main.py:264-276) ;
3. exige `input(...).strip() == "OUI JE CONFIRME"` (main.py:277) ; sinon
   `sys.exit("Annule. (Aucun ordre envoye.)")` (main.py:278) **et AUCUN marqueur
   ecrit** ;
4. si confirme → ecrit `/data/live/armed.json` (mode="reel", armed_via="cli-interactive")
   puis **exit 0 sans trader**.

**Impossible par accident (DERIVE) :** `docker compose run --rm` sans TTY (ou
stdin ferme) → `input()` recoit EOF → exception → abort → **aucun marqueur**.
Ecrire le marqueur exige donc : acces shell a l'hote **+** un terminal
interactif **+** la frappe exacte de la phrase. C'est le 3e rempart de Lot 8
(main.py:277) transpose au conteneur.

**`live-arm --dry` (optionnel) :** ecrit un marqueur `mode="dry"` **sans** exiger
la phrase (aucun ordre possible en dry, live_trader.py:96-97,119-120). Sert au
smoke-test conteneur. Le superviseur ne pipe **aucune** phrase pour un marqueur dry.

### 2.4 Le superviseur : `main.py live-run` (= command du service `live`)

Boucle (nouveau module `trading/live_supervisor.py`) :

```
installer un handler SIGTERM qui leve KeyboardInterrupt (arret propre PID 1)
boucle:
    marker = lire_marqueur(/data/live/armed.json)
    stop = existe(/data/live/stop_request)
    si stop ou marker absent/invalide/mode not in {reel,dry}:
        si un enfant CONFIRME tourne (is_our_process) -> terminate_pid(enfant) (PAS de vente)
        ecrire live_status (desarme / arret demande) ; log ; sleep(CHECK)
        continue
    si cles absentes:  # (§5)
        ecrire live_status(ERREUR cles) ; log loud ; sleep(BACKOFF)  # jamais silencieux
        continue
    # --- SEQUENCE PROTEGEE (anti-BUG-015) ---
    verrou:
        pid, running = is_our_process(run/live.pid, "live")
        si NON running:
            enfant = spawn(main.py live --execute [ou dry, sans --execute],
                           stdin = "OUI JE CONFIRME\n" si mode==reel sinon DEVNULL)
            ecrire run/live.pid (pid:ts) + run/live.json (sidecar sans cle)
    surveiller l'enfant + le sentinelle toutes les CHECK secondes
```

- **Un seul enfant, garanti (BUG-015).** Le check d'identite (`is_our_process`,
  lancer.py:224-239, **non** `pid_alive` — BUG-009) **et** le spawn **et**
  l'ecriture du pid sont dans **un seul bloc verrouille**, exactement comme
  `_live_start_lock` (monitor.py:1456,1525, **MESURE**). Deux instances de
  superviseur ne peuvent pas exister (une seule par conteneur, un seul conteneur),
  mais le verrou protege aussi le cas d'un enfant survivant + d'un nouveau cycle.
- **`CHECK`** (cadence de surveillance du sentinelle/marqueur) ~ **2 s**,
  **independante** de `poll_seconds` du trader (qui peut valoir 3600 s,
  paper_trader.py:223). C'est ce qui borne la latence de l'arret web (§3).
- **Enfant GERE, pas detache** : contrairement au live local (detache pour
  survivre au serveur web, LOT8 §3.6), ici le **superviseur EST** le PID 1 du
  conteneur `live` avec `restart: unless-stopped` → c'est **Docker** qui assure
  la survie/reprise. L'enfant est un fils du superviseur, dans **le meme
  namespace PID** → `terminate_pid` (lancer.py:298-328) fonctionne (voir §3, le
  cross-namespace est justement le probleme du web).
- **Log dedie + repli DEVNULL + jamais silencieux (BUG-014) :** le spawn ecrit
  dans `live_console.log` dedie (patron live_control.py:329) ; si verrouille →
  DEVNULL (live_control.py:294-297) ; tout echec de spawn est **journalise**, jamais
  avale (M9, patron monitor.py:1544-1548).
- **`cmd_live` reste INCHANGE** : il recoit la phrase pipee (main.py:277 la lit)
  et re-verifie les cles (main.py:261) → 3e rempart intact. La phrase est
  **legitimement** rejouee par le superviseur parce que **l'humain a deja confirme
  a l'armement** (2.3) ; le marqueur est la preuve « confirme une fois ».

### 2.5 Desarmer : `main.py live-disarm` (one-shot) ou via le web (§3)

`docker compose run --rm live python main.py live-disarm` → supprime
`/data/live/armed.json`. Au prochain `CHECK`, le superviseur termine l'enfant
(sans vendre) et idle. `docker compose stop live` reste l'arret OS garanti.

### 2.6 Reconciliation avec le flux nonce web existant

**Le flux nonce web (LOT8 §1-§2) reste le canal d'armement du LIVE LOCAL,
inchange.** En conteneur, le web est neutralise pour le demarrage (§3) : le
**marqueur CLI** est le **seul** canal d'armement. **Justification (DERIVE) :**
le nonce vit **en memoire serveur, TTL 120 s, detruit a chaque restart du
serveur** (live_control.py:90-98) — il est **structurellement incompatible** avec
un restart non attendu. Le marqueur persistant est son equivalent conteneur, sa
friction deplacee vers « shell hote + phrase interactive une fois ». Les deux
canaux ne coexistent jamais pour un meme deploiement (flag `IYC_DISABLE_LIVE_CONTROL`).

---

## 3. Bouton web `/live` en conteneur : demarrage neutralise, arret CONSERVE

### 3.1 Decision : nouveau flag `IYC_DISABLE_LIVE_CONTROL`, plus GRANULAIRE que le paper

**MESURE :** le flag paper `IYC_DISABLE_PAPER_CONTROL` refuse **start ET stop**
(paper_page.py:93-95, monitor.py:1279-1289). Pour le live, l'exigence est
differente : **start neutralise, page consultable, arret CONSERVE** (securite).
On introduit donc un flag **distinct** avec une granularite differente — on ne
reutilise PAS le flag paper.

Quand `IYC_DISABLE_LIVE_CONTROL` est vrai (parse identique a
`paper_control_disabled`, paper_page.py:85-95 : `"1"/"true"/"yes"`, insensible
casse/espaces) :

| Route | Local (flag absent) | Conteneur (flag present) |
|---|---|---|
| `GET /live` | mur + start (LOT8) | **rendu, en LECTURE SEULE** : statut reel/dry, PnL, journal ; les formulaires **arm/start (reel ET dry) sont retires** cote rendu ; bandeau « Demarrage desactive en conteneur — armer via `docker compose run --rm live live-arm` » |
| `POST /live/arm` | emet nonce (LOT8) | **REFUS serveur**, aucun nonce (patron monitor.py:1279-1289) |
| `POST /live/start` | spawn (LOT8) | **REFUS serveur** (dry ET reel), **avant tout spawn** — sinon il naitrait dans le monitor, mort a son restart, isole du volume (footgun identique au paper, DEPLOY §7) |
| `POST /live/stop` | `terminate_pid` (LOT8 §1.7) | **CONSERVE** mais **mecanisme different** (§3.2) |

Le refus start/arm se fait **cote serveur AVANT lecture de l'action** (patron
exact de `_paper_post`, monitor.py:1269-1289) : un POST forge ne spawne/arme rien
meme si CSRF + host sont satisfaits.

### 3.2 L'arret web en conteneur : sentinelle, pas `terminate_pid` (compromis M20)

**MESURE/DERIVE :** le live tourne dans le conteneur `live` ; le web dans le
conteneur `monitor`. Les **PID sont par-namespace** : `run/live.pid` ecrit par le
conteneur `live` est **denue de sens** dans le conteneur `monitor`, et
`terminate_pid` (lancer.py:298-328) **ne peut pas** tuer un process d'un autre
conteneur. Donner au monitor l'acces au **socket Docker** pour un kill
cross-conteneur est **REJETE** : surface d'attaque enorme sur un service
internet-facing.

**Decision :** en conteneur, `POST /live/stop` :
1. ecrit un **sentinelle** `/data/live/stop_request` (fichier vide horodate) ;
2. **desarme** (supprime `/data/live/armed.json`) — pour que le superviseur ne
   relance pas ;
3. rend une page « **Arret demande** — le service live s'arrete sous quelques
   secondes ; ta position ouverte sur Kraken **reste** (le bot ne liquide pas) ».

Le superviseur (§2.4), a son prochain `CHECK` (~2 s), voit le sentinelle → termine
son enfant (meme namespace, `terminate_pid` **fonctionne** la) sans vendre, puis
efface le sentinelle une fois desarme.

**Le compromis, chiffre (M20) :**
- *Ce qu'on obtient :* un « Arreter immediatement » web **toujours fonctionnel**,
  qui stoppe reellement le trading (via desarmement + sentinelle) ; l'enfant meurt
  en **~2 s (borne `CHECK`)**, pas en `poll_seconds`.
- *Ce qu'on abandonne :* le kill OS **sub-seconde** depuis le web.
- *Ce que ca coute :* deux fichiers-signaux sur le volume et une cadence de
  surveillance courte. **L'arret OS garanti** reste `docker compose stop live`
  (documente comme le kill de derniere instance).

### 3.3 Surface honnete : « position ouverte NON GEREE » (M9)

Le monitor lit `/data/live_state.json`. **DERIVE :** si l'etat dit `invested:true`
mais qu'aucun process live n'est detecte (desarme/arrete), la position est
**non protegee**. `GET /live` et l'Accueil doivent afficher, en evidence :
« **POSITION OUVERTE NON GEREE** (live desarme depuis HH:MM) — aucun trailing/stop
actif ; re-arme ou gere sur Kraken ». Jamais masquer cet etat.

---

## 4. Le service `live` dedie (SPECIFIE, NON ACTIVE)

**A documenter pour ajout ulterieur** (overlay `docker-compose.live.yml`, active
seulement par `-f docker-compose.yml -f docker-compose.live.yml`). **Ne pas
creer le fichier maintenant, ne monter aucune cle.** YAML cible :

```yaml
services:
  live:
    build: .
    image: insertyourcoin:latest
    container_name: iyc-live
    restart: unless-stopped
    init: true                      # tini : propage SIGTERM au superviseur, reap
    working_dir: /data              # live_state.json / live_trades.log / live_stats.csv / run/ sur le volume
    command: python -u /app/main.py live-run
    volumes:
      - iyc_data:/data
      - ./.env:/app/.env:ro         # CLES, LECTURE SEULE — sur CE service UNIQUEMENT, jamais paper/monitor
    networks:
      - iyc-internal                # egress Kraken uniquement
    # PAS de `ports:`  — aucun listener entrant
    # PAS du reseau `proxy`         — jamais internet-facing en entree
```

**Justifications tranchees :**
- **`restart: unless-stopped`** (comme paper, docker-compose.yml:10) : Docker
  assure la reprise apres crash ; le superviseur reprend l'etat (§1). **DERIVE.**
- **`init: true`** (comme paper, docker-compose.yml:11) : SIGTERM propage au
  superviseur PID 1 → arret propre (§2.4). **MESURE** (paper l'a deja).
- **`working_dir: /data`** : meme raison que paper (docker-compose.yml:14-19,
  **MESURE**) — les fichiers relatifs atterrissent sur le volume.
- **`./.env:/app/.env:ro`** : cles en **lecture seule**, **jamais** sur
  `paper`/`monitor` (DEPLOY §8 point 2, **MESURE**). Le process lit `.env` via
  `config.py:7-15` (**MESURE**) ; jamais de cle en argument/env du subprocess
  (LOT8 §3.3, garde N6).
- **Reseau : `iyc-internal` seul, PAS `proxy`.** **Reponse a la question posee :
  non, le service `live` n'a PAS besoin du reseau `proxy`** — il n'expose aucun
  port et ne fait que des appels **sortants** vers Kraken (egress, fourni par le
  bridge). Le mettre sur `proxy` l'exposerait inutilement. **DERIVE.**
- **Plafonds :** restent dans `config.py` (image) ; les changer exige un rebuild
  (DEPLOY §8 point 4, **MESURE**) — jamais une variable d'env silencieuse (garde N4).

**Chemins live cote monitor (a cabler) :** le monitor lit aujourd'hui
`root/"live_stats.csv"` / `root/"live_trades.log"` (monitor.py:1388-1389,
**MESURE**). En conteneur il faut que ces chemins **et** `live_state.json`
resolvent vers `/data/...`. **A trancher a l'implementation :** ajouter des
arguments `--live-state /data/live_state.json --live-log /data/live_trades.log
--live-stats /data/live_stats.csv` a la commande `monitor` (patron des
`--stats/--log/--state` du paper deja passes, docker-compose.yml:63-68). **SUPPOSE :**
sans ces arguments, le monitor conteneur lirait les fichiers live au mauvais
chemin — a valider et cabler.

**Variante SWAG (`docker-compose.eunivers.yml`) :** le service `live` y est
**identique** (memes montages, meme reseau `iyc-internal` **seul** — surtout pas
le reseau externe `proxy`). Ajouter aussi `IYC_DISABLE_LIVE_CONTROL=1` au service
`monitor` de CETTE variante et du mode dedie (§3).

---

## 5. Semantique d'arret / de crash / de cles

- **Arret (web sentinelle, `live-disarm`, `docker compose stop`) ≠ liquidation.**
  Le superviseur termine l'enfant ; **aucune vente**. La position Kraken reste ;
  message explicite (LOT8 §1.7/§4). L'etat persiste demeure → une re-arm/relance
  reprend la gestion (§1). **DERIVE de** la regle « arreter n'est pas liquider ».
- **Position desarmee non relancee = NON GEREE** → surface loud (§3.3). **M9.**
- **Crash conteneur → Docker restart (unless-stopped) → superviseur → reprise (§1).**
- **Cles absentes/invalides au demarrage — echec EXPLICITE, jamais silencieux :**
  - `cmd_live` fait deja `sys.exit` si cles absentes (main.py:261-262, **MESURE**) ;
    `fetch_balance` leve `RuntimeError` si cles manquantes (exchange.py:145-150,
    **MESURE**).
  - **Decision superviseur :** avant de spawner, `keys_configured()`
    (options.py:137-154, **MESURE**) ; si faux **et** arme → ecrire un
    `live_status` « ERREUR : cles absentes », **logger loud**, et **idle avec
    backoff** (ne PAS exit-loop qui martelerait le restart Docker, ne PAS spawner
    en boucle qui martelerait Kraken). L'operateur voit l'erreur dans les logs
    **et** sur `/live` (M9). Cles **invalides** (auth refusee) → l'enfant crash sur
    la 1re `fetch_balance` → le superviseur backoff + remonte l'erreur via
    `logs/live_error.log` (patron monitor.py:1544-1548, **MESURE**) et `live_status`.

---

## 6. Ce qui ne bouge pas (conservation, L3)

- **Paper (prod) inchange** : services `paper`/`monitor` de `docker-compose.yml`
  et `docker-compose.eunivers.yml` intacts ; `IYC_DISABLE_PAPER_CONTROL` inchange.
- **Live LOCAL inchange** : sans `IYC_DISABLE_LIVE_CONTROL` et sans marqueur, le
  flux nonce web de Lot 8 se comporte a l'octet pres comme specifie (LOT8 §1-§2).
- **`cmd_live` inchange** (main.py:259-280) : les nouveaux chemins l'appellent
  tel quel (phrase pipee, 3e rempart).
- **`_Trader.run()` inchange** (paper_trader.py:180-223) : pas de drapeau d'arret
  ajoute a la boucle partagee (aucune regression paper). L'arret passe par le
  signal OS sur l'enfant (KeyboardInterrupt via SIGTERM handler du superviseur,
  qui exploite le `break` existant paper_trader.py:211-213).

---

## 7. Plan de tests exige (sans reseau ni cles ; spawn + Kraken mockes)

> Patron : `tests/test_monitor_server.py` (HTTP loopback, port ephemere, CSRF,
> `_post`) + fake exchange (conftest) + spawn/`terminate_pid`/`is_our_process`/
> `keys_configured` monkeypatches. Chaque garde a son test (`docs/SQA.md` §2).

**Persistance & reprise (`tests/test_live_state.py`)**
1. `test_live_state_roundtrip` — sauve/relit tous les champs (§1.2), ecriture atomique.
2. `test_live_state_sans_cle_ni_solde` — le JSON ne contient jamais cle/solde/cash.
3. `test_reconcile_reprise_normale_investie` — Kraken investi + etat investi → restaure entry/peak/entry_ts/entry_cost/last_trade_ts.
4. `test_reconcile_divergence_kraken_investi_etat_flat` — adoption defensive : entry=peak=prix courant, WARNING loggue, persiste.
5. `test_reconcile_divergence_kraken_flat_etat_investi` — retour a plat, WARNING, pas de re-achat.
6. `test_reconcile_etat_absent_kraken_investi` — adoption defensive (etat absent).
7. `test_last_trade_ts_survit_au_restart` — cooldown non contourne par un redemarrage.
8. `test_risk_overlay_actif_apres_reprise` — apres reprise investie, `_risk_overlay` applique bien stop/trailing (non-regression du danger n°1 : paper_trader.py:159-160 ne sort plus).

**Armement / marqueur / superviseur (`tests/test_live_supervisor.py`)**
9. `test_live_arm_ecrit_marqueur_apres_phrase` — phrase exacte → marqueur mode=reel, armed_via=cli-interactive.
10. `test_live_arm_phrase_fausse_aucun_marqueur` — phrase != → sys.exit, aucun fichier.
11. `test_live_arm_sans_tty_aucun_marqueur` — stdin EOF → abort, aucun marqueur.
12. `test_live_arm_cles_absentes_refuse` — keys_configured False → sys.exit, aucun marqueur.
13. `test_superviseur_desarme_idle_sans_spawn` — marqueur absent → aucun spawn (enregistreur non appele).
14. `test_superviseur_arme_reel_spawn_execute_et_pipe_phrase` — marqueur reel → enfant `live --execute` + stdin == `OUI JE CONFIRME`.
15. `test_superviseur_arme_dry_spawn_sans_execute_ni_phrase` — marqueur dry → pas de `--execute`, stdin DEVNULL.
16. `test_superviseur_un_seul_enfant_anti_toctou` — enfant deja confirme (`is_our_process` True) → aucun 2e spawn (non-regression BUG-015, sequence verrouillee).
17. `test_superviseur_sentinelle_termine_enfant` — stop_request present → terminate_pid(enfant) appele (mock), pas de vente, sentinelle efface apres desarmement.
18. `test_superviseur_sigterm_termine_enfant_sans_liquider` — SIGTERM → terminate enfant, aucun ordre de vente emis.
19. `test_superviseur_enfant_crash_relance_si_arme` — crash simule → relance avec backoff tant que arme.
20. `test_superviseur_cles_absentes_erreur_explicite_pas_de_spawn` — arme + keys absentes → live_status ERREUR + log, aucun spawn, aucun martelement.
21. `test_superviseur_ne_tue_pas_pid_non_confirme` — pid rance (`is_our_process` False) → jamais terminate_pid (non-regression BUG-009).

**Web conteneur (`tests/test_live_container_web.py`)**
22. `test_web_live_start_refuse_en_conteneur_reel_et_dry` — flag actif → POST /live/start (reel et dry) refuse **avant** tout spawn (enregistreur non appele).
23. `test_web_live_arm_refuse_en_conteneur` — flag actif → POST /live/arm → aucun nonce.
24. `test_web_live_get_lecture_seule_en_conteneur` — flag actif → /live rendu, formulaires start retires, statut visible.
25. `test_web_live_stop_conteneur_ecrit_sentinelle_et_desarme` — flag actif → /live/stop ecrit stop_request + supprime armed.json, **n'appelle PAS** terminate_pid.
26. `test_web_live_stop_local_appelle_terminate_pid` — flag absent → comportement Lot 8 (terminate_pid) inchange.
27. `test_web_position_non_geree_affichee` — live_state invested + aucun process → banniere « non geree ».

**Non-regression / conservation**
28. `test_paper_control_inchange` — `IYC_DISABLE_PAPER_CONTROL` toujours start+stop refuses.
29. `test_live_local_flux_nonce_inchange` — sans flag ni marqueur, le flux LOT8 est identique.
30. `test_plafonds_non_surchageables_conteneur` — aucun arg/env ne surcharge MAX_* (garde N4).
31. `test_cmd_live_inchange` — signature/comportement de `cmd_live` identiques.
32. `test_cles_jamais_en_argument_ni_env_enfant` — l'enfant ne recoit aucune cle (arg/env) — garde N6.

---

## 8. Criteres de NO-GO (font echouer la gate P0)

> Les **N1-N12 de `docs/design/LOT8_LIVE_SPEC.md` §6 restent en vigueur**. On
> ajoute les criteres propres au conteneur :

- **C1 — Reprise aveugle.** Le live ne persiste pas son etat de risque, ou reprend
  une position ouverte **sans restaurer/ancrer** un trailing/stop (danger n°1,
  paper_trader.py:159-160).
- **C2 — Etat prime sur l'exchange.** Une reprise achete/vend sur l'etat persiste
  au lieu de reconcilier avec Kraken ; l'exchange ne fait pas foi sur la divergence.
- **C-BUG15 — Plusieurs live sur le meme compte.** Le superviseur (ou un chemin
  web) peut faire coexister **deux** process `live --execute` → exposition agregee
  > plafond (regression BUG-015). La sequence check→spawn→pid n'est pas verrouillee,
  ou utilise `pid_alive` au lieu de `is_our_process` (BUG-009).
- **C3 — Marqueur sans phrase.** `armed.json` mode=reel ecrit sans la phrase
  interactive, ou ecrit sans TTY, ou par le web/le superviseur.
- **C4 — Demarrage accidentel.** Le superviseur peut passer des ordres reels sans
  un marqueur `reel` valide (fail-safe non respecte).
- **C5 — Web mal cloisonne.** En conteneur, le start web n'est pas neutralise
  (spawn dans le monitor), OU l'« Arreter » web n'est plus fonctionnel.
- **C6 — Arret cosmetique cross-namespace.** `/live/stop` conteneur appelle
  `terminate_pid` (no-op dans le monitor) au lieu du sentinelle+desarmement.
- **C7 — Cles mal montees.** `.env` monte sur `paper`/`monitor`, ou non
  read-only, ou cle en argument/env de l'enfant (N6).
- **C8 — Echec silencieux des cles.** Cles absentes/invalides → idle muet, ou
  restart-loop qui martele Kraken, au lieu d'une erreur surfacee (M9).
- **C9 — Arret qui liquide.** Un arret (web/disarm/SIGTERM) vend la position.
- **C10 — Plafonds surchargeables en conteneur.** Un env/arg contourne MAX_* (N4).
- **C11 — Desarmement inefficace.** Apres desarmement, le superviseur relance
  quand meme l'enfant.
- **C12 — Regression du paper ou du live local.** Un comportement change quand les
  flags/fichiers nouveaux sont absents (L3).
- **C13 — Garde sans test.** Une garde de §8/§7 sans test de non-regression
  (`docs/SQA.md` §2) → bug ouvert par definition.

---

## 9. Changements de code impliques (pour dimensionner l'implementation)

Aucun code n'est ecrit ici. La spec **implique** :

1. **`trading/live_trader.py`** — ajouter `state_file` (defaut `/data`-relatif),
   `_load_state`/`_save` (atomique), persistance de `entry_price/peak/entry_ts/
   entry_cost/last_trade_ts` aux points de mutation, `_set_peak` qui persiste,
   et une methode **`reconcile()`** (table §1.4). ~ mirroir de paper_trader.py:284-347.
2. **`trading/live_supervisor.py`** (NOUVEAU) — boucle superviseur (§2.4) : lecture
   marqueur + sentinelle, sequence spawn/terminate enfant VERROUILLEE (anti-BUG-015),
   handler SIGTERM, backoff, precheck cles, ecriture `live_status`.
3. **`trading/live_control.py`** (extension) — lecture/ecriture/suppression du
   marqueur `armed.json`, du sentinelle `stop_request`, du `live_status` ; fonctions
   PURES testables (patron des helpers existants live_control.py:215-266).
4. **`main.py`** — 3 sous-commandes : `live-arm` (interactif, phrase, ecrit
   marqueur), `live-disarm` (supprime marqueur), `live-run` (lance le superviseur).
   `cmd_live` **INCHANGE**.
5. **`trading/monitor.py`** — `_live_arm_post`/`_live_start_post` : refus serveur
   si `IYC_DISABLE_LIVE_CONTROL` (patron monitor.py:1269-1289) ; `_live_stop_post` :
   branche conteneur (sentinelle+desarmement) vs local (terminate_pid) ; `_live_get`
   variante lecture seule + surface « position non geree » ; cabler les chemins live
   vers `/data` (§4).
6. **`trading/live_page.py`** — variante lecture-seule du mur (start masque, stop
   conserve) + banniere « position ouverte non geree ».
7. **`docker-compose.live.yml`** (NOUVEAU, overlay, ajoute plus tard) — service
   `live` (§4) ; + `IYC_DISABLE_LIVE_CONTROL=1` sur `monitor` des deux composes.
8. **`docs/DEPLOY_DOCKER.md`** — reecrire §8 avec la procedure reelle (arm/disarm,
   overlay, kill de derniere instance `docker compose stop live`).
9. **`docs/SQA.md`** — a l'implementation, la gate P0 (BUG-015 est un precedent) :
   toute garde §8 sans test = bug ouvert.
10. **Tests** — les 32 tests de §7 (nouveaux fichiers).

**Estimation d'ampleur (SUPPOSE, a affiner par le producer) :** ~2 modules
nouveaux + 5 modules touches + 3 fichiers de tests. Le gros du risque est
concentre sur `reconcile()` (§1.4) et le superviseur (§2.4, anti-BUG-015) — a
gater en priorite par un acteur independant.

---

*Fin de la spec Lot 8B. Document de conception uniquement — aucune ligne de code,
aucun compose modifie, aucune cle montee. Toute implementation passe par
`ui-programmer`/`lead-implementer` sous revue P0 renforcee, apres feu vert
utilisateur explicite, avec la gate SQA (`docs/SQA.md` §4), les NO-GO de LOT8 §6
ET de §8 ci-dessus, controle par un acteur independant du producteur (M19 aval).*
