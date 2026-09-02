"""
Strategie PREDICTIVE (etude #8) -- classification d'etat par regression logistique.

Ce que c'est, sans enrobage
---------------------------
`MODE_ADAPTATIF_SPEC.md` §2b dit que ce terrain est celui ou meurent les projets de
quant amateur (rapport signal/bruit, trop peu de points, non-stationnarite, frais).
Ce module ne discute pas cette analyse : il fournit l'objet a TESTER pour la trancher
avec des chiffres (docs/ETUDE_8_PREDICTIF.md, criteres geles AVANT toute mesure).

Choix de conception, tous imposes par la spec et les criteres geles :

- on ne predit PAS un prix ni un rendement : on classe un ETAT binaire
  (« les H prochains jours sont-ils haussiers ? ») -> investi / hors marche ;
- modele SIMPLE et interpretable : regression logistique L2, 6 caracteristiques,
  descente de gradient a nombre d'iterations fixe, initialisee a ZERO
  -> aucun aleatoire, resultat strictement DETERMINISTE (pas de graine a gerer) ;
- pas de dependance nouvelle : numpy pur (sklearn n'est pas dans requirements.txt,
  et cette etude ne justifie pas d'en ajouter une) ;
- reentrainement GLISSANT : a la bougie i, le modele n'est entraine que sur des
  lignes dont l'etiquette etait DEJA CONNUE a i (voir la garantie ci-dessous).

Garantie anti-lookahead (le point critique de tout ce domaine)
--------------------------------------------------------------
L'etiquette de la ligne j vaut « close[j+H] > close[j] » : elle n'est connue qu'a la
bougie j+H. A la bougie i on n'entraine donc QUE sur les lignes j telles que
`j + H <= i`. Les caracteristiques de la ligne j n'utilisent, elles, que des cloture
<= j. Aucune information posterieure a i n'entre dans la decision prise en i.
Le backtester decale ensuite le signal d'une bougie (execution a l'ouverture de i+1),
comme pour toutes les autres strategies du projet.
`tests/test_predictive.py` verifie cette garantie sur une serie ou le futur est
trivialement predictible : la strategie ne doit PAS le voir.
"""
import numpy as np
import pandas as pd

from .strategies import Strategy

# Fenetres des caracteristiques (GELEES, cf. docs/ETUDE_8_PREDICTIF.md §0.3).
MOM_WINDOWS = (20, 60, 180)
VOL_FAST, VOL_SLOW = 20, 100
DD_WINDOW = 180
SMA_WINDOW = 200
FEATURE_MAX_WINDOW = max(max(MOM_WINDOWS), VOL_SLOW, DD_WINDOW, SMA_WINDOW)

FEATURE_NAMES = ("mom20", "mom60", "mom180", "vol_ratio", "drawdown180", "ecart_sma200")


def build_features(close: pd.Series) -> pd.DataFrame:
    """
    6 caracteristiques calculees UNIQUEMENT sur le passe (aucun shift negatif).
    A l'indice t, toutes les valeurs n'utilisent que des clotures <= t.
    """
    rets = close.pct_change()
    feats = {
        "mom20": close / close.shift(MOM_WINDOWS[0]) - 1.0,
        "mom60": close / close.shift(MOM_WINDOWS[1]) - 1.0,
        "mom180": close / close.shift(MOM_WINDOWS[2]) - 1.0,
        # volatilite realisee courte rapportee a la longue (log : symetrique)
        "vol_ratio": np.log((rets.rolling(VOL_FAST).std() + 1e-12)
                            / (rets.rolling(VOL_SLOW).std() + 1e-12)),
        # drawdown depuis le plus haut glissant (<= 0)
        "drawdown180": close / close.rolling(DD_WINDOW).max() - 1.0,
        "ecart_sma200": close / close.rolling(SMA_WINDOW).mean() - 1.0,
    }
    return pd.DataFrame(feats, index=close.index)[list(FEATURE_NAMES)]


def _fit_logistic(x, y, l2, iters, lr):
    """
    Regression logistique L2, descente de gradient a pas fixe, poids initialises a
    ZERO -> deterministe (aucun tirage aleatoire, aucune graine).
    `x` est deja standardise ; l'intercept n'est PAS penalise.
    Retourne le vecteur de poids [intercept, w1..wk].
    """
    n, k = x.shape
    xb = np.hstack([np.ones((n, 1)), x])
    w = np.zeros(k + 1)
    for _ in range(iters):
        z = xb @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))
        grad = xb.T @ (p - y) / n
        grad[1:] += (l2 / n) * w[1:]
        w -= lr * grad
    return w


