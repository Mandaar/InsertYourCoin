# Revue formelle READ-ONLY — Lot 6 (écran Walk-forward)

> Portée : `trading/walkforward_page.py`, `trading/research_runners.py::run_walkforward`,
> câblage `trading/monitor.py` (routes `/research/walkforward`), dispatch
> `trading/report_page.py`, `tests/test_walkforward_page.py` + `tests/test_research_runners.py`
> (tests runner walk-forward) + `tests/test_monitor_server.py` (intégration HTTP réelle).
> Référence de vérité : `trading/optimizer.py` (`walk_forward`, `walk_forward_multi`,
> `holdout_split`, `holdout_check`, `_verdict`, `WARMUP`, `MIN_TRADES`) et `main.py::cmd_walkforward`.
> Méthode : lecture ligne à ligne, comparaison croisée code web vs code CLI/optimizer,
> exécution de la suite complète (gate d'entrée). Aucun fichier modifié.
> Contexte : la lentille « honnêteté » a déjà été jouée (BUG-010 P1, BUG-011 P2, tous deux
> **Vérifiés/Fermés** au registre `docs/SQA.md`). Cette revue couvre les 3 lentilles restantes.

## Gate d'entrée — MESURÉ

```
.venv\Scripts\python.exe -m pytest -q
554 passed in 43.42s
```
554/554 verts, 0 échec (le test flaky connu BUG-012 `test_route_static_sert_chart_js_vendorise`
ne s'est pas manifesté sur ce run — comportement intermittent documenté, non bloquant).

---

## FAIL — aucun

Aucun défaut fonctionnel, de sécurité ou de non-régression trouvé dans le périmètre du Lot 6.

---

## MARGINAL — 1 point

### Lentille 1(g) — messages de garde serveur : LOGIQUE identique, TEXTE non-identique à la CLI

**MESURÉ.** La CONDITION de garde (bornes numériques, déclenchement) est strictement identique
entre CLI et web — vérifié par lecture directe et par les tests de garde (95% rejeté, holdout=0+final
rejeté, holdout=20+final accepté, aux deux niveaux : `parse_walkforward_params` ET route HTTP réelle).
Mais le **texte** du message diffère :

| | CLI (`main.py:182,184`, MESURÉ via lecture directe des octets du fichier) | Web (`trading/walkforward_page.py:205,210`) |
|---|---|---|
| Holdout hors bornes | `"--holdout : pourcentage attendu dans [0, 90[."` | `"Holdout : pourcentage attendu dans [0, 90[."` |
| `final` sans holdout | `"--final exige --holdout > 0 (sans holdout, pas de segment sacre)."` | `"Validation finale : exige un holdout > 0 (sans holdout, pas de segment sacré)."` |

Écart : préfixe (`--holdout`/`--final`, syntaxe CLI) vs libellé de champ web (`Holdout`/
`Validation finale`), et présence d'accents côté web (absents côté CLI, historique probable :
`main.py` a longtemps évité les caractères non-ASCII pour la console Windows cp1252, cf.
BUG-004 au registre — le web n'a pas cette contrainte, il émet du HTML UTF-8).

**Pourquoi MARGINAL et pas FAIL** : c'est une adaptation d'UX défendable (un utilisateur web
ne doit pas voir `--holdout`, un nom de flag CLI, dans un formulaire HTML) et la **logique de
garde est prouvée identique** par les tests de boundary (`tests/test_walkforward_page.py:154-184`,
`tests/test_monitor_server.py:714-739`). Ce n'est donc pas un défaut fonctionnel.

**Ce qui EST un vrai défaut, mineur (P3)** : le nom des tests et le docstring du module
sur-vendent la parité. `walkforward_page.py:150-152` dit *« Reprend les gardes EXACTES de la
CLI »* et le test s'appelle `test_parse_walkforward_params_holdout_out_of_range_is_error_exact_cli_message`
(`tests/test_walkforward_page.py:154`) — « exact_cli_message » alors que le message n'est PAS
byte-identique au message CLI, seule la RÈGLE l'est. Un lecteur pressé du nom de test croira à
une parité textuelle qui n'existe pas.

**Sévérité** : P3 (cosmétique / clarté de la documentation-test). Aucun scénario d'échec
utilisateur : le message web reste correct et actionnable pour un utilisateur web.
**Correctif suggéré (non appliqué, hors périmètre read-only)** : renommer le test en
`..._same_bound_as_cli` ou ajouter un commentaire précisant « règle identique, texte adapté au
web », pour ne pas induire en erreur une future revue.

---

## Observation non notée (hors format PASS/FAIL) — couverture de test incomplète sur un cas limite

**MESURÉ** : `_worst_holdout_verdict` (`trading/walkforward_page.py:442-456`) n'agrège que les
symboles dont la validation finale a **réussi** (`holdout_results`, pas `holdout_errors`). Si,
en multi-actifs, un symbole réussit son holdout (vert) et un autre échoue techniquement
(`holdout_errors`, ex. « Holdout trop court »), le bandeau global reste basé sur le pire des
holdouts **réussis** et ne reflète pas qu'un symbole n'a **jamais pu être validé**. L'échec est
bien affiché ailleurs sur la page (carte rouge dédiée, `_holdout_block` ligne 626-630,
`.result-error`), donc l'information n'est pas cachée — mais **aucun test ne vérifie le rendu du
bandeau dans ce scénario précis** (recherché : `grep holdout_errors` dans
`tests/test_walkforward_page.py` → seule occurrence : le test qui vérifie que la carte d'erreur
s'affiche, `test_render_walkforward_done_shows_holdout_error_per_symbol`, ligne 369 — aucun test
sur l'état du bandeau dans ce cas). Non classé en FAIL/MARGINAL car (a) l'info reste visible sur
la page, (b) le CLI n'a lui-même aucun concept de « bandeau agrégé » à comparer (il imprime
chaque symbole séquentiellement), donc il n'y a pas de référence de parité à violer. Signalé pour
traçabilité (V16 : dire ce qui n'a pas été testé) — candidat à un test complémentaire, pas un bug.

---

## PASS — détail par lentille

### Lentille 1 — Sémantique walk-forward (LE JUGE)

- **(a) Pas de fuite train→test — PASS, MESURÉ.**
  `walk_forward` (`optimizer.py:185-199`) sélectionne les paramètres sur `train = df.iloc[:test_start]`
  (uniquement le passé), jamais sur la fenêtre OOS courante ni les suivantes. Le runner web
  (`research_runners.py:433`) appelle `walk_forward_multi` sans aucune ré-implémentation — aucun
  code Lot 6 ne touche à la sélection de paramètres. Test comportemental dédié :
  `tests/test_research_runners.py::test_run_walkforward_removes_holdout_before_research` (ligne
  406-418) mesure la date de fin de la dernière fenêtre OOS et vérifie `last_window_end <= df.index[cut-1]`
  — preuve empirique, pas une assertion de structure.

- **(b) Warm-up préservé (WARMUP amont, rebase) — PASS, MESURÉ.**
  `WARMUP = 250` (`optimizer.py:38`) et le rebase equity (`Backtester.run(..., warmup=...)`) sont
  internes à `optimizer.walk_forward` (lignes 195-199) — le web ne les ré-implémente pas :
  `research_runners.py::run_walkforward` construit `wf_kwargs` (lignes 422-428) avec les mêmes
  noms de paramètres que la signature de `walk_forward` (`n_windows`, `train_frac`, `metric`,
  `fixed_params`, + `_bt_kwargs`) et délègue intégralement à `walk_forward_multi`. Pass-through
  pur, zéro divergence possible par construction.

- **(c) Holdout retiré avant la recherche, jamais consommé sans `final` — PASS, MESURÉ.**
  `research_runners.py:405-417` : `research[sym] = df.iloc[:cut]` où
  `cut = holdout_split(len(df), holdout_frac)` — **seule** `research` (jamais `data`, qui contient
  le holdout) est passée à `walk_forward_multi` (ligne 434). `holdout_check` n'est appelé
  (ligne 444-457) que si `params.get("final") and holdout_frac > 0`. Identique au flux CLI
  (`main.py:196-230` : retrait avant `walk_forward`/`walk_forward_multi`, `holdout_check` appelé
  seulement `if getattr(args, "final", False)`). `holdout_split` est **la même fonction importée**
  (`optimizer.py:233-244`, docstring : *« partagée par le CLI et holdout_check »*) — aucune
  frontière dupliquée pouvant diverger.

- **(d) Métriques dégénérées NaN/inf jamais traitées comme succès — PASS, MESURÉ.**
  `_mono_severity` et `_holdout_severity` (`walkforward_page.py:413`, `433`) testent
  `not math.isfinite(...)` en PREMIÈRE branche, avant tout autre calcul — exactement l'ordre de
  `optimizer._verdict` (`optimizer.py:528`). Côté affichage brut, `trading/metrics_format.py`
  rend NaN en `"n/a"` / classe CSS `"neu"` (jamais `"up"`), donc aucune fausse couleur verte sur
  une métrique dégénérée dans les tables de fenêtres (`_windows_table`, ligne 540-561).
  Tests dédiés : `test_render_walkforward_done_mono_orange_when_metric_nan_is_indecidable`
  (ligne 315), `test_mono_severity_parity_with_cli_verdict_across_scenarios` (ligne 324, couvre
  `nan` ET `inf`), `test_holdout_severity_parity_with_cli_verdict_across_scenarios` (ligne 448).

- **(e) Agrégation multi-actifs fidèle au moteur — PASS, MESURÉ.**
  `_verdict_banner` (`walkforward_page.py:459-514`) lit `summary["robust"]`, `summary["n_positive"]`,
  `summary["n_assets"]` **directement**, sans aucun recalcul — confirmé par lecture : aucune
  formule de robustesse n'existe dans `walkforward_page.py` pour le cas multi-actifs (seul le cas
  mono-actif calcule quelque chose, via `_mono_severity`, précisément parce que
  `summary["robust"]` DÉGÉNÈRE pour `n_assets==1`, cf. BUG-010). `summary` vient tel quel de
  `walk_forward_multi` (`optimizer.py:322-331`, commenté *« SOURCE DE VERITE UNIQUE… jamais de
  re-test divergent »*). `format_walk_forward_multi` (CLI, ligne 464-492) lit exactement les
  mêmes champs (`s['n_assets']`, `s['n_positive']`, `s['avg_oos_return']`, `s["robust"]`) —
  aucune divergence de calcul possible entre les deux affichages, ils lisent le même dict.

- **(f) Verdict web = même donnée moteur que la CLI (BUG-010/BUG-011) — PASS, MESURÉ.**
  `tests/test_walkforward_page.py:22` importe `from trading.optimizer import _verdict as
  cli_verdict` — **appel direct de la fonction moteur**, pas une copie recopiée à la main. Lecture
  branche par branche :
  - `_mono_severity(avg_window_metric, oos_total_return)` reproduit EXACTEMENT
    `optimizer._verdict(avg_window_metric, 1.0, oos_total_return, wf=True)` (le même appel que
    `format_walk_forward`, `optimizer.py:422`) : 4 branches dans le même ordre (non-fini →
    indécidable ; return<0 ou metric<0 → rouge ; metric < 0.5\*max(1.0,1e-9)=0.5 → orange ;
    sinon vert). Seuils identiques (0.5, pas de constante réinventée).
  - `_holdout_severity(metric_value, total_return)` reproduit EXACTEMENT
    `optimizer._verdict(metric_value, 0.0, total_return)` (même appel que `format_holdout`,
    `optimizer.py:520`) : même ordre de branches, seuil `0.5 * max(0.0, 1e-9)` **recopié comme
    formule**, pas comme constante précalculée — évite toute dérive de précision flottante.
  - Tests de parité (`test_mono_severity_parity_with_cli_verdict_across_scenarios` ligne 324,
    `test_holdout_severity_parity_with_cli_verdict_across_scenarios` ligne 448) rejouent CHAQUE
    scénario (NaN, inf, négatif, sur-apprentissage, succès) INDIVIDUELLEMENT contre `cli_verdict`
    importé — conforme V16 (pas un échantillon global).
  - BUG-010/BUG-011 sont au statut **Vérifié** au registre (`docs/SQA.md:62-63`), avec commit et
    test de non-régression référencés — cohérent avec ce que la lecture du code confirme.

- **(g) Gardes serveur identiques aux messages CLI — MARGINAL** (cf. section dédiée ci-dessus).
  La RÈGLE (bornes `[0, 90[`, `final` exige `holdout>0`) est identique et testée serveur
  (`tests/test_monitor_server.py:714-739`, POST HTTP réel), mais le TEXTE diffère de la CLI.

### Lentille 2 — Sécurité

- **(a) CSRF sur POST /research/walkforward — PASS, MESURÉ.**
  `trading/monitor.py:1472-1483` : `if not self._host_ok(): return` puis
  `if not csrf_valid(form.get("csrf_token"), csrf_token): ... 403 ...` AVANT tout appel à
  `_research_walkforward_post`. Même patron que `/research/backtest|compare|optimize|portfolio`
  (lignes 1416-1471), aucune exception pour walkforward. Test d'intégration réel :
  `tests/test_monitor_server.py::test_route_research_walkforward_post_sans_csrf_rejete` (ligne
  699) — vrai POST HTTP sans token, vérifie `exc.value.code == 403`.

- **(b) `host_allowed` — PASS, MESURÉ.**
  `host_allowed(host_header, port)` (`monitor.py:867-875`) : anti DNS-rebinding, liste blanche
  stricte `127.0.0.1`/`localhost` + port. `_host_ok()` (ligne 962-971) l'appelle et renvoie 403
  avant tout traitement — appelé en tête de la route walkforward (ligne 1473), identique aux
  autres routes de recherche.

- **(c) `final=1` sans confirmation — garde CÔTÉ SERVEUR — PASS, MESURÉ.**
  La garde métier (`final` implique `holdout_pct > 0`) est vérifiée SERVEUR dans
  `parse_walkforward_params` (`walkforward_page.py:207-211`), appelée par
  `_research_walkforward_post` **avant** toute soumission de job — donc avant que la modale JS
  (`_FINAL_CONFIRM_JS`, purement côté navigateur) n'entre en jeu. Test qui simule EXACTEMENT
  « un POST forgé sans passer par la modale JS » :
  `tests/test_monitor_server.py::test_route_research_walkforward_post_final_sans_holdout_exact_cli_message`
  (ligne 725) — commentaire du test : *« même un POST forgé sans passer par la modale JS est
  refusé »* — POST direct avec `final=1, holdout=0`, vérifie `code==200` + message d'erreur +
  `"class='job-panel'" not in page` (aucun job créé). Note de conception (documentée dans le code,
  `monitor.py:1111-1114`) : le `window.confirm()` est explicitement de l'UX (friction anti-double-
  clic), pas une frontière de sécurité — la frontière de sécurité réelle contre une requête
  cross-site forgée est le CSRF (point a), déjà couvert. Pour un utilisateur légitime qui soumet
  `final=1` avec `holdout>0` via un outil (curl/devtools) en sautant volontairement le confirm(),
  aucune règle métier n'est violée : c'est son propre navigateur, son propre token CSRF, sa propre
  décision. Pas de faille.

- **(d) job_id validé/échappé — PASS, MESURÉ.**
  `_REPORT_RE = re.compile(r"^/report/([0-9a-f]{32})/?$")` (`monitor.py:893`) — regex stricte hex
  32 caractères, appliquée à `/report/<job_id>` (utilisé par le panneau de job walkforward via
  `job_panel_html(job_id, ..., result_url=f"/report/{job_id}")`, `walkforward_page.py:365,380`).
  Générique à tous les écrans de recherche, pas de chemin dédié walkforward non-validé.

- **(e) Aucun secret dans logs de job / HTML — PASS, MESURÉ (par lecture).**
  `progress.log(...)` dans `run_walkforward` (`research_runners.py:411-413,429-431,445,456,459`)
  ne journalise que symbole/pourcentage holdout/nom de stratégie/nombre de fenêtres/messages
  d'erreur applicatifs (`str(exc)` sur des `RuntimeError` internes à l'optimizer, jamais une
  exception réseau brute portant des en-têtes signés). Formulaire POST walkforward ne contient
  aucun champ de type clé/secret (`strategy`, `symbols`, `timeframe`, `days`, `source`, `windows`,
  `train_frac`, `metric`, `fixed`, `holdout`, `final`, risque). `KrakenExchange()` (via
  `_load_basket_ohlcv`, réutilisé tel quel du Lot 5) n'est pas un point d'introduction de risque
  spécifique au Lot 6.

