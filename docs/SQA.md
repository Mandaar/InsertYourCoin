# SQA — Assurance qualite logicielle (InsertYourCoin)

> Systeme leger **inspire de la QA de REGNUM AETERNUM**, adapte a un outil solo Python.
> But : tracer les bugs, **correler chaque correctif a un test de non-regression**, et
> **reutiliser le vecu** (on s'inspire des enquetes passees avant d'en lancer une nouvelle).
> Enquetes narratives detaillees : `docs/ENQUETE_ET_AMELIORATIONS.md`.

## 1. Severites (adaptees au trading)
- **P0 — Critique** : risque financier reel (ordre live errone, perte de capital), crash en
  live, garde-fou de securite contourne (`VERIFY_SSL`, plafonds `config.py`, secret commite).
  -> on **arrete tout** jusqu'a resolution.
- **P1 — Majeur** : fonction cassee (connexion Kraken KO, collecte interrompue, calcul
  PnL/risque faux) ou **diagnostic impossible** (pas de logs).
- **P2 — Mineur** : degradation non bloquante (affichage, log bruyant, edge case rare).
- **P3 — Cosmetique** : confort, formatage, libelles.

## 2. Cycle de vie d'un bug
`Ouvert -> En enquete -> Corrige (commit) -> Verifie -> Ferme`
- **Ouvert** : symptome consigne dans le registre (§5, statut Ouvert).
- **En enquete** : appliquer la doctrine (`ENQUETE_ET_AMELIORATIONS.md` §1). **Etape 0
  obligatoire : s'inspirer du vecu** (cf. §3).
- **Corrige** : cause racine + **garde-fou par construction** ; commit reference dans le registre.
- **Verifie** : un **test de non-regression** existe et passe, + comportement observe
  (logs / dashboard / `stats`).
- **Ferme** : registre a jour (severite, commit, test, lien enquete).

> **Regle d'or (Loi anti-recidive)** : un bug n'est *ferme* que s'il a un **test** qui
> empeche sa recurrence. **Pas de test = bug encore ouvert.**

## 3. La systemique "s'inspirer du vecu" (etape 0 de toute enquete)
Avant toute nouvelle enquete, **lire d'abord** : le **registre des bugs** (§5) et le
**journal d'enquetes** (`ENQUETE_ET_AMELIORATIONS.md` §2). Beaucoup de symptomes se
repetent (reseau, SSL, frais, signal). Reutiliser une cause / un correctif deja documentes
fait gagner des heures et evite de re-deriver depuis zero.
- Cas **deja vecu** -> appliquer / adapter le correctif connu, verifier qu'il tient.
- Cas **nouveau** -> enqueter, puis **capitaliser** : nouvelle ligne au registre (§5) +
  enquete detaillee (§2 du carnet).

## 4. Gate qualite (avant un merge significatif ou un passage en live)
- [ ] `pytest` tout vert (sans reseau).
- [ ] Aucun **P0 / P1** ouvert.
- [ ] Garde-fous live intacts (dry-run par defaut, plafonds `config.py`, double confirmation).
- [ ] Aucun secret commite (`git status` : pas de `.env`).
- [ ] `VERIFY_SSL = True`.
- [ ] Chaque bug corrige du lot a son **test de non-regression**.

## 5. Registre des bugs (correlation bug <-> correctif <-> test)

| ID | Date | Sev | Symptome | Cause racine | Correctif (commit) | Test non-regression | Enquete | Statut |
|----|------|-----|----------|--------------|--------------------|---------------------|---------|--------|
| BUG-001 | 2026-06-05 | P1 | `CERTIFICATE_VERIFY_FAILED` contre Kraken | Avast intercepte le HTTPS ; sa CA racine est absente du bundle `certifi` | `9c17bac` puis centralise `5816567` (`truststore` -> magasin de certificats de l'OS ; `VERIFY_SSL=True`) | `tests/test_healthcheck.py` (`diagnose_error` -> ssl) | carnet §2 (#0) | **Ferme** |
| BUG-002 | 2026-06-05 | P1 | `kraken GET .../OHLC` en boucle la nuit + collecte morte ; process arrete | Timeouts reseau nocturnes **non journalises** (aucun log paper) + mise en veille du PC | `b9cf6d0` (logs paper typuees, backoff, timeout 30s, detection refus Kraken/DDoSProtection) + `42ae373` (dashboard) | `tests/test_resilience.py` | carnet §2 (#1) | **Ferme** |
| BUG-003 | 2026-06-07 | P2 | `config.FEE=0.0026` sous-estime le taker Kraken reel -> backtests & paper FLATTES (conclusions optimistes) | Taker spot Kraken palier de base = **0.40%** (maker 0.25%) d'apres la doc officielle, pas 0.26% | A FAIRE : `config.FEE` -> `0.0040` (taker), ou parametrer maker/taker selon le type d'ordre | A AJOUTER (assert que le backtester applique bien le frais configure) | panel §0 (hygiene de mesure) | **Ouvert** |

> **Nouveau bug** -> ajouter une ligne ici (statut *Ouvert*), puis suivre le cycle §2.
> Severite des le constat ; ne jamais fermer sans test.

---
*Inspiration : QA REGNUM (qa-lead / referentiel de regression / gate review), version solo.*
