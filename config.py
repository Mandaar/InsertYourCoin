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