- **(f) JobBusy respecté — PASS, MESURÉ.**
  `_research_walkforward_post` (`monitor.py:1110-1130`) : `except JobBusy:` renvoie
  `render_walkforward_busy(...)` au lieu de créer un 2e job. Test paramétré couvrant explicitement
  walkforward : `tests/test_monitor_server.py::test_route_research_lot5_screens_refuse_second_job_while_busy`
  (ligne 786, paramètre `("/research/walkforward", {"strategy": "sma"})` ligne 784) — job bloquant
  réel + 2e POST + vérifie `"déjà en cours" in page` et qu'un panneau de job (celui du job existant)
  reste affiché, pas un nouveau.

- **(g) Rien ne peut désactiver SSL — PASS, MESURÉ (par absence).**
  `grep VERIFY_SSL|verify_ssl` sur `trading/walkforward_page.py` et `trading/research_runners.py`
  → 0 occurrence. Le Lot 6 ne touche jamais `config.VERIFY_SSL` ni `Exchange(verify_ssl=...)`.

### Lentille 3 — Non-régression + qualité des tests

- **(a) Dispatch `render_result_done` préserve backtest/compare/optimize/portfolio — PASS, MESURÉ.**
  `trading/report_page.py::render_result_done` (lignes 140-171) : chaîne `if/if/if/if` sur
  `result.get("kind")`, chaque branche antérieure (`compare`, `optimize`, `portfolio`) intacte,
  branche `walkforward` ajoutée en 4e position (ligne 168-170), défaut `backtest`/absent →
  `render_report_done` (comportement Lot 4 préservé). Test dédié :
  `tests/test_report_page.py::test_render_result_done_dispatches_walkforward` (ligne 132) +
  suite complète verte (554/554) qui couvre les autres `kind` sans régression détectée.

