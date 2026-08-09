# Déploiement Docker — paper trading + monitoring sur un serveur Debian distant

> Objectif : faire tourner **InsertYourCoin en paper trading** (argent fictif, prix
> réels Kraken) **plusieurs semaines sans surveillance** sur un petit serveur Debian,
> accumuler les données (`paper_stats.csv`), et consulter le tableau de bord depuis
> ton navigateur, **en HTTPS, avec mot de passe**, où que tu sois.
>
> **Phase 1 (ce document) : AUCUNE clé API Kraken.** Le paper trading n'a besoin que
> de données publiques. La section « Ajouter le live plus tard » explique le chemin
> pour la suite, sans rien activer aujourd'hui.

---

## 0. Ce que tu obtiens (architecture)

```
                     Internet (HTTPS, port 443)
                            |
                            v
                    ┌───────────────┐
                    │  proxy (Caddy) │  <- SEUL service qui publie un port
                    │  TLS + mot de  │     sur l'hôte (443, + 80 pour ACME)
                    │  passe (bcrypt)│
                    └───────┬────────┘
                            | réseau Docker interne (iyc-internal)
                            v
                    ┌────────────────┐        lit (jamais n'écrit le trading)
                    │ monitor          │◄──────────────┐
                    │ dashboard web    │                │
                    │ (port 8765,      │                │
                    │  jamais publié)  │                │
                    └────────────────┘                │
                                                         │
                    ┌────────────────┐   écrit dans   │
                    │ paper            │────────────────┘
                    │ boucle de trading│
                    │ (argent fictif)  │
                    └────────────────┘
                            │
                            v
                    volume Docker nommé  iyc_data
                    (paper_state.json, paper_stats.csv,
                     paper_trades.log — persiste aux redémarrages)
```

Trois conteneurs (`docker-compose.yml`), un volume de données persistant, un réseau
Docker interne où seul `proxy` est exposé.

> **Deux variantes de déploiement, un seul projet.** Ce document (§1 à §12) couvre le
> **mode dédié** : ce serveur t'appartient entièrement, `proxy` (Caddy) est le seul
> service qui publie 80/443. Si tu déploies sur un **serveur mutualisé où un
> reverse-proxy existe déjà** (SWAG, Traefik, nginx…) et détient ces ports pour
> plusieurs projets — va directement à **§13**, qui documente `docker-compose.eunivers.yml`
> (variante sans Caddy, additive, n'affecte en rien ce que tu lis ici).

**Le compromis assumé (M20)** — ce qu'on obtient / ce qu'on abandonne / ce que ça
coûte :
- **Obtenu** : accès web HTTPS authentifié depuis n'importe où, données qui survivent
  aux redémarrages/mises à jour, paper trading supervisé automatiquement par Docker
  (`restart: unless-stopped`), zéro clé API exposée.
- **Abandonné (documenté §7)** : le bouton **« Démarrer/Arrêter le paper »** de la
  page web `/paper` est **désactivé par construction** dans ce déploiement (il
  aurait spawné un second paper trading, isolé du volume persistant, à l'intérieur
  du conteneur `monitor`). Le paper trading se pilote **uniquement** via
  `docker compose`.
- **Coût** : un peu de discipline sur les commandes (`--env-file .env.deploy` à
  chaque fois, §2) et sur les 2 secrets à gérer soi-même (mot de passe, TLS).

---

## 1. Prérequis sur le serveur Debian

- Debian 12 (bookworm) ou plus récent, avec un accès `sudo` ou root.
- **Docker Engine + le plugin Compose** (`docker compose`, pas l'ancien `docker-compose`
  en script Python) :
  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER
  # déconnecte-toi / reconnecte-toi (ou `newgrp docker`) pour que le groupe s'applique
  docker compose version   # doit afficher une version 2.x
  ```
- **Un nom de domaine** pointant vers l'IP de ce serveur (recommandé, HTTPS public
  automatique) **OU** juste son **IP publique** (fonctionne aussi, §4 mode B).
- **Pare-feu** : ouvre le port **443** (et **80** uniquement si tu utilises un
  domaine — challenge Let's Encrypt). Ferme tout le reste côté internet (SSH excepté,
  sur un port non standard de préférence).

## 2. Récupérer le projet

```bash
git clone <url-du-repo> insertyourcoin
cd insertyourcoin
```

> À partir d'ici, **toute commande `docker compose` de ce document inclut
> `--env-file .env.deploy`**. C'est nécessaire (§9, gotcha détaillé) : sans ce flag,
> les paramètres du paper (stratégie, stop-loss…) retombent silencieusement sur des
> valeurs par défaut au lieu de lire `.env.deploy` — jamais une erreur bruyante, donc
> facile à ne pas remarquer. Si tu préfères ne jamais taper ce flag, crée-toi un alias :
> `alias dcy='docker compose --env-file .env.deploy'` (puis utilise `dcy up -d` etc.)

## 3. Générer le mot de passe du dashboard

Le hash bcrypt se génère avec l'image Caddy elle-même (aucune dépendance à installer) :

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'TON_MOT_DE_PASSE_FORT'
```

Copie le résultat (commence par `$2a$` ou `$2b$`) — tu en auras besoin à l'étape suivante.

## 4. Configurer `.env.deploy`

```bash
cp .env.deploy.example .env.deploy
```

Édite `.env.deploy` (jamais commité — déjà dans `.gitignore`) :

- **Mode A — tu as un nom de domaine** (ex. `trading.example.com`, DNS déjà pointé
  vers ce serveur) :
  ```ini
  IYC_SITE_ADDRESS=trading.example.com
  IYC_TLS_MODE=toi@example.com
  ```
  Caddy obtient et renouvelle **automatiquement** un certificat Let's Encrypt public
  (nécessite les ports 80 **et** 443 ouverts, et le DNS déjà propagé).

- **Mode B — tu n'as pas de domaine, tu accèdes par IP** :
  ```ini
  IYC_SITE_ADDRESS=:443
  IYC_TLS_MODE=internal
  ```
  Caddy génère un certificat auto-signé (sa propre CA interne) — **fonctionne
  immédiatement**, aucun domaine requis. Ton navigateur affichera un avertissement
  « connexion non privée / certificat non fiable » à accepter une fois (normal :
  c'est un certificat que *toi seul* as émis, pas une autorité publique). Si tu veux
  faire disparaître l'avertissement, tu peux exporter et installer la CA racine de
  Caddy dans ton navigateur (`docker compose exec proxy cat
  /data/caddy/pki/authorities/local/root.crt` — hors scope de ce document, optionnel).

Renseigne aussi :
```ini
IYC_BASIC_AUTH_USER=admin
IYC_BASIC_AUTH_HASH=<le hash bcrypt de l'étape 3>
```

Les paramètres du paper (`PAPER_STRATEGY`, `PAPER_SYMBOL`, `PAPER_TIMEFRAME`,
`PAPER_STOP_LOSS`, `PAPER_TAKE_PROFIT`, `PAPER_TRAILING_STOP`) ont des valeurs par
défaut raisonnables déjà dans le fichier — modifie-les si tu veux tester autre chose
que SMA sur ETH/USD 5m.

## 5. Démarrer

```bash
docker compose --env-file .env.deploy up -d --build
```

Ça construit l'image (une seule image, réutilisée par `paper` et `monitor` — cf.
`Dockerfile`), démarre les 3 conteneurs, et les laisse tourner en arrière-plan.

**Vérifie** :
```bash
docker compose ps                       # les 3 services doivent être "Up" (monitor : "healthy" après ~10-40s)
docker compose logs -f paper             # tu dois voir les cycles du paper trading démarrer
docker compose logs -f proxy             # Caddy doit annoncer avoir obtenu/chargé un certificat
```

Ouvre ensuite `https://trading.example.com` (mode A) ou `https://<IP-du-serveur>`
(mode B) dans ton navigateur — le mot de passe de l'étape 3 t'est demandé (auth HTTP
basic), puis le tableau de bord InsertYourCoin s'affiche.

## 6. Où sont les données, comment les récupérer

Tout ce qu'écrit le paper trading (`paper_state.json`, `paper_stats.csv`,
`paper_trades.log`) vit dans le **volume Docker nommé** `insertyourcoin_iyc_data`
(le préfixe `insertyourcoin_` vient du nom du dossier du projet ; vérifie le nom
exact avec `docker volume ls`). Ce volume **survit** aux redémarrages de conteneur,
aux `docker compose down` (sans `--volumes`), et aux mises à jour d'image.

