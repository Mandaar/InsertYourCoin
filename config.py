"""
Configuration centrale du systeme de trading.
Cles API lues depuis l'environnement (.env). Voir .env.example.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Cles API Kraken ---
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")

# --- Marche ---
DEFAULT_SYMBOL = "ETH/USD"
DEFAULT_TIMEFRAME = "1d"
INITIAL_CAPITAL = 10_000.0

# =====================================================================
# HOLDOUT SACRE — registre GELE (garde-fou, incident #9 du 2026-09-01)
# =====================================================================
# Le holdout est une ressource qui NE SE RECONSTITUE PAS : une fois les bougies
# recentes regardees, elles ne sont plus hors-echantillon, pour toujours. Le
# 2026-09-01, `backtest --timeframe 1d --days 730` a recouvert INTEGRALEMENT le
# holdout ETH de l'etude #5 sans que personne ne soit averti (cf.
# docs/ENQUETE_ET_AMELIORATIONS.md, incident #9).
#
# Ce registre decrit l'HISTORIQUE DE REFERENCE sur lequel le holdout a ete
# decoupe -- PAS la frontiere elle-meme : la frontiere est CALCULEE par
# `trading.optimizer.holdout_split` (source UNIQUE, la meme que le walk-forward),
# jamais recopiee a la main.
#
# Provenance (DERIVE de docs/ETUDE_5_TSMOM_VS_BH.md §1 "Spans OOS effectifs") :
#   BTC/ETH : segment de recherche 2017-08-17 -> 2024-10-02 = 2604 bougies daily
#             (verifie : le calendrier daily continu donne exactement 2604).
#             holdout 20% => n total tel que holdout_split(n, 0.20) == 2604 => 3255,
#             soit une derniere bougie de reference au 2026-07-15 (etude datee du
#             2026-07-16 : la derniere bougie close est bien celle du 15) ->
#             recoupement independant qui confirme le compte.
#   SOL     : recherche 2020-08-11 -> 2025-05-08 = 1732 bougies => n = 2165,
#             derniere bougie de reference 2026-07-15 (meme recoupement).
# La ZONE RESERVEE est [frontiere, +inf[ : toute bougie plus recente que la
# frontiere n'a jamais ete vue par la recherche et reste reservee a la
# validation finale.
HOLDOUT_PCT = 20.0            # % de bougies recentes reservees (etude #5)

HOLDOUT_REFERENCES = {
    # actif de base (BTC/USD, BTC/USDT... -> "BTC") : historique de reference
    "BTC": {"start": "2017-08-17", "bars": 3255, "timeframe": "1d",
            "source": "binance", "study": "etude #5 (2026-07-16)"},
    "ETH": {"start": "2017-08-17", "bars": 3255, "timeframe": "1d",
            "source": "binance", "study": "etude #5 (2026-07-16)"},
    "SOL": {"start": "2020-08-11", "bars": 2165, "timeframe": "1d",
            "source": "binance", "study": "etude #5 (2026-07-16)"},
}

# Le decoupage a ete GELE sur Binance ; mais ce qui est reserve, c'est la PERIODE
# (les prix d'ETH en 2025 sont les memes sur Kraken, a la prime stablecoin pres).
# Le garde-fou s'applique donc quelle que soit la `--source` : c'est exactement le
# cas de l'incident #9 (backtest Kraken sur la periode du holdout Binance). Il
# raisonne en revanche sur les bougies REELLEMENT chargees (dates de l'index), qui
# different d'une source a l'autre.

# Journal APPEND-ONLY des contournements volontaires (--use-holdout). Le holdout
# reste utilisable en connaissance de cause, mais jamais silencieusement.
HOLDOUT_USAGE_LOG = "holdout_usage.log"

# --- Frais Kraken spot (grille A PARTIR DU 9 JUILLET 2026, palier de base) ---
# Ordres MARCHE = on PREND la liquidite => taker. Ordres LIMIT poses dans le carnet
# = on FOURNIT la liquidite => maker (moins cher). On developpe pour trader DANS LE
# FUTUR -> on prend la grille FUTURE (prudent, ne flatte pas). Avant cette date la
# grille etait taker 0.40% / maker 0.25%.
FEE_TAKER = 0.0080      # 0.80% : ordre MARCHE (le moteur simule ce comportement)
FEE_MAKER = 0.0040      # 0.40% : ordre LIMIT (a utiliser CONSCIEMMENT si on passe en maker)
# FEE = frais ACTIF du moteur. On le fait pointer sur le taker (ordres marche simules)
# pour garder toute la compatibilite existante : tout le code lit `config.FEE`.
FEE = FEE_TAKER

# Types d'ordre supportes par le paper/live. "market" = comportement historique.
ORDER_TYPES = ("market", "limit")


def fee_for_order_type(order_type: str) -> float:
    """
    SOURCE UNIQUE du couplage type d'ordre <-> taux de frais simule.

    Un ordre MARCHE prend la liquidite (taker), un ordre LIMIT postOnly la fournit
    (maker). Faire diverger les deux (passer des ordres marche en facturant du
    maker, ou l'inverse) fausserait la MESURE : c'est pour ca que ce mapping vit a
    UN seul endroit, lu par `_Trader` (paper ET live). Aucun appelant ne recopie
    la regle.

    Ne cree aucun gain : reduit un COUT d'execution, rien d'autre.
    """
    if order_type == "market":
        return FEE_TAKER
    if order_type == "limit":
        return FEE_MAKER
    raise ValueError(
        f"Type d'ordre inconnu : {order_type!r} (attendu : {' ou '.join(ORDER_TYPES)})"
    )


# --- Ordres LIMIT : attente de remplissage (borne de cadence) ---
# Un ordre limite postOnly peut ne JAMAIS etre rempli. On l'attend un temps BORNE
# puis on l'annule et on laisse le cycle suivant re-decider avec un prix frais
# (plutot que de courir apres le marche). 60 s : court devant la cadence de
# re-evaluation (>= 3600 s en 1h/1d, soit <= 1,7 % du cycle) et assez long pour
# qu'un ordre pose au toucher sur une paire majeure se remplisse s'il doit l'etre.
# L'attente effective est de toute facon bornee par `poll_seconds` (cf. _Trader).
LIMIT_ORDER_TIMEOUT_SEC = 60
LIMIT_ORDER_POLL_SEC = 5      # cadence d'interrogation de l'ordre pendant l'attente

# --- Slippage (cout d'execution defavorable) — AUDIT B6 ---
# Le prix reellement obtenu est moins bon que le prix theorique : a l'ACHAT on paie un
# peu plus cher, a la VENTE on encaisse un peu moins (carnet d'ordres, latence, impact).
# Non modelise jusqu'ici -> les resultats etaient OPTIMISTES (avantage trompeur aux
# strategies a fort turnover). 5 bps/cote (0.05%) est une hypothese prudente pour des
# majors liquides en spot ; monter a 10-15 bps en intraday ou sur paires moins liquides.
SLIPPAGE = 0.0005

# --- Gestion du risque (fractions ; None = desactive) ---
STOP_LOSS = None        # ex: 0.08 -> coupe a -8% du prix d'entree
TAKE_PROFIT = None      # ex: 0.15 -> prend le gain a +15%
TRAILING_STOP = None    # ex: 0.10 -> stop suiveur a 10% sous le plus haut atteint

# --- Dimensionnement de position ---
# None = tout-ou-rien (100%). "vol" = cible une volatilite annuelle constante :
# on investit moins quand le marche est agite, plus quand il est calme -> lisse la courbe.
POSITION_SIZING = None
TARGET_VOL = 0.50       # volatilite annuelle cible (50%) quand POSITION_SIZING="vol"
VOL_WINDOW = 20         # fenetre (en bougies) pour estimer la volatilite
MAX_FRACTION = 1.0      # part max du capital investie (1.0 = pas de levier)

# =====================================================================
# GARDE-FOUS DU TRADING REEL
# =====================================================================
MAX_TRADE_VALUE_USD = 100.0
MAX_POSITION_VALUE_USD = 500.0
MIN_TRADE_INTERVAL_SEC = 3600

VERIFY_SSL = True

# Robustesse SSL : si un antivirus/proxy intercepte le HTTPS (MITM legitime, ex. Avast),
# le certificat est re-signe par une CA locale absente du bundle certifi. truststore fait
# utiliser le magasin de certificats de l'OS (qui contient cette CA) -- SANS desactiver la
# verification. Centralise ici (politique SSL unique). Absent => comportement par defaut.
if VERIFY_SSL:
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
