# SETUP — Installation propre d'InsertYourCoin

Guide pour installer et lancer l'outil **proprement** sur ta machine (Windows, macOS, Linux),
y compris **derrière un antivirus ou un proxy d'entreprise** qui scanne le HTTPS.

> Philosophie : une install Python standard, isolée dans un *venv*, reproductible et
> facile à supprimer. Pas d'exécutable « tout-en-un » (les `.exe` PyInstaller déclenchent
> de faux positifs antivirus) — on reste sur `python main.py …`.

---

## 1. Prérequis
- **Python 3.11+ recommandé** (3.10 minimum). Vérifie : `python --version`.
- **git** (pour cloner) — ou récupère l'archive du projet.

## 2. Récupérer le projet
```bash
git clone <url-du-repo>      # ou décompresse l'archive
cd InsertYourCoin
```

## 3. Créer un environnement isolé (venv) — recommandé
N'installe rien dans ton Python système, garde l'install reproductible, supprimable d'un `rm`.

**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Si bloqué par l'execution policy :
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# puis relance la ligne d'activation.
```

**Windows (cmd)**
```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 4. Installer les dépendances
```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 5. Vérifier l'installation — une seule commande
```bash
python main.py check
```
Affiche les versions installées puis teste la connexion Kraken :
`OK : connexion Kraken fonctionnelle (ETH/USD = …)`.
Si tu vois une **erreur SSL**, lis la section suivante.

## 6. Antivirus / proxy qui scanne le HTTPS (SSL) — IMPORTANT
Beaucoup d'antivirus (Avast, AVG, Kaspersky, ESET, Bitdefender…) et les proxys
d'entreprise **interceptent le HTTPS** : ils re-signent les certificats avec leur propre
autorité racine, **absente du bundle de certificats de Python** (`certifi`). Sans rien
faire, `ccxt`/`requests` échouent en `CERTIFICATE_VERIFY_FAILED` contre Kraken.

**Solution automatique, déjà en place :** le paquet **`truststore`** (dans
`requirements.txt`) fait utiliser le **magasin de certificats de l'OS** — où la racine de
ton antivirus est déjà approuvée. On **ne désactive JAMAIS** la vérification SSL
(`config.VERIFY_SSL` reste `True`).
➜ Si `python main.py check` affiche un prix, **tout va bien, rien à faire**.

**Cas particulier — si `pip install` lui-même échoue en SSL** (l'antivirus scanne aussi PyPI) :
- **Option A (propre)** : assure-toi que la CA de ton antivirus est bien dans le magasin
  Windows (l'antivirus le fait normalement tout seul), puis réessaie.
- **Option B (dépannage install)** :
  ```bash
  python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
  ```
  Cela ne contourne la vérification **que** pour télécharger les paquets ; le runtime
  (connexion Kraken) reste protégé par `truststore` + SSL activé.
- **Option C** : désactive temporairement le « scan HTTPS » de ton antivirus, installe, réactive.

## 7. Clés API Kraken (UNIQUEMENT pour soldes + trading réel)
`backtest`, `optimize`, `walkforward`, `portfolio`, `paper` marchent **sans clés**.
Pour le live et la lecture des soldes :
1. Sur Kraken : **Settings → API → Create API key**.
2. **Sécurité** : coche **seulement** *Query Funds* et *Create & Modify Orders*.
   **NE coche PAS** *Withdraw Funds* (retrait).
3. Crée ton `.env` à partir du modèle :
   ```bash
   cp .env.example .env        # Windows PowerShell : Copy-Item .env.example .env
   ```
4. Colle tes deux clés dans `.env`. **Ne commite jamais `.env`** (déjà dans `.gitignore`).

## 8. Premiers tests (sans clés)
```bash
python main.py compare --timeframe 1d
python main.py backtest --strategy sma --stop-loss 8 --take-profit 20 --chart bt.png
python main.py walkforward --strategy sma --windows 4
python main.py portfolio --symbols BTC/USD,ETH/USD,SOL/USD --strategy sma --stop-loss 8 --take-profit 20
python main.py dashboard --strategy sma --stop-loss 8 --take-profit 20   # ouvre dashboard.html
```

## 9. Workflow recommandé (toujours dans cet ordre)
1. **Backtest / compare** : éliminer ce qui ne marche pas.
2. **Walk-forward** : ne garder que ce qui tient hors-échantillon (le juge).
3. **Paper trading** : faire tourner en réel avec argent fictif, plusieurs semaines.
   - Labo de stats : `paper` accumule `paper_stats.csv` ; `python main.py stats` en donne
     une synthèse descriptive (rendement, drawdown, part des frais, ventilation heure/jour).
4. **Live** : seulement après, petits montants, garde-fous serrés (`config.py`).

---

## Lancer en un double-clic (paper + monitoring)
Pour « lancer et laisser tourner » sans taper de commande :
- **Windows** : double-clique `lancer.bat` ;
- **macOS / Linux** : `./lancer.sh` (une fois `chmod +x lancer.sh`).

Le lanceur fait, dans l'ordre : `main.py check` (diagnostic), démarre le **paper
trading** en arrière-plan (console dans `logs/paper_console.log`), démarre le
**monitoring** sur `http://127.0.0.1:8765` et ouvre ton navigateur dessus.
Relancer ne double rien : si paper/monitor tournent déjà, il les réutilise.