**Voir ce qu'il contient** (sans rien arrêter) :
```bash
docker compose exec monitor ls -la /data
```

**Copier les fichiers vers l'hôte** (ex. pour les analyser en local avec
`python main.py stats`) :
```bash
docker cp iyc-monitor:/data/paper_stats.csv ./paper_stats.csv
docker cp iyc-monitor:/data/paper_trades.log ./paper_trades.log
docker cp iyc-monitor:/data/paper_state.json ./paper_state.json
```

**Sauvegarder le volume entier** (backup complet, indépendant des conteneurs) :
```bash
docker run --rm \
  -v insertyourcoin_iyc_data:/data:ro \
  -v "$PWD":/backup \
  alpine tar czf /backup/iyc_data_$(date +%Y%m%d).tar.gz -C /data .
```

**Restaurer** (sur ce serveur ou un autre) :
```bash
docker run --rm \
  -v insertyourcoin_iyc_data:/data \
  -v "$PWD":/backup \
  alpine sh -c "cd /data && tar xzf /backup/iyc_data_20260809.tar.gz"
```

## 7. Ce qu'il ne faut PAS faire dans ce déploiement (bloqué par construction)

- **Le bouton « Démarrer le paper » / « Arrêter le paper » de la page web `/paper`
  est désactivé dans ce déploiement — pas seulement déconseillé.** Cette
  fonctionnalité (`trading/monitor.py`, Lot 7) a été conçue pour l'usage
  **mono-machine** de `lancer.py` : utilisée telle quelle en conteneurs, elle
  aurait spawné un *second* process `main.py paper` **à l'intérieur du conteneur
  `monitor`**, écrivant dans `/app/paper_state.json` (répertoire de code, éphémère,
  PAS le volume `/data`) au lieu du volume persistant — deux paper trading
  distincts, deux historiques divergents, et celui de la page web disparaissant au
  premier redémarrage du conteneur.

  **Fermé par construction** (variable d'environnement `IYC_DISABLE_PAPER_CONTROL=1`,
  positionnée sur le service `monitor` dans `docker-compose.yml` **et**
  `docker-compose.eunivers.yml` — pas sur `paper`, qui ne sert pas `/paper`) :
  - **`GET /paper`** reste consultable (statut en lecture seule), mais le formulaire
    Démarrer et le bouton Arrêter sont **retirés du rendu**, remplacés par un encart
    « Pilotage désactivé en déploiement conteneurisé — gère le paper via
    `docker compose ... restart/stop/logs paper` ».
  - **`POST /paper`** (actions `start` **et** `stop`) est **refusé côté serveur**
    (`trading/monitor.py::_paper_post`, vérifié en tout premier, avant toute lecture
    de `action`) : un formulaire forgé ne peut **rien** spawner ni tuer, même avec un
    jeton CSRF valide — le contrôle n'est pas une simple absence de bouton en HTML.
  - `trading/paper_page.py::paper_control_disabled()` (fonction pure) parse le flag :
    absent/vide → `False`, comportement **local (mono-machine) strictement
    inchangé** ; `1`/`true`/`yes` (insensible à la casse) → `True`.
  - Le paper trading de ce déploiement reste **exclusivement** celui du service
    `paper` de `docker-compose.yml`, supervisé par Docker (`restart: unless-stopped`).
    Pilotage : `docker compose restart paper`, `docker compose logs paper`,
    `docker compose stop paper`.
