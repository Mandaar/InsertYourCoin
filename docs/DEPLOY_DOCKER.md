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

**Le compromis assumé (M20)** — ce qu'on obtient / ce qu'on abandonne / ce que ça
coûte :
- **Obtenu** : accès web HTTPS authentifié depuis n'importe où, données qui survivent
  aux redémarrages/mises à jour, paper trading supervisé automatiquement par Docker
  (`restart: unless-stopped`), zéro clé API exposée.
- **Abandonné (documenté §7)** : le bouton **« Démarrer/Arrêter le paper »** de la
  page web `/paper` ne doit **pas** être utilisé dans ce déploiement (il spawnerait un
  second paper trading, isolé du volume persistant, à l'intérieur du conteneur
  `monitor`). Le paper trading se pilote **uniquement** via `docker compose`.
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

## 7. Ce qu'il ne faut PAS faire dans ce déploiement

- **Ne clique pas sur « Démarrer le paper » / « Arrêter le paper » depuis la page web
  `/paper`.** Cette fonctionnalité (`trading/monitor.py`, Lot 7) a été conçue pour
  l'usage **mono-machine** de `lancer.py` : elle spawnerait un *second* process
  `main.py paper` **à l'intérieur du conteneur `monitor`**, écrivant dans
  `/app/paper_state.json` (répertoire de code, éphémère, PAS le volume `/data`) au
  lieu du volume persistant — deux paper trading distincts, deux historiques
  divergents, et celui de la page web disparaît au premier redémarrage du conteneur.
  Le paper trading de ce déploiement est **exclusivement** celui du service
  `paper` de `docker-compose.yml`, supervisé par Docker (`restart: unless-stopped`).
  Pilotage : `docker compose restart paper`, `docker compose logs paper`,
  `docker compose stop paper` — jamais le bouton web.
- **Le bouton « Redémarrer le serveur » / « Arrêter le serveur »** (page Options)
  contrôle uniquement le conteneur `monitor` lui-même — celui-ci utilise
  correctement `--host 0.0.0.0` et les chemins `/data/...` même après un clic sur
  « Redémarrer » (corrigé le 2026-08-09, cf. §10) : sûr à utiliser.
- **Ne monte jamais `.env` (clés Kraken) sur le service `paper` ou `monitor`** de ce
  déploiement Phase 1 — il n'y en a pas besoin, et ça ouvrirait une surface inutile.
  Voir §8 pour l'ajouter proprement plus tard.

## 8. Ajouter le live plus tard (PAS activé aujourd'hui)

Le jour où tu voudras passer une partie en trading réel (petits montants, garde-fous
serrés `config.py` — cf. `CLAUDE.md` du projet), voici le chemin, **sans rien
changer aujourd'hui** :

1. Crée un fichier `.env` (les clés Kraken — **jamais** le même fichier que
   `.env.deploy`) à partir de `.env.example`, avec une clé Kraken **sans** la
   permission *Withdraw Funds*.
2. Ajoute un **nouveau service** `live` dans `docker-compose.yml` (copie du service
   `paper`, en changeant `paper` en `live --execute` dans la commande) qui monte ce
   `.env` **en lecture seule** : `- ./.env:/app/.env:ro`. Ne l'ajoute **jamais** au
   service `paper` existant — la séparation est volontaire (Loi 3 / conservation :
   le paper reste 100% sûr par construction, indépendamment du reste).
3. La friction applicative reste intacte et n'est PAS contournable depuis ce
   déploiement : `main.py live --execute` exige de taper `OUI JE CONFIRME` sur un
   **terminal interactif** — donc démarrer ce service en `docker compose up -d`
   (détaché, sans TTY) **bloquera indéfiniment sur ce prompt**, ce qui est en
   pratique un garde-fou de plus, pas un bug : il faudra lancer ce service au
   premier plan (`docker compose run --rm live`) au moins une fois pour confirmer,
   ou accepter de retravailler ce point avec un `qa-tester`/`release-engineer` avant
   d'automatiser le live (hors scope de cette mission, volontairement).
4. Les plafonds (`MAX_TRADE_VALUE_USD`, `MAX_POSITION_VALUE_USD`,
   `MIN_TRADE_INTERVAL_SEC`) restent dans `config.py`, donc dans l'image — les
   changer exige un rebuild (`--build`), jamais une variable d'environnement
   silencieuse.

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
