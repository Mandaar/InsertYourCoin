# Rapport de session — App web locale (reprise)

> Session du 2026-06-18. But du document : permettre de **reprendre le chantier
> « app web locale »** sans rien re-dériver. À lire en premier la prochaine fois.

---

## 1. Ce qui a été décidé

Transformer InsertYourCoin (CLI Python) en **site auto-hébergé, lancé et utilisé
sur la machine** (« double-clic, ça démarre tout »). Décisions actées par l'utilisateur :

- **Livraison = web local AV-proof.** Serveur `http.server` (stdlib, déjà utilisé par
  `trading/monitor.py`), lancé par `lancer.bat`/`.sh`, ouvre le navigateur sur `127.0.0.1`.
  **PAS de .exe** (PyInstaller rejeté dans `SETUP.md` : faux positifs antivirus).
- **Périmètre = app complète** : toutes les fonctions CLI deviennent des écrans web.
- **Méthode = spec d'abord, puis maquettes** (validées) **avant** tout code.
- « Mini exécutable » demandé = en réalité l'app web double-cliquable, pas un binaire.

## 2. Ce qui est livré (conception terminée)

| Artefact | Chemin | Statut |
|---|---|---|
| Spec UI/UX (13 écrans, sitemap, sécurité, roadmap) | `docs/UI_UX_WEBAPP_SPEC.md` | **VALIDÉE** |
| Maquette HTML autonome des 13 écrans | `docs/mockups/prototype.html` | vérifiée |
| Icône bureau | `assets/insertyourcoin.ico` (16/32/48/256) | posée sur le bureau |
| Installeur / désinstalleur raccourci | `installer_raccourci.bat`, `desinstaller_raccourci.bat`, `scripts/install_shortcut.ps1` | testés |

**Raccourci bureau** : `InsertYourCoin.lnk` créé sur le bureau → cible `lancer.bat`,
répertoire de travail = racine projet, icône liée. Aujourd'hui le double-clic lance
**paper + monitoring** (l'existant) ; quand l'app complète sera implémentée, la **même
icône** la lancera sans rien changer.

## 3. Les 3 décisions de design (actées, cf. spec §11)

1. **Accueil sur `/`** ; le monitoring passe sur `/monitoring` (redirection douce depuis `/`).
2. **Vendoring offline** de Chart.js + polices (corrige la dette CDN de `dashboard.py`).
3. **Bouton « Tester la liaison Kraken »** dans Options : appel `Query Funds` en lecture
   seule, OK/échec, **solde masqué par défaut**.

## 4. Roadmap d'implémentation (cf. spec §9) — EN COURS (Lots 0-5 faits)

Par lots, chacun sous **gate SQA** (pytest vert, pas de P0/P1, garde-fous live intacts,
`VERIFY_SSL=True`, non-régression), délégué au `ui-programmer`, vérifié en runtime réel :

- ✅ **Lot 0 — Socle** : thème CSS partagé + nav commune + vendoring Chart.js offline. `c5875b4`
- ✅ **Lot 1 — Accueil + Diagnostic** (`/check`), bascule `/` → Accueil, monitoring → `/monitoring`. `d4439de`
- ✅ **Lot 2 — Labo de stats** (`/stats`, lecture seule, source CSV en liste blanche). `e9d1d15`
- ✅ **Lot 3 — Infra jobs async** (`trading/jobs.py` `JobManager` mono-job thread-safe). `af75d34`
- ✅ **Lot 4 — Backtest + Rapport inline** (`/research/backtest` → job → `/report/<id>`, badge IN-SAMPLE). `611d424`
- ✅ **Lot 5 — Comparer + Optimiser + Portefeuille** (routage résultat généralisé par `kind`). `904adc5`
- 🟠 **Lot 6 — Walk-forward** (LE JUGE) : **code complet + 472 tests verts, mais GATE SQA NON PASSÉE**.
  Committé pour ne pas perdre le travail, **PAS considéré comme livré** : 2 findings d'honnêteté confirmés
  restent **ouverts** (**BUG-010 P1** mono-actif vert-au-lieu-de-sévère, **BUG-011 P2** holdout en échec
  qui ne qualifie pas le bandeau) — cf. `docs/SQA.md`. La phase de correction du workflow est morte sur
  un **budget mensuel épuisé**, et la réfutation n'a tourné que sur 1 lentille /4 (sémantique, sécurité
  et non-régression **non réfutées** → 12 findings non tranchés). **À FAIRE AVANT de déclarer le Lot 6 livré** :
  corriger BUG-010/011 (+ tests), rejouer la revue sur les 3 lentilles manquantes, et une vérification
  runtime réelle (3 verdicts + friction `--final`) que je n'ai pas pu faire.