- **Le bouton « Redémarrer le serveur » / « Arrêter le serveur »** (page Options)
  contrôle uniquement le conteneur `monitor` lui-même — celui-ci utilise
  correctement `--host 0.0.0.0` et les chemins `/data/...` même après un clic sur
  « Redémarrer » (corrigé le 2026-08-09, cf. §10) : sûr à utiliser.
- **Ne monte jamais `.env` (clés Kraken) sur le service `paper` ou `monitor`** de ce
  déploiement Phase 1 — il n'y en a pas besoin, et ça ouvrirait une surface inutile.
  Voir §8 pour l'ajouter proprement plus tard.

## 8. Ajouter le live (Lot 8B — superviseur + armement persistant, conteneur)

> **Statut : implémenté, NON ACTIVÉ par défaut.** L'overlay `docker-compose.live.yml`
> n'a **aucun effet** tant qu'il n'est pas explicitement ajouté avec `-f` à la
> commande `docker compose` — voir §5. Ce document décrit la procédure **réelle**
> (superviseur conteneurisé, armement persistant, mur web neutralisé côté
> démarrage) : elle **remplace** l'ancienne esquisse "un service `live --execute`
> qui bloque sur `docker compose run`" — cf.
> `docs/design/LOT8B_LIVE_CONTENEUR_SPEC.md` pour le détail complet des décisions
> et leurs justifications (M19, gate indépendante).

### 8.1 Pourquoi le local (Lot 8, `input()` interactif) ne suffit pas ici

Le live **local** exige de taper `OUI JE CONFIRME` sur un terminal interactif à
**chaque** démarrage (`main.py live --execute`). Sous `restart: unless-stopped`,
ça tombe en trois pièges : le prompt **bloque indéfiniment** sans TTY, l'état de
risque (stop/trailing) ne vivait qu'**en mémoire** (perdu à chaque restart), et le
bouton web `/live` spawnerait un process **dans le conteneur `monitor`**, isolé du
volume — trois hypothèses locales qui tombent toutes en conteneur. Le Lot 8B
répond par **un marqueur d'armement persistant** (confirmé UNE fois, via un
terminal, puis relu par un **superviseur** dédié qui reprend/relance
`main.py live --execute` de lui-même, sans jamais redemander la phrase).

### 8.2 Ce que tu obtiens (compromis chiffré, M20)