def _predict_proba(w, x):
    z = w[0] + x @ w[1:]
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


class LogisticRegimeStrategy(Strategy):
    """
    Classification d'etat : « le rendement des `horizon` prochaines bougies sera-t-il
    positif ? ». Probabilite > `threshold` -> investi (1), sinon hors marche (0).

    Parametres (valeurs par defaut = CONFIG PRIMAIRE gelee de l'etude #8) :
      horizon    : H, horizon d'etiquetage en bougies (5 jours en daily) ;
      min_train  : nb minimum de lignes etiquetees avant la premiere decision ;
      refit      : re-entrainement tous les N bougies (entre deux, poids conserves) ;
      l2, iters, lr, threshold : hyperparametres geles.

    Tant que l'historique disponible est insuffisant (moins de `min_train` lignes
    etiquetees), la strategie reste HORS MARCHE (0) -- elle ne plante pas et
    n'invente pas de position.
    """
    def __init__(self, horizon: int = 5, min_train: int = 300, refit: int = 30,
                 l2: float = 1.0, iters: int = 300, lr: float = 0.5,
                 threshold: float = 0.5):
        self.horizon = int(horizon)
        self.min_train = int(min_train)
        self.refit = max(1, int(refit))
        self.l2, self.iters, self.lr = float(l2), int(iters), float(lr)
        self.threshold = float(threshold)
        self.name = f"Predictif(logit, H={self.horizon}j)"
        # Dernier modele entraine (interpretabilite : poids lisibles par caracteristique).
        self.last_weights = None

    @property
    def warmup_bars(self) -> int:
        """
        Bougies d'amorcage necessaires AVANT de pouvoir decider quoi que ce soit :
        fenetre de caracteristique la plus longue + lignes d'entrainement + horizon.
        Lu par `walk_forward` pour dimensionner la marge amont des fenetres OOS
        (sans quoi la strategie passerait la moitie de chaque fenetre a l'arret).
        """
        return FEATURE_MAX_WINDOW + self.min_train + self.horizon

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].astype(float)
        n = len(close)
        out = np.zeros(n, dtype=int)
        if n <= self.horizon + self.min_train:
            return pd.Series(out, index=df.index)

        feats = build_features(close).to_numpy(dtype=float)
        valid = np.isfinite(feats).all(axis=1)
        # Etiquette de la ligne j : rendement des H bougies suivantes > 0.
        # y[j] n'est CONNU qu'a la bougie j + H (garantie appliquee ci-dessous).
        future = close.shift(-self.horizon).to_numpy(dtype=float)
        cur = close.to_numpy(dtype=float)
        with np.errstate(invalid="ignore"):
            y = (future > cur).astype(float)
        y_known = np.isfinite(future)

        w = None
        mu = sd = None
        etat = 0
        n_since_fit = 0
        for i in range(n):
            if not valid[i]:
                out[i] = 0
                continue
            # Lignes ENTRAINABLES a la bougie i : etiquette deja observee (j + H <= i).
            last_train = i - self.horizon
            if last_train < 0:
                out[i] = 0
                continue
            usable = valid[:last_train + 1] & y_known[:last_train + 1]
            n_usable = int(usable.sum())
            if n_usable < self.min_train:
                out[i] = 0
                continue
            if w is None or n_since_fit >= self.refit:
                xt = feats[:last_train + 1][usable]
                yt = y[:last_train + 1][usable]
                mu = xt.mean(axis=0)
                sd = xt.std(axis=0)
                sd[sd < 1e-12] = 1.0
                w = _fit_logistic((xt - mu) / sd, yt, self.l2, self.iters, self.lr)
                self.last_weights = dict(zip(("intercept",) + FEATURE_NAMES, w))
                n_since_fit = 0
            n_since_fit += 1
            p = _predict_proba(w, (feats[i] - mu) / sd)
            etat = 1 if p > self.threshold else 0
            out[i] = etat
        return pd.Series(out, index=df.index)


# Auto-enregistrement dans le registre commun. Necessaire quand ce module est
# importe AVANT `trading.strategies` : dans cet ordre, l'import place au bas de
# strategies.py trouve `trading.predictive` partiellement initialise et abandonne
# (silencieusement, par construction) -- c'est donc ici que la cle est posee.
from .strategies import STRATEGIES  # noqa: E402

STRATEGIES.setdefault("predictive", LogisticRegimeStrategy)
