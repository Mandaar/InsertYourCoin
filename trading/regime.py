"""
Detecteur de REGIME par VOTE de plusieurs horizons (etage 1, AUCUNE IA).

Ce que c'est, sans enrobage
---------------------------
`docs/design/MODE_ADAPTATIF_SPEC.md` §3 etage 1 pose le probleme mesure par l'etude #5 :
le TSMOM ne gagne qu'a **365 j**, encadre de deux valeurs PERDANTES (180 et 540 negatifs
sur BTC). Construire un systeme sur 365 serait batir sur du sable. La reponse de la spec
n'est pas de choisir un meilleur lookback -- c'est de n'en choisir AUCUN :

    5 horizons votent (180 / 270 / 365 / 450 / 540), le regime est la MAJORITE.

Aucun parametre n'est appris, aucun seuil n'est regle sur les donnees. Les 5 horizons
sont IMPOSES par la spec : ils ne sont ni choisis ici, ni optimises, ni retires apres
coup (docs/ETUDE_11_REGIME.md §0.3, criteres geles avant toute mesure).

Ce que ce module fait, et ce qu'il ne fait pas
----------------------------------------------
- FAIT : agrege 5 signaux TSMOM (la brique validee de l'etude #5, reutilisee telle
  quelle -- `TSMomentum`) en un etat binaire RISK-ON / RISK-OFF.
- NE FAIT PAS : l'etat NEUTRE (exposition 1/2) de l'etage 2. Raison MESUREE, pas un
  choix de confort -- voir "Pourquoi binaire" ci-dessous.
- NE FAIT PAS : les trois autres entrees listees par la spec §3 etage 1 (pente de la
  moyenne longue, volatilite realisee vs sa mediane, drawdown courant). Raison : cette
  etude mesure LE VOTE, et rien d'autre. Ajouter une entree en meme temps rendrait
  impossible d'attribuer le resultat (M22 : on mesure la cible SANS la transformation
  avant d'ajouter la transformation suivante). Chaque entree supplementaire devra
  gagner sa place sur ses propres criteres geles, une a la fois.

Pourquoi binaire (0/1) et pas 0 / 0.5 / 1
------------------------------------------
Deux faits mesures dans le code existant, tous deux hors du perimetre de cette mission :

1. `trading/backtester.py` : `signal = strategy.generate_signals(df).astype(int)` puis
   des tests `desired[i] == 1` / `== 0`. Un signal 0.5 serait TRONQUE a 0 -- le NEUTRE
   deviendrait silencieusement du cash, ce qui est pire que de ne pas l'implementer.
2. `tests/test_strategies.py::test_signal_shape` exige, pour CHAQUE cle du registre,
   `set(sig.unique()).issubset({0, 1})`.

Point d'extension pour l'etage 2 (NEUTRE) : le compte de voix est deja disponible via
`vote_counts()` / `votes()`. L'exposition fractionnaire se branche cote MOTEUR (la ou
`Backtester._size_series` calcule deja une fraction de capital pour le sizing par
volatilite), pas cote strategie -- c'est un lot separe, avec ses propres criteres.
"""
import pandas as pd

from .strategies import Strategy, TSMomentum

# Horizons du vote : GELES par la spec (§3 etage 1) et par docs/ETUDE_11_REGIME.md §0.2.
# Ce ne sont pas des parametres a regler : les modifier invalide l'etude.
DEFAULT_LOOKBACKS = (180, 270, 365, 450, 540)

# Marge d'amorcage ajoutee au plus long horizon pour `warmup_bars` (lu par
# `optimizer.walk_forward`). 60 bougies = ~2 mois : de quoi que le membre le plus lent
# soit deja DECIDE (et pas juste ne) au premier jour hors-echantillon.
WARMUP_EXTRA = 60

# Etiquettes lisibles (journal / futur ecran "Regime"). NEUTRE existe dans la spec
# (etage 2) mais n'est PAS produit par cet etage -- voir l'en-tete du module.
RISK_ON = "RISK-ON"
RISK_OFF = "RISK-OFF"