- **Obtenu** : reprise automatique après crash/redémarrage du conteneur (Docker
  `restart: unless-stopped` + superviseur qui reconnecte l'état via Kraken) ;
  armement confirmé **une fois**, jamais par accident (le marqueur n'existe QUE si
  un humain a tapé `OUI JE CONFIRME` sur un terminal interactif) ; un seul live à
  la fois **garanti** (même verrou anti-TOCTOU que BUG-015) ; le bouton web
  « Arrêter » du dashboard reste fonctionnel (sentinelle + désarmement) même si le
  démarrage web est neutralisé.
- **Abandonné** : le démarrage/armement depuis la page web `/live` — en conteneur,
  ce canal est **entièrement désactivé** (lecture seule) ; le seul canal
  d'armement est un terminal shell sur l'hôte (`docker compose run --rm live
  live-arm`).
- **Coût** : deux commandes à connaître (`live-arm`/`live-disarm`), un fichier
  `.env` (clés Kraken) à préparer sur l'hôte, une case déjà connue (BUG-015)
  qu'un test de concurrence continue de couvrir.

### 8.3 Préparer les clés (comme le local — jamais commité)

```bash
cp .env.example .env
```

Édite `.env` avec une clé Kraken **sans** la permission *Withdraw Funds* (Query
Funds + Orders seulement). Ce fichier est **différent** de `.env.deploy` (qui
configure Caddy/le paper) — ne les confonds jamais. `.env` est déjà dans
`.gitignore`.

### 8.4 Activer l'overlay (mode dédié) ou (reverse-proxy existant)

```bash
# Mode dédié (docker-compose.yml, Caddy) :
docker compose -f docker-compose.yml -f docker-compose.live.yml \
  --env-file .env.deploy up -d --build

# Reverse-proxy existant (docker-compose.eunivers.yml, SWAG) :
docker compose -f docker-compose.eunivers.yml -f docker-compose.live.yml \
  --env-file .env.deploy up -d --build
```

`docker-compose.live.yml` ajoute le service `live` (superviseur, `command: python
-u /app/main.py live-run`, `.env` monté en **lecture seule**, réseau
`iyc-internal` **seul** — jamais `proxy`, aucun `ports:`) et étend
`environment:` du service `monitor` existant avec `IYC_DISABLE_LIVE_CONTROL=1`
(fusion additive Compose — le `command:` du `monitor` de base n'est **jamais**
redéclaré dans l'overlay, pour ne pas perdre `--stats/--log/--state/--live-root`,
même classe de bug que §11).

À ce stade, le service `live` **tourne mais ne trade rien** : aucun marqueur
d'armement n'existe encore, le superviseur reste `désarmé` (visible sur `/live`,
maintenant en **lecture seule**).

### 8.5 Armer (one-shot, interactif, sur l'hôte)

```bash
docker compose -f docker-compose.yml -f docker-compose.live.yml \
  --env-file .env.deploy run --rm live \
  python /app/main.py live-arm --strategy sma --symbol ETH/USD --timeframe 5m \
  --stop-loss 5 --take-profit 10 --trailing-stop 8
```

(`/app/main.py` en chemin absolu -- `docker compose run` hérite du `working_dir:
/data` du service `live`, où `main.py` n'existe pas ; c'est le code applicatif qui
vit dans `/app`, comme dans le `command:` du service lui-même.)

Récapitulatif affiché (paire, stratégie, plafonds `config.py`), puis exige de
taper exactement `OUI JE CONFIRME`. Une fois confirmé : le marqueur
`/data/live/armed.json` est écrit (**aucune** clé, **aucune** phrase dedans — la
grille est figée, cf. spec §2.2) et la commande **rend la main** (elle ne trade
jamais elle-même). Le superviseur (déjà en cours d'exécution via `restart:
unless-stopped`) lit ce marqueur à son prochain cycle (**~2 s**) et (re)lance
`main.py live --execute` en lui pipant la phrase sur son entrée standard — la 3ᵉ
barrière de Lot 8 (`main.py::cmd_live`, **inchangé**) reste donc intacte, elle
est simplement rejouée automatiquement parce qu'un humain a déjà confirmé une
fois à l'armement.

**Sans TTY, aucun marqueur n'est écrit** (fail-safe volontaire) : lancer cette
commande via un `up -d` détaché, un cron, ou tout contexte sans terminal
interactif échoue proprement sur EOF — impossible d'armer par accident.

**Armer en simulation d'abord** (recommandé, aucune phrase exigée, aucun ordre
possible) :

```bash
docker compose -f docker-compose.yml -f docker-compose.live.yml \
  --env-file .env.deploy run --rm live \
  python /app/main.py live-arm --dry --strategy sma --symbol ETH/USD --timeframe 5m
```

### 8.6 Désarmer / arrêter

Trois façons, du plus doux au plus radical :

1. **Bouton web « Arrêter immédiatement »** (page `/live`, désormais en lecture
   seule mais ce bouton **reste actif**) : écrit un sentinelle d'arrêt +
   désarme ; le superviseur termine l'enfant sous ~2 s, **sans vendre**. Ta
   position ouverte sur Kraken, le cas échéant, **reste** — le bot ne liquide
   jamais (`arrêter n'est pas liquider`).
2. **CLI, depuis l'hôte** :
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.live.yml \
     --env-file .env.deploy run --rm live python /app/main.py live-disarm
   ```
   Même effet que le bouton web : le superviseur termine l'enfant sans vendre au
   prochain cycle.
3. **Kill de dernière instance** (garantie OS, indépendante de l'application) :
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.live.yml \
     --env-file .env.deploy stop live
   ```
   Arrête le conteneur entier (superviseur + enfant). Au redémarrage
   (`start`/`up -d`), le superviseur relit l'état persisté et **reconcilie** avec
   Kraken avant de reprendre (cf. workstream A — `LiveTrader.reconcile()`,
   spec §1.4) — ce n'est **pas** une liquidation, seulement une pause.

### 8.7 Où sont les données live

Sur le volume `iyc_data`, comme le paper :

| Fichier | Contenu |
|---|---|
| `live_state.json` | ancres de risque persistées (`entry_price`, `peak`, `entry_ts`, `entry_cost`, `last_trade_ts`) — **aucune clé, aucun solde** (Kraken reste la vérité pour cash/quantité) |
| `live/armed.json` | marqueur d'armement — **aucune clé, aucune phrase** |
| `live/stop_request` | sentinelle d'arrêt (transitoire) |
| `live/status.json` | statut du superviseur (`en_cours`/`désarmé`/`erreur_cles`/…) — lu par `/live` |
| `live_trades.log`, `live_stats.csv` | journal + stats, identiques au format local |

Le dashboard (`/live` en conteneur) lit tout ceci via `--live-root /data` (déjà
présent sur `monitor` dans `docker-compose.yml`/`docker-compose.eunivers.yml`,
**sans effet** tant que le service `live` n'existe pas).

### 8.8 Ce qui ne bouge PAS (conservation, L3)

- **Sans cet overlay** (`docker-compose.live.yml` non ajouté avec `-f`), rien ne
  change : `--live-root /data` sur `monitor` est un flag mort (aucun
  `live/*`/`live_state.json` n'existe jamais sur le volume), `/live` continue
  d'afficher son mur local habituel.
- **`cmd_live` inchangé** (`main.py::cmd_live`) : les nouveaux chemins (`live-arm`,
  superviseur) l'appellent tel quel, phrase pipée sur stdin.
- **Le flux nonce web local** (Lot 8, `docs/design/LOT8_LIVE_SPEC.md`) reste
  identique quand `IYC_DISABLE_LIVE_CONTROL` est absent — c'est un flag **distinct**
  de `IYC_DISABLE_PAPER_CONTROL`, jamais partagé.
- **Les plafonds** (`MAX_TRADE_VALUE_USD`, `MAX_POSITION_VALUE_USD`,
  `MIN_TRADE_INTERVAL_SEC`) restent dans `config.py`, donc dans l'image — les
  changer exige un rebuild (`--build`), jamais une variable d'environnement
  silencieuse ni un champ du marqueur d'armement.

## 9. Mettre à jour

```bash
git pull
docker compose --env-file .env.deploy up -d --build
```

Rebuild l'image, recrée `paper` et `monitor` avec le nouveau code (le volume `iyc_data`
n'est jamais touché — les données survivent). `proxy` n'a pas besoin de rebuild
(image officielle Caddy, sauf si tu modifies `Caddyfile`, auquel cas `docker compose
--env-file .env.deploy up -d proxy` suffit).

## 10. Sécurité — pourquoi ces couches, ce qu'elles protègent

- **HTTPS + mot de passe obligatoires** : la page `/options` du dashboard permet de
  saisir des clés API Kraken (chiffrées en transit uniquement si HTTPS ; jamais
  affichées ni loguées en clair côté application) — et **n'a elle-même aucune
  authentification applicative**. C'est le reverse proxy qui protège TOUTE la
  surface, uniformément, avant même que l'application ne voie la requête.
- **`monitor` jamais exposé directement** (aucun `ports:` dans son service) : même
  si `proxy` tombe, `monitor` reste injoignable depuis internet — seul le réseau
  Docker interne `iyc-internal` y a accès.
- **Protection anti DNS-rebinding de l'application** (`host_allowed()`,
  `trading/monitor.py`) : elle exige un en-tête `Host: 127.0.0.1:8765` — Caddy la
  satisfait en réécrivant l'en-tête (`header_up Host 127.0.0.1:8765`, cf.
  `Caddyfile`) **au lieu** de modifier ce code applicatif. Choix documenté
  explicitement : ça préserve intacte une protection qui a du sens en dehors de ce
  déploiement (usage local `lancer.py`), plutôt que d'affaiblir le code pour ce seul
  cas d'usage.
- **`--host 0.0.0.0` du service `monitor`** n'expose PAS le dashboard au monde : ce
  bind ne rend le service accessible que *depuis les autres conteneurs du même
  réseau Docker* — il n'existe **aucun** chemin réseau depuis l'hôte ou internet vers
  `monitor:8765` sans passer par `proxy`.
- **Utilisateur non-root** dans le conteneur (`Dockerfile`, uid/gid 1000) : réduit la
  surface en cas de faille dans une dépendance Python.
- **Patch appliqué à `trading/monitor.py`/`main.py`** (2026-08-09, cf. §11) : le
  respawn déclenché par le bouton « Redémarrer le serveur » de la page Options
  oubliait `--host`/`--stats`/`--log`/`--state` — un clic aurait rendu le conteneur
  injoignable depuis `proxy` et fait lire au monitor des chemins hors du volume.
  Corrigé et testé (5 tests ajoutés, 599 tests verts au total).

## 11. Ce qui a été modifié dans le code applicatif (et pourquoi)

Ce déploiement a nécessité **deux patches minimaux, additifs**, sur du code qui ne
prévoyait pas d'usage multi-conteneurs :

1. **`main.py`** : ajout de `--host` à la commande `monitor` (défaut `127.0.0.1`,
   comportement local inchangé). La plomberie existait déjà côté
   `trading/monitor.py` (`run_monitor(host=...)`, bind réel du serveur HTTP) mais
   n'était joignable par aucun argument CLI.
2. **`trading/monitor.py`** (`_restart_server_thread`) : le respawn du bouton
   « Redémarrer le serveur » (page Options) reconstruit désormais sa commande avec
   `--host`/`--stats`/`--log`/`--state`, qu'il oubliait auparavant (bug dormant en
   usage local, où `project_root()` == le répertoire de travail par convention —
   jamais visible avant un déploiement multi-conteneurs, où ces chemins divergent
   réellement).

Aucune autre ligne de `trading/` n'a été touchée. `599 tests passed` après patch
(`.venv\Scripts\python.exe -m pytest -q`), dont 5 nouveaux tests couvrant précisément
ces deux changements (`tests/test_main_monitor_cli.py`,
`tests/test_monitor_server.py::test_route_server_restart_forwards_host_and_data_paths`,
`::test_restart_thread_forwards_data_paths_when_provided`).

## 12. Dépannage rapide

| Symptôme | Piste |
|---|---|
| `docker compose ps` : `monitor` reste `unhealthy` | `docker compose logs monitor` — souvent un chemin `/data/...` inexistant au tout premier démarrage (normal avant le premier cycle du paper : `paper_stats.csv` n'existe pas encore) — attends 1-2 cycles du paper (`--timeframe` minutes) |
| Le navigateur ne se connecte pas du tout | Pare-feu : `sudo ss -tlnp \| grep -E ':443\|:80'` doit montrer `docker-proxy` en écoute ; vérifie aussi que le port est bien ouvert côté hébergeur/routeur (pas seulement `ufw`) |
| Certificat Let's Encrypt jamais obtenu (mode A) | `docker compose logs proxy` ; vérifie DNS (`dig +short trading.example.com` doit renvoyer l'IP du serveur) et que le port **80** est bien ouvert (challenge HTTP-01) |
| 403 « Host non autorisé » en passant par le domaine/IP | Le `header_up Host 127.0.0.1:8765` du `Caddyfile` a disparu ou le port ne correspond plus à `--port` de `monitor` dans `docker-compose.yml` (§ note du `Caddyfile`) |
| Erreur Caddyfile au démarrage (`unrecognized directive`) | La directive `basicauth` peut avoir changé de nom selon la version exacte de `caddy:2-alpine` — vérifie `docs.caddyserver.com/docs/caddyfile/directives/basicauth` pour ta version (non testable depuis cette machine Windows, aucun Docker installé ici — à vérifier au premier `docker compose up` sur le serveur réel) |
| Le paper semble à l'arrêt depuis un moment | `docker compose logs --tail 100 paper` ; le dashboard affiche aussi une alerte « paper inactif » après 360s sans cycle |

---

## 13. Déploiement derrière un reverse-proxy existant (SWAG / serveur mutualisé)

> Contexte cible (fourni par la session infra qui gère ce serveur, pas par ce
> document) : Debian IONOS, ~13 conteneurs derrière **SWAG** (linuxserver, nginx) qui
> détient déjà 80/443 (Let's Encrypt HTTP-01, CrowdSec, fail2ban). Sous-domaine prévu
> **`iyc.eunivers.net`**. 1 utilisateur Linux par stack (`/home/iyc/`) ; le clone du
> projet et la configuration SWAG (bloc `server{}` nginx, DNS) sont faits par la
> **session infra**, pas par les commandes de cette section.

### 13.1 Ce qui change vs le mode dédié (§0-§12)

| | Mode dédié (`docker-compose.yml`) | Mode reverse-proxy existant (`docker-compose.eunivers.yml`) |
|---|---|---|
| Service `proxy` (Caddy) | présent, seul à publier 80/443 | **absent** — SWAG publie déjà 80/443 pour toute la machine |
| TLS, Basic Auth, anti-indexation | gérés par Caddy (`Caddyfile`, `.env.deploy`) | **gérés par SWAG**, hors de ce dépôt — rien à recréer côté app/compose |
| Réseau vers `monitor` | `iyc-internal` uniquement (Caddy y a accès) | `iyc-internal` **+** réseau Docker **externe `proxy`**, partagé avec SWAG |
| Comment `monitor` est trouvé | Caddy relaie par nom de service interne | **SWAG résout par `container_name`** (`iyc-monitor`, port 8765) |
| Protection Host (anti DNS-rebinding) | Caddy réécrit l'en-tête Host (`header_up Host 127.0.0.1:8765`) | **impossible** : réécrire le Host côté nginx est interdit sur ce serveur (double `proxy_set_header Host` → incident nginx déjà vécu) → **allowlist côté app** (`IYC_ALLOWED_HOSTS`, §13.3) |
| Secrets `.env.deploy` (TLS, mot de passe) | requis (§3-4) | **non utilisés par cette variante** — l'auth et le TLS sont réglés dans SWAG |

**Le compromis assumé (M20)** — obtenu / abandonné / coût :
- **Obtenu** : zéro double couche TLS/auth à maintenir en synchro avec les ~12 autres
  stacks du serveur ; le service `paper` reste identique bit pour bit au mode dédié.
- **Abandonné** : la protection Host « exige exactement `127.0.0.1`/`localhost` »
  n'est plus universelle — un hôte configuré (`iyc.eunivers.net`) est explicitement
  ajouté à l'allowlist (§13.3, périmètre documenté).
- **Coût** : une variable/un flag à tenir cohérent entre `docker-compose.eunivers.yml`
  (défaut `iyc.eunivers.net`) et la conf SWAG (côté session infra) — s'ils divergent,
  symptôme direct : 403 « Host non autorisé » (§12, tableau de dépannage).

### 13.2 Démarrer

Sur le serveur (le clone et le `.env.deploy` sont préparés par la session infra, ou
suis §2-§4 en adaptant : pas besoin de `IYC_SITE_ADDRESS`/`IYC_TLS_MODE`/
`IYC_BASIC_AUTH_*`, propres au mode dédié Caddy) :

```bash
docker compose -f docker-compose.eunivers.yml --env-file .env.deploy up -d --build
```

**Prérequis qui doit déjà exister** (créé par la session infra, `docker network
create proxy` ou équivalent lors de l'installation de SWAG) : le réseau Docker
externe `proxy`. S'il n'existe pas, `docker compose up` **échoue avec un message
clair** plutôt que de créer silencieusement un second réseau `proxy` que SWAG ne
verra jamais (`networks: proxy: external: true` dans le compose — vérifie
`docker network ls | grep proxy` avant si le message n'est pas explicite).

**Ce que la session infra fait ensuite** (hors de ce document) : ajouter un bloc SWAG
qui route `iyc.eunivers.net` vers `iyc-monitor:8765`, avec Basic Auth + TLS + règle
anti-indexation ; pointer le DNS de `iyc.eunivers.net` vers ce serveur.

> ⚠️ **Gotcha DNS/ACME — vérifié en production (2026-08-09).** Avant d'ajouter le
> sous-domaine à SWAG (`SUBDOMAINS`), **s'assurer qu'aucun enregistrement AAAA
> (IPv6) « parking » ne traîne** sur le nouveau sous-domaine. Vécu réel : IONOS
> servait un AAAA de parking sur `iyc.eunivers.net` au moment de la validation
> Let's Encrypt → ACME préfère l'IPv6 → challenge routé vers le parking IONOS →
> `Invalid response … 204`, et SWAG a **révoqué le certificat AVANT de re-valider**
> → panne cert **totale pour TOUS les sous-domaines** (~15 min). Préconditions :
> vérifier la zone autoritaire (`dig AAAA iyc.eunivers.net` doit être vide, ou
> pointer le vrai serveur) **avant** de toucher `SUBDOMAINS`, et **vérifier le
> certificat réellement servi après émission** (nginx peut garder en mémoire le
> placeholder auto-signé → `reload`). Incident 100 % côté infra/DNS, **sans rapport
> avec le code** — noté ici car il conditionne un déploiement SWAG réussi.

### 13.3 Le point Host — pourquoi une allowlist côté app plutôt qu'une réécriture nginx

`host_allowed()` (`trading/monitor.py`) n'acceptait, avant ce patch, que
`127.0.0.1`/`localhost`. En mode dédié, Caddy contourne ça en réécrivant l'en-tête
Host avant de relayer. **Sur ce serveur, réécrire le Host côté SWAG (nginx) est
interdit** — un second `proxy_set_header Host` en plus de celui déjà posé par SWAG
pour les ~12 autres stacks a déjà provoqué un `nginx: emerg` (conflit de directive).

Solution retenue : une **allowlist configurable côté application, défaut
strictement inchangé** :

- `host_allowed(host_header, port, extra_hosts=())` — `extra_hosts` vide (défaut) =
  comportement identique à avant ce patch. Testé dans `tests/test_allowed_hosts.py`
  et `tests/test_options.py::test_host_allowed_*` (non-régression).
- Source de config, les deux se cumulent : variable d'env **`IYC_ALLOWED_HOSTS`**
  (liste séparée par virgules) **et** flag CLI **`--allowed-host`** (répétable) sur
  `main.py monitor`. `docker-compose.eunivers.yml` positionne
  `IYC_ALLOWED_HOSTS=${IYC_ALLOWED_HOSTS:-iyc.eunivers.net}` sur le service `monitor`.
- Re-forwardé au **respawn** déclenché par le bouton « Redémarrer le serveur »
  (page Options) — même classe de bug que celle déjà corrigée le même jour pour
  `--host`/`--stats`/`--log`/`--state` (§11) : sans ce re-forward, un clic aurait
  fait perdre l'allowlist jusqu'au prochain redémarrage manuel du conteneur.

**Sécurité, explicitement** : ajouter un hôte à l'allowlist assouplit l'anti
DNS-rebinding **pour cet hôte précis seulement** (127.0.0.1/localhost restent
acceptés en plus, jamais remplacés). Acceptable dans ce déploiement parce que
`monitor` n'est joignable **que** via le réseau Docker `proxy` (aucun `ports:` publié
par ce conteneur, comme en mode dédié) **et** que SWAG impose Basic Auth + TLS avant
que la requête n'atteigne l'application — les deux couches qui protègent réellement
restent intactes ; l'allowlist ne fait que permettre à une requête déjà filtrée par
SWAG de passer le contrôle applicatif interne.

### 13.4 Fichiers de cette variante

| Fichier | Rôle |
|---|---|
| `docker-compose.eunivers.yml` | variante sans `proxy` (Caddy), réseau externe `proxy`, `IYC_ALLOWED_HOSTS` |
| `.env.deploy.example` | section dédiée « reverse-proxy existant » (`IYC_ALLOWED_HOSTS`), sans effet en mode dédié |
| `trading/monitor.py`, `main.py` | `host_allowed(..., extra_hosts=...)`, `build_monitor_server(..., allowed_hosts=...)`, `--allowed-host` CLI, re-forward au respawn |

Le mode dédié (`docker-compose.yml`, `Caddyfile`) **n'est pas modifié** par cette
variante — les deux compose files coexistent, tu choisis celui qui correspond à ton
serveur avec `-f`.

---

## Annexe — ce qui a été VÉRIFIÉ vs ce qui reste À VÉRIFIER sur la cible

**Vérifié sur cette machine (Windows, pas de Docker installé)** :
- Les 3 fichiers écrits par le paper trading, leurs chemins par défaut (relatifs au
  répertoire de lancement) et les 3 chemins explicites acceptés par `monitor`
  (lus directement dans `trading/paper_trader.py` et `trading/monitor.py`).
- `host_allowed()` et le bind réel du serveur (`ThreadingHTTPServer((host, port), ...)`)
  — lu dans le code, confirme que `--host 0.0.0.0` fonctionne comme attendu.
- Le patch `--host` + le forwarding `_restart_server_thread` : **599/599 tests
  pytest verts**, y compris 5 tests nouveaux ciblant exactement ces deux changements.
- La logique de `assert_paper_only` (`lancer.py`) : confirme qu'aucune commande
  construite par le code existant ne peut contenir `"live"`.

**Non vérifiable depuis cette machine (aucun Docker installé — confirmé : `docker`
n'est pas dans le PATH) — à valider sur le serveur Debian réel, dans cet ordre** :
- `docker compose --env-file .env.deploy config` (valide la syntaxe YAML + les
  interpolations `${...}`) — **à lancer avant tout autre chose**.
- `docker compose --env-file .env.deploy build` (le `Dockerfile` compile bien,
  `python:3.14-slim` est disponible, `pip install -r requirements.txt` réussit).
- Le mécanisme d'initialisation du volume nommé (`iyc_data` hérite bien de
  l'ownership `iyc:iyc` défini dans le `Dockerfile`) — comportement Docker
  documenté et standard, mais jamais exécuté ici faute de daemon Docker.
- La syntaxe exacte de la directive `basicauth` sur `caddy:2-alpine` (cf. tableau de
  dépannage ci-dessus) et l'obtention effective d'un certificat Let's Encrypt (mode A)
  ou auto-signé (mode B).

### Annexe bis — variante §13 (`docker-compose.eunivers.yml`, reverse-proxy existant)

**Vérifié sur cette machine (lecture de code + tests, pas d'exécution Docker)** :
- `host_allowed(host_header, port, extra_hosts=())` : défaut vide → comportement
  identique à avant ce patch (`tests/test_options.py::test_host_allowed_*`, verts,
  non-régression) ; hôte configuré accepté/rejeté correctement, avec/sans port,
  insensible à la casse (`tests/test_allowed_hosts.py`).
- `build_monitor_server(..., allowed_hosts=...)`, `run_monitor(..., allowed_hosts=...)`
  et le Handler (`_host_ok`) transmettent bien `allowed_hosts` à `host_allowed()`.
- `--allowed-host` (répétable) + `IYC_ALLOWED_HOSTS` (CSV) fusionnent sans se
  remplacer (`main._resolve_allowed_hosts`), défaut = tuple vide sans configuration.
- `_restart_server_thread` re-forwarde `--allowed-host` au respawn (même correctif
  que `--host`/`--stats`/`--log`/`--state` du §11, appliqué à ce nouveau paramètre
  dès son introduction — pas après coup) : couvert par 3 tests dans
  `tests/test_monitor_server.py` (unit + intégration HTTP réelle sur `/server/restart`).
- `docker-compose.eunivers.yml` : validé **structurellement** via PyYAML (installé
  temporairement pour l'audit puis désinstallé, pas une dépendance du projet) —
  2 services (`paper`, `monitor`), ni l'un ni l'autre ne publie `ports:`, `monitor`
  est sur les deux réseaux `iyc-internal`+`proxy`, `proxy` est bien `external: true`,
  aucun service `proxy`/Caddy présent, `container_name: iyc-monitor` confirmé.
- **599 → 616 tests pytest verts** (`.venv\Scripts\python.exe -m pytest -q`), dont
  17 nouveaux ciblant précisément cette variante (`tests/test_allowed_hosts.py` +
  3 tests ajoutés à `tests/test_monitor_server.py` + 1 test CLI ajusté dans
  `tests/test_main_monitor_cli.py`).

**Non vérifiable depuis cette machine — à valider sur le serveur Debian réel** :
- Que le réseau Docker externe **`proxy` existe déjà** avant le premier
  `docker compose -f docker-compose.eunivers.yml up` (créé par la session infra qui
  installe SWAG) — sans lui, `docker compose up` doit échouer avec un message
  explicite (`external: true`) plutôt que créer un second réseau invisible pour SWAG ;
  comportement documenté de Compose, jamais exécuté ici faute de daemon Docker.
- Que **SWAG résout effectivement `iyc-monitor` par son `container_name`** une fois
  les deux stacks sur le même réseau `proxy` (résolution DNS Docker interne,
  standard, mais dépend de la conf SWAG réelle — hors de ce dépôt, faite par la
  session infra).
- Que la Basic Auth + l'anti-indexation + le TLS **configurés dans SWAG** (pas dans
  ce dépôt) protègent bien `iyc.eunivers.net` avant que la requête n'atteigne
  `monitor` — à vérifier par un accès direct au sous-domaine une fois la conf SWAG
  posée.
- Qu'un hôte non listé dans `IYC_ALLOWED_HOSTS` retourne bien 403 en conditions
  réelles derrière SWAG (le comportement de `host_allowed()` est testé en local,
  mais pas le chemin réseau complet SWAG → conteneur).
- La syntaxe healthcheck (`test: ["CMD", "python", "-c", ...]`) est identique au
  mode dédié déjà documenté ci-dessus comme À VÉRIFIER — aucune différence
  introduite par cette variante sur ce point.