- **(b) Nav cohérente — PASS, MESURÉ.**
  `RESEARCH_SUBNAV` (`webui.py:137-143`) inclut `("walkforward", "Walk-forward",
  "/research/walkforward", True)` — activé au même niveau que les 4 autres écrans de recherche.
  `research_subnav_html("walkforward")` marque l'onglet actif via la classe CSS `sub-tab active`.
  Test : `tests/test_monitor_server.py::test_route_research_subnav_links_walkforward_screen`
  (ligne 774, vérifié depuis un AUTRE écran — `/research/backtest` — confirmant le lien croisé) +
  `test_route_research_walkforward_form_has_csrf_and_default_holdout` (ligne 696, vérifie l'état
  `active` depuis l'écran walkforward lui-même).

- **(c) Les tests du Lot 6 testent le COMPORTEMENT — PASS, avec 1 observation notée séparément.**
  Aucune assertion tautologique trouvée (`grep "assert True"` etc. → 0 résultat sur
  `test_walkforward_page.py` et `test_research_runners.py`). Les tests de parité
  (`test_mono_severity_parity_with_cli_verdict_across_scenarios`,
  `test_holdout_severity_parity_with_cli_verdict_across_scenarios`) appellent le VRAI code moteur
  et échoueraient si une branche divergeait — non contournables. Les tests d'intégration HTTP
  (`test_monitor_server.py`) font de VRAIES requêtes loopback (pas de mock du serveur). Seul point
  faible identifié : absence de test sur l'état du bandeau en cas de `holdout_errors` partiel (cf.
  observation dédiée ci-dessus) — un manque de couverture, pas un test qui ment.

