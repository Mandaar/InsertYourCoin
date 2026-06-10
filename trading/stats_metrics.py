"""
Sharpe deflate / probabiliste — penaliser le data-mining (AUDIT B12+).

Un ratio de Sharpe seul ment : (1) il suppose des rendements normaux (la crypto a des
queues epaisses et de l'asymetrie), et (2) il ne dit rien du NOMBRE D'ESSAIS qu'on a
faits pour le trouver. Si on teste 100 combinaisons de parametres, la MEILLEURE aura un
Sharpe flatteur juste par chance, meme sans aucun edge reel.

Ce module implemente deux corrections de Bailey & Lopez de Prado :

- PSR (Probabilistic Sharpe Ratio) : probabilite que le VRAI Sharpe depasse un
  benchmark, en tenant compte de la taille d'echantillon, de l'asymetrie (skew) et de
  l'aplatissement (kurtosis). Source : Bailey & Lopez de Prado (2012), "The Sharpe Ratio
  Efficient Frontier", Journal of Risk.

- DSR (Deflated Sharpe Ratio) : un PSR dont le benchmark n'est pas 0 mais le Sharpe
  MAXIMAL qu'on s'attendrait a observer SOUS H0 (aucun edge) apres N essais. Plus on
  teste de combinaisons, plus ce seuil monte, plus la proba que l'edge soit reel baisse.
  Source : Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
  Selection Bias, Backtest Overfitting, and Non-Normality", Journal of Portfolio
  Management 40(5).

Fonctions PURES, sans dependance externe : scipy n'est PAS requis. La CDF normale est
calculee via math.erf ; l'inverse (quantile) via l'approximation rationnelle d'Acklam
(precision ~1e-9 sur [0,1]), suffisante ici. Si scipy etait present il pourrait remplacer
ces deux helpers, mais on evite d'ajouter une dependance pour si peu.
"""
import math

# Constante d'Euler-Mascheroni (gamma) -- utilisee dans l'esperance du maximum d'un
# echantillon de N gaussiennes (formule SR0 du DSR).
EULER_MASCHERONI = 0.5772156649015329

NAN = float("nan")


def _norm_cdf(x):
    """CDF de la loi normale standard : P(Z <= x). Via math.erf (pas de scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p):
    """
    Quantile de la loi normale standard (inverse de la CDF) : Z tel que P(Z<=z)=p.
    Approximation rationnelle d'Acklam (erreur relative ~1e-9). Sans scipy.
    p hors ]0,1[ -> -inf / +inf / NaN, proprement.
    """
    if not (p == p):            # NaN
        return NAN
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf

    # Coefficients d'Acklam.
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]

    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:                # queue basse
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    if p > phigh:               # queue haute
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    q = p - 0.5                 # region centrale
    r = q * q
    return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
           (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)


def probabilistic_sharpe_ratio(sharpe, n_obs, skew=0.0, kurt=3.0, sharpe_benchmark=0.0):
    """
    Probabilistic Sharpe Ratio (PSR).

    Probabilite que le VRAI Sharpe depasse `sharpe_benchmark`, etant donne un Sharpe
    OBSERVE `sharpe` sur `n_obs` observations, avec asymetrie `skew` et aplatissement
    `kurt` (kurtosis NON-excessif ; 3.0 = loi normale) des rendements.

    PSR = Phi( (SR - SR*) * sqrt(n-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2) )

    `sharpe` et `sharpe_benchmark` doivent etre exprimes dans la MEME unite (par
    observation, ou tous deux annualises). NaN/inf ou n_obs<2 -> NaN propre.
    Croit avec `sharpe`, avec `n_obs`, et decroit quand `sharpe_benchmark` monte.
    """
    sr = float(sharpe)
    if not math.isfinite(sr) or not math.isfinite(float(sharpe_benchmark)):
        return NAN
    if n_obs is None or n_obs < 2:
        return NAN
    denom_sq = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom_sq <= 0.0:         # variance d'estimation non definie -> indecidable
        return NAN
    z = (sr - float(sharpe_benchmark)) * math.sqrt(n_obs - 1.0) / math.sqrt(denom_sq)
    return _norm_cdf(z)


def expected_max_sharpe(n_trials, variance_trials_sharpe):
    """
    SR0 : Sharpe MAXIMAL attendu sous H0 (aucun edge) apres `n_trials` essais
    independants, dont les Sharpe ont une variance `variance_trials_sharpe`.

    SR0 = sqrt(V) * [ (1 - gamma) * Z^-1(1 - 1/N) + gamma * Z^-1(1 - 1/(N*e)) ]

    avec gamma = constante d'Euler-Mascheroni, e = exp(1), Z^-1 = quantile normal.
    C'est l'esperance du maximum d'un echantillon de N gaussiennes (Bailey-Lopez de
    Prado 2014). N=1 ou V<=0 -> 0.0 (un seul essai : aucun seuil de data-mining).
    """
    if n_trials is None or n_trials < 2:
        return 0.0
    v = float(variance_trials_sharpe)
    if not math.isfinite(v) or v <= 0.0:
        return 0.0
    n = float(n_trials)
    g = EULER_MASCHERONI
    z1 = _norm_ppf(1.0 - 1.0 / n)
    z2 = _norm_ppf(1.0 - 1.0 / (n * math.e))
    return math.sqrt(v) * ((1.0 - g) * z1 + g * z2)


def deflated_sharpe_ratio(sharpe, n_obs, n_trials, variance_trials_sharpe=None,
                          skew=0.0, kurt=3.0):
    """
    Deflated Sharpe Ratio (DSR) -- Bailey & Lopez de Prado (2014).

    Probabilite que le vrai Sharpe depasse le Sharpe maximal ATTENDU SOUS H0 apres
    `n_trials` essais. C'est un PSR dont le benchmark = SR0 (cf. expected_max_sharpe),
    et non 0. Plus `n_trials` est grand, plus SR0 monte, plus le DSR baisse :
    le data-mining est ainsi penalise.

    `variance_trials_sharpe` : variance des Sharpe des differentes combinaisons
    testees. Si None, on la borne par defaut a 1.0 (hypothese standard d'essais a
    variance unitaire faute de mieux) -- a fournir explicitement si on l'a mesuree.
    `sharpe`/SR0 doivent etre dans la MEME unite. NaN/inf -> NaN propre.
    """
    sr = float(sharpe)
    if not math.isfinite(sr):
        return NAN
    if n_trials is None or n_trials < 1:
        return NAN
    var = 1.0 if variance_trials_sharpe is None else variance_trials_sharpe
    sr0 = expected_max_sharpe(n_trials, var)        # 0.0 si n_trials<2
    return probabilistic_sharpe_ratio(sr, n_obs, skew=skew, kurt=kurt,
                                      sharpe_benchmark=sr0)