class RegimeVoteStrategy(Strategy):
    """
    Regime de marche par vote de N horizons de momentum, long/flat.

    Chaque horizon L vote 1 si `close[t] > close[t - L]` (exactement `TSMomentum(L)`,
    la brique de l'etude #5), 0 sinon. Un horizon dont le decalage n'est pas encore
    disponible (debut de serie) vote 0 -- meme convention que `TSMomentum` : tant qu'on
    ne SAIT pas, on est hors marche.

    Regime = MAJORITE STRICTE des voix (`len(lookbacks) // 2 + 1`, soit 3 sur 5).
    Le seuil n'est pas un parametre : il est calcule, pour qu'il n'y ait rien a regler.

    Sortie : 1 = RISK-ON (exposition pleine), 0 = RISK-OFF (cash).

    Aucun lookahead : a l'instant t, chaque voix ne lit que des clotures <= t
    (`shift(L)` est un decalage vers le PASSE). Le backtester decale ensuite le signal
    d'une bougie (execution a l'ouverture de t+1), comme pour toutes les strategies.
    """

    def __init__(self, lookbacks=DEFAULT_LOOKBACKS):
        if isinstance(lookbacks, str):
            lookbacks = [int(x) for x in lookbacks.replace(";", ",").split(",") if x.strip()]
        elif isinstance(lookbacks, int):
            lookbacks = [lookbacks]
        looks = tuple(int(x) for x in lookbacks)
        if not looks:
            raise ValueError("RegimeVoteStrategy : au moins un horizon est requis.")
        if any(x < 1 for x in looks):
            raise ValueError(f"RegimeVoteStrategy : horizons >= 1 attendus, recu {looks}.")
        self.lookbacks = looks
        # Majorite stricte -- CALCULEE, jamais reglee (3 voix sur 5).
        self.min_votes = len(looks) // 2 + 1
        self.name = ("Regime(vote " + "/".join(str(x) for x in looks)
                     + f", majorite {self.min_votes}/{len(looks)})")
        # Journal de decision de la DERNIERE bougie (meme role que SMACrossover.gate_info :
        # le paper doit pouvoir ecrire POURQUOI il est dans cet etat).
        self.gate_info = None

    @property
    def warmup_bars(self) -> int:
        """
        Bougies d'amorcage necessaires avant que TOUS les membres puissent voter.
        Lu par `optimizer._declared_warmup` : sans cela, le walk-forward n'accorderait
        que `max(WARMUP=250, ...)` de marge et le membre 540 passerait chaque fenetre
        hors-echantillon muet -- un handicap qui n'existe pas en trading reel.
        """
        return max(self.lookbacks) + WARMUP_EXTRA

    def votes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Voix de chaque horizon (colonnes 'L180', 'L270', ... ; valeurs 0/1)."""
        return pd.DataFrame(
            {f"L{L}": TSMomentum(L).generate_signals(df) for L in self.lookbacks},
            index=df.index,
        )

    def vote_counts(self, df: pd.DataFrame) -> pd.Series:
        """Nombre d'horizons haussiers a chaque bougie (0..len(lookbacks))."""
        return self.votes(df).sum(axis=1).astype(int)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        votes = self.votes(df)                      # calcule UNE fois
        counts = votes.sum(axis=1).astype(int)
        signal = (counts >= self.min_votes).astype(int)
        n_pour = int(counts.iloc[-1]) if len(counts) else 0
        self.gate_info = {
            "voix_pour": n_pour,
            "voix_total": len(self.lookbacks),
            "majorite_requise": self.min_votes,
            "regime": RISK_ON if n_pour >= self.min_votes else RISK_OFF,
            "detail": ({col: int(votes[col].iloc[-1]) for col in votes.columns}
                       if len(df) else {}),
        }
        return signal

    def regime_labels(self, df: pd.DataFrame) -> pd.Series:
        """Serie d'etiquettes lisibles (journal / futur ecran 'Regime')."""
        return self.generate_signals(df).map({1: RISK_ON, 0: RISK_OFF})


# Grille de l'optimiseur : `optimizer.walk_forward` lit DEFAULT_GRIDS[nom] AVANT de
# regarder `fixed_params`, donc une strategie du registre sans entree de grille y
# leve KeyError. `trading/optimizer.py` est HORS PERIMETRE de cette mission (un autre
# chantier y travaille), d'ou cette fonction : elle pose l'entree a l'execution, sans
# toucher le fichier. La "grille" ne contient QU'UNE combinaison -- les horizons sont
# geles, il n'y a rien a optimiser (n_trials = 1 dans les deux modes).
# A faire lors du branchement CLI/web : recopier cette entree en dur dans DEFAULT_GRIDS.
REGIME_GRID = ({"lookbacks": [DEFAULT_LOOKBACKS]}, None)


def ensure_optimizer_grid():
    """Enregistre la grille (une seule combinaison) si elle manque. Idempotent."""
    from . import optimizer
    optimizer.DEFAULT_GRIDS.setdefault("regime", REGIME_GRID)
    return optimizer.DEFAULT_GRIDS["regime"]


# Auto-enregistrement dans le registre commun, comme `trading/predictive.py` : couvre
# le cas ou ce module est importe AVANT `trading.strategies` (l'import place au bas de
# strategies.py trouve alors ce module partiellement initialise et abandonne).
from .strategies import STRATEGIES  # noqa: E402

STRATEGIES.setdefault("regime", RegimeVoteStrategy)