- **Arrêt** : double-clique `arreter.bat` (Windows) ou `python lancer.py --stop`.
- **État** : `python lancer.py --status` ; aperçu sans rien lancer : `python lancer.py --dry-run`.
- **Paper-only par construction** : ce lanceur ne sait lancer **que** paper + monitor
  (jamais `live`), n'exige **aucune clé API** et le monitoring reste en local (`127.0.0.1`).
- Les paramètres du paper (stratégie, timeframe, stop/objectif/trailing) se modifient
  en tête de `lancer.py`, en attendant une page Options.

---

## 10. Sécurité git (si tu publies le dépôt)
**Règle d'or : ne jamais committer de secret.** `.env` (clés Kraken), `paper_state.json`,
`live_trades.log` et les `*_stats.csv` sont déjà dans `.gitignore`. Avant chaque commit :
`git status` — vérifie qu'aucun `.env` n'apparaît. Si une clé fuite :
**révoque-la et régénère-la sur Kraken** (elle reste dans l'historique git sinon).

**Licence** : à toi de choisir (elle définit ce que les autres peuvent faire du code).
La **MIT** est une option permissive courante ; dis-moi si tu veux un fichier `LICENSE`.
**Avertissement** : garde l'encart « risque / pas un conseil en investissement / aucune
garantie » du `README.md` bien visible — important pour un dépôt public.

## 11. (Annexe) Ouvrir le projet dans Claude Code
- **App desktop** : section **Code** → ouvre le **dossier du projet** ; `CLAUDE.md` est lu
  automatiquement. (`/memory` affiche le contexte chargé ; inutile de lancer `/init`.)
- **Terminal** : `winget install Anthropic.ClaudeCode` (Windows), puis `cd` dans le dossier
  et `claude`. Doc : https://code.claude.com/docs/en/overview

---

## Checklist de démarrage
- [ ] venv créé **et activé**
- [ ] `python -m pip install -r requirements.txt`
- [ ] `python main.py check` → **OK** (sinon : section 6 Antivirus/SSL)
- [ ] (live seulement) clés Kraken **sans retrait** dans `.env`
- [ ] Choix : panier d'actifs (défaut `BTC/USD,ETH/USD,SOL/USD`), timeframe (défaut `1d`), capital de test et plafonds live (`config.py`)
- [ ] `VERIFY_SSL = True` (ne jamais réactiver le contournement du bac à sable)
