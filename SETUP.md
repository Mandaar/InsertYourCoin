# SETUP — Ce que tu dois fournir et faire

Checklist de démarrage pour reprendre le projet dans **Claude Code** sur ta machine.

---

## 1. Récupérer le projet
Décompresse `InsertYourCoin.zip` quelque part de stable (ex : `C:\Users\…\projets\InsertYourCoin`).

## 2. Python + dépendances
- Python **3.10+** (`python --version`).
- Dans le dossier du projet :
  ```bash
  pip install -r requirements.txt
  ```

## 3. Ouvrir le projet dans Claude Code
Tu as déjà l'app Claude (desktop). Deux options :

- **App desktop** (le plus simple) : ouvre la section **Code**, puis ouvre le **dossier du projet**.
  Claude Code lira automatiquement `CLAUDE.md` au démarrage.
- **Terminal** (alternative) : installe Claude Code puis lance-le dans le dossier.
  Sous Windows : `winget install Anthropic.ClaudeCode`, ensuite `cd` dans le dossier et `claude`.

Doc officielle à jour : https://code.claude.com/docs/en/overview

> Astuce : une fois dedans, tu peux taper `/memory` pour voir le contexte chargé.
> Inutile de lancer `/init` : le `CLAUDE.md` est déjà fourni.

## 4. Clés API Kraken (UNIQUEMENT pour soldes + trading réel)
Le backtest, l'optimisation et le portefeuille marchent **sans clés**. Pour le live/soldes :

1. Sur Kraken : **Settings → API → Create API key**.
2. **Important sécurité** : ne coche QUE *Query Funds* et *Create & Modify Orders*.
   **NE coche PAS** la permission de retrait (*Withdraw Funds*).
3. Crée le fichier `.env` à partir du modèle :
   ```bash
   cp .env.example .env     # (Windows PowerShell : Copy-Item .env.example .env)
   ```
4. Édite `.env` et colle tes deux clés. **Ne commite jamais `.env`** (déjà dans `.gitignore`).

---

## 5. Premiers tests (sans clés, pour vérifier que tout tourne)
```bash
python main.py compare --timeframe 1d
python main.py backtest --strategy sma --stop-loss 8 --take-profit 20 --chart bt.png
python main.py walkforward --strategy sma --windows 4
python main.py portfolio --symbols BTC/USD,ETH/USD,SOL/USD --strategy sma --stop-loss 8 --take-profit 20
python main.py dashboard --strategy sma --stop-loss 8 --take-profit 20   # ouvre dashboard.html
```

## 6. Workflow recommandé (dans l'ordre, toujours)
1. **Backtest / compare** : éliminer ce qui ne marche pas.
2. **Walk-forward** : ne garder que ce qui tient hors-échantillon (le juge).
3. **Paper trading** : faire tourner en réel avec argent fictif, plusieurs semaines.
4. **Live** : seulement après, petits montants, garde-fous serrés.

---

## Ce que tu dois fournir / décider — résumé
- [ ] Projet décompressé + `pip install -r requirements.txt`
- [ ] Clés Kraken **sans retrait** dans `.env` (seulement pour paper-réel/live)
- [ ] Le panier d'actifs voulu (défaut conseillé : `BTC/USD,ETH/USD,SOL/USD`)
- [ ] Le timeframe visé (défaut `1d` ; l'intraday coûte plus de frais)
- [ ] Le capital de test et les plafonds live (`config.py` : `MAX_TRADE_VALUE_USD`, etc.)
- [ ] Rester sur `VERIFY_SSL = True` (ne pas réactiver le contournement du bac à sable)

---

## 7. Mettre InsertYourCoin en dépôt git (public plus tard)

**Avant tout — la règle d'or d'un repo public : ne jamais committer de secret.**
`.env` (tes clés Kraken) est déjà dans `.gitignore`, ainsi que `paper_state.json` et
`live_trades.log`. Vérifie toujours avec `git status` que `.env` n'apparaît pas avant un commit.
Si une clé est commitée par erreur : **révoque-la et régénère-la sur Kraken** (elle reste
dans l'historique git sinon).

Initialiser et publier (nom de dépôt suggéré : `insert-your-coin`) :
```bash
git init
git add .
git status                 # CONTROLE : aucun .env, aucun log, aucune cle
git commit -m "InsertYourCoin : version initiale"
# puis cree un repo vide sur GitHub et :
git remote add origin <url-du-repo>
git push -u origin main
```

**Licence** : le choix t'appartient (il définit ce que les autres peuvent faire de ton code).
La MIT est une option permissive courante pour un projet ouvert ; il en existe d'autres. Je ne
suis pas juriste — dis-moi si tu veux que j'ajoute un fichier `LICENSE` (MIT par défaut).

**Avertissement public** : le `README.md` contient déjà un avertissement « risque / pas un
conseil en investissement / aucune garantie » — important pour un dépôt public. Garde-le visible.
