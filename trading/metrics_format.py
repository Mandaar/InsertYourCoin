"""
Petits formatteurs de metriques PARTAGES par les ecrans de recherche Lot 5
(Comparer/Optimiser/Portefeuille) -- memes conventions visuelles (couleur
up/down/neutre, "n/a" honnete sur NaN, "inf" sur profit factor infini) que
trading/dashboard.py, qui garde ses propres copies privees (_pct/_cls/_pf,
deja testees) pour ne prendre AUCUN risque de regression sur le Rapport
backtest existant (Lot 4). Fonctions PURES, aucune I/O.
"""
import math


def pct(v, signed=True):
    """Pourcentage lisible, ou "n/a" honnete si la valeur est absente/NaN
    (metrique degeneree -- cf. optimizer.MIN_TRADES) plutot qu'un faux 0%."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v*100:+.1f}%" if signed else f"{v*100:.1f}%"


def cls(v):
    """Classe CSS up/down/neu -- "neu" si absent/NaN (jamais fausse couleur)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "neu"
    return "up" if v > 0 else ("down" if v < 0 else "neu")


def num(v, decimals=2):
    """Nombre brut (sharpe, sortino...) ou "n/a" si absent/NaN."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:.{decimals}f}"


def pf(v):
    """Profit factor : 'inf' si infini (jamais de crash de formatage %-)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if isinstance(v, float) and math.isinf(v):
        return "inf"
    return f"{v:.2f}"