- ⬜ **Lot 7 — Paper pilotable** depuis l'UI (remplace les constantes en tête de `lancer.py`).
- ⬜ **Lot 8 — Live verrouillé** (`/live`, **P0** — argent réel, exige un feu vert user explicite avant de le lancer).
- ⬜ **Lot 9 — Polish & accessibilité**.

**Point d'entrée pour reprendre : Lot 6 (walk-forward).**

Architecture web en place (repères pour la reprise) :
- `trading/webui.py` — `page_shell`, `job_panel_html`, `NAV_ITEMS`/`ENABLED_SCREENS`, `serve_static`, sous-nav recherche.
- `trading/jobs.py` — `JobManager` (attaché au serveur via `server.job_manager`), contrat `submit/status/cancel/result`, `JobBusy`.
- `trading/research_runners.py` — `run_backtest/compare/optimize/portfolio(params, progress)`, payload `{kind, ...}`, loader `_load_ohlcv` monkeypatchable (tests sans réseau).
- `trading/*_page.py` — pages pures (form + rendu) ; `report_page.render_result_done(result)` dispatch par `kind`.
- `trading/monitor.py` — serveur `http.server`, routes, CSRF, `host_allowed`, `/static/`, `/research/*`, `/report/<id>`, `/job/<id>/status|cancel`.
- Le **Lot 6** ajoutera `run_walkforward` + `walkforward_page` + le rendu verdict, en réutilisant `optimizer.walk_forward*`, `holdout_*`. `--final` (holdout) doit rester derrière une friction et une décision user explicite.

## 5. Garde-fous à NE JAMAIS relâcher dans l'UI

- `config.VERIFY_SSL = True` toujours ; **aucune option UI** pour désactiver SSL.
- Clés Kraken : `.env` seul, **jamais affichées** (booléen OUI/NON), jamais loguées ;
  clé sans **Withdraw Funds** ; clés session = mémoire seule si « .env » décoché.
- Page Options : CSRF, bind `127.0.0.1`, anti-DNS-rebinding (déjà en place).
- Wallet = **lien** vers la page de retrait Kraken officielle, rien de stocké, aucun retrait auto.
- **Live** hors nav principale, dry-run par défaut, friction multi-étapes + phrase exacte
  `OUI JE CONFIRME`, plafonds `config.py` affichés et appliqués.
- **Honnêteté** : walk-forward = le juge (hiérarchie typographique), badge in-sample,
  Buy & Hold visible, frais/drawdown jamais masqués. Ne jamais survendre.

## 6. Gotchas rencontrés cette session (à connaître)

- **Outil preview `screenshot` cassé** dans la session (timeout systématique ; la page se
  rend pourtant parfaitement). Contournement : vérifier par **inspection DOM** (`preview_eval`)
  comparée au thème de référence — c'est la méthode préférée de toute façon.
- **Maquette initialement sans accents** (sur-application de la règle « ASCII pur » qui ne
  vaut que pour les `.ps1`) → corrigé. **Rappel : le HTML est en UTF-8, accents obligatoires** ;
  seuls les `.ps1` sont en ASCII pur.
- **Process long-vivants** : ne jamais lancer `lancer.bat` depuis une commande de session
  pour « tester » (gotcha job-object : le process meurt avec la commande). L'icône, elle,
  lance un vrai process qui survit. Cf. mémoire `gotcha-process-longvifs-job-object`.

## 7. État au moment de l'arrêt

- **416 tests pytest verts**. Aucun secret commité (`.env` absent ; `*_stats.csv`,
  `options.json`, `paper_state.json`, `data/`, `run/`, `logs/`, `.venv/`, `.claude/launch.json`
  gitignorés). `VERIFY_SSL=True`.
- **Lots 0-5 committés et poussés** sur `main` (commits ci-dessus, §4).
- L'app web double-cliquable (icône bureau → `lancer.bat` → serveur monitor) sert déjà
  **tous les écrans livrés** : Accueil, Diagnostic, Monitoring, Stats, Options, et les 4
  analyses de recherche (Backtest, Comparer, Optimiser, Portefeuille).
- **Backup** : snapshot du projet sur `E:\Backups\InsertYourCoin\` (voir dossier daté le plus récent).
- `.claude/launch.json` (gitignoré) contient les configs `monitor` (port 8765) et `maquette`
  (port 8770 → `docs/mockups/prototype.html`).

## 8. Reprise — checklist rapide

1. `git pull` puis `git status` propre.
2. `.venv\Scripts\python.exe -m pytest -q` → doit être vert (416+).
3. Double-clic icône bureau (ou `python main.py monitor`) → vérifier les écrans livrés.
4. Attaquer le **Lot 6 (walk-forward)** — voir §4 (repères archi) et la spec §4.6.
