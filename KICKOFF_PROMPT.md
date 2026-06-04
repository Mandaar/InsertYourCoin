# Prompt de démarrage — à coller dans Claude Code

Copie-colle le texte ci-dessous comme **premier message** dans Claude Code, une fois
le dossier du projet ouvert.

---

Bonjour ! Tu reprends un projet existant : **InsertYourCoin**, un **système de trading
algorithmique crypto sur Kraken** (Python, CLI). Lis d'abord `CLAUDE.md` à la racine — il contient le contexte,
les garde-fous et l'architecture, et il fait foi.

Contexte en deux mots : c'est du **capital qu'on peut se permettre de perdre**, pour tenter
d'amortir au mieux les coûts de mon projet "Regnum". **Ce n'est pas un salaire**, et je veux
de l'**honnêteté** : pas de promesse de gain, le walk-forward (perf hors-échantillon) est le
juge, et la priorité est la **gestion du risque** (préserver le capital), pas le jackpot.

Ce qui est déjà fait : backtest, comparaison, optimisation (train/test), walk-forward,
backtest de portefeuille, dashboard HTML, et paper/live avec stop-loss + take-profit.
Constat mesuré : la stratégie SMA n'a pas d'edge fiable sur la crypto récente — les outils
de risque lissent la courbe mais ne créent pas de profit. On part de cette réalité, sans se
raconter d'histoires.

Avant de coder quoi que ce soit :
1. Lis `CLAUDE.md` puis `SETUP.md`, et explore brièvement `main.py` et `trading/`.
2. Propose-moi un **plan** (Explore → Plan → Implement → Commit), ne fonce pas.

Première tâche visée (à confirmer ensemble) : **câbler le trailing stop et le
dimensionnement par volatilité dans `paper_trader.py` et `live_trader.py`** (ils existent
déjà dans le backtester), puis préparer un paper trading que je puisse lancer en continu.

Réponds-moi en français. On avance étape par étape, et tu me signales tout ce qui cloche
plutôt que de le masquer.