- **(d) Aucune assertion existante affaiblie — PASS, MESURÉ.**
  `git diff 5db357c..244ef8a -- trading/walkforward_page.py tests/test_walkforward_page.py
  trading/research_runners.py trading/monitor.py trading/report_page.py` (5db357c = commit du
  fix BUG-010/011, 244ef8a = HEAD) : le diff sur `tests/test_walkforward_page.py` ne contient QUE
  des corrections d'accents (`"Strategie inconnue"` → `"Stratégie inconnue"`,
  `"MITIGE"` → `"MITIGÉ"`, etc. — 12 lignes, toutes des ajouts de caractères accentués dans les
  chaînes déjà testées, aucune suppression de logique). `grep -c "^-def "` / `"^+def "` sur
  l'ensemble du diff (5 fichiers, y compris `monitor.py` dont le diff brut fait 2761 lignes à
  cause d'une passe d'accentuation globale hors Lot 6, Lot 9) → **0 fonction ajoutée ou
  supprimée** dans ce diff. Aucune régression de couverture détectée sur le périmètre Lot 6.

- **(e) Tests de parité BUG-010/011 rejouent bien `optimizer._verdict` importé — PASS, MESURÉ.**
  `tests/test_walkforward_page.py:22` : `from trading.optimizer import _verdict as cli_verdict`
  — import direct du symbole privé du module moteur, pas une chaîne recopiée dans le fichier de
  test. `test_mono_severity_parity_with_cli_verdict_across_scenarios` (ligne 336) appelle
  `cli_verdict(avg_metric, 1.0, oos, wf=True)` ; `test_holdout_severity_parity_with_cli_verdict_across_scenarios`
  (ligne 456) appelle `cli_verdict(metric_value, 0.0, total_return)` — mêmes arguments que les
  appels réels dans `optimizer.py` (`format_walk_forward` ligne 422, `format_holdout` ligne 520).
  Si `optimizer._verdict` change un jour, ces tests casseront automatiquement — pas une copie qui
  peut dériver silencieusement.

---

## Verdict global

**Le Lot 6 (écran walk-forward) est GATABLE : 0 P0, 0 P1, 0 P2 trouvés sur les 3 lentilles
revues.** 1 point MARGINAL (P3, cosmétique — libellé de test/docstring sur-vendant une parité
textuelle avec la CLI qui n'existe pas, alors que la parité de RÈGLE, elle, est réelle et
prouvée) + 1 observation de couverture de test non bloquante (bandeau vs holdout_errors partiel,
information déjà visible ailleurs sur la page). Combiné à BUG-010 (P1) et BUG-011 (P2) déjà
Vérifiés/Fermés (lentille honnêteté), aucun défaut ouvert ne s'oppose à une déclaration de gate
SQA pour ce lot.

**FAIL** : aucun.
**MARGINAL** : 1 (Lentille 1(g) — texte de garde serveur non byte-identique à la CLI, règle
identique, P3, non bloquant).
