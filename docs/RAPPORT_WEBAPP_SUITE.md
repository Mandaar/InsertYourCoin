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

## 4. Roadmap d'implémentation (cf. spec §9) — NON COMMENCÉE

À faire par lots, chacun sous **gate SQA** (pytest vert, pas de P0/P1, garde-fous live
intacts, `VERIFY_SSL=True`, test de non-régression par bug), délégué au `ui-programmer` :

- **Lot 0 — Socle** : thème CSS partagé + coquille de nav commune + vendoring offline +
  bascule Accueil sur `/` (redirection monitoring). Zéro régression métier.
- **Lot 1** — Accueil + Diagnostic (`/check`).
- **Lot 2** — Labo de stats web (`/stats`).
- **Lot 3** — Infrastructure de jobs async (worker mono-job + polling).
- **Lot 4** — Backtest + Rapport inline (réemploi `dashboard.py` vendorisé).
- **Lot 5** — Comparer + Optimiser + Portefeuille.
- **Lot 6** — Walk-forward (LE JUGE, écran le plus soigné).
- **Lot 7** — Paper pilotable depuis l'UI (remplace les constantes en tête de `lancer.py`).
- **Lot 8** — Live verrouillé (`/live`, P0 par nature, revue renforcée).
- **Lot 9** — Polish & accessibilité.

**Point d'entrée conseillé pour reprendre : Lot 0.**

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

- 253 tests pytest **verts**. Aucun secret commité (`.env`, `*_stats.csv`, `options.json`,
  `paper_state.json` gitignorés). `VERIFY_SSL=True`.
- Tout le travail de cette session est **committé** sur `main`.
- `.claude/launch.json` (gitignoré) contient une config `maquette` (serveur statique port 8770)
  pour rouvrir la maquette : `http://127.0.0.1:8770/docs/mockups/prototype.html`.
