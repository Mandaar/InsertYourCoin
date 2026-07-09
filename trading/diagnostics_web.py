"""
Pont web <-> diagnostic CLI (Lot 1, ecran /check + carte Accueil).

Reutilise EXACTEMENT la logique de main.py (diagnose_error, truststore_active,
diagnostic_static_lines) au lieu de la reecrire. Import PARESSEUX de `main`
(a l'interieur des fonctions) : main.py est l'entree CLI qui importe trading.*
au chargement -- un import top-level de `main` depuis trading/ risquerait un
cycle a l'execution `python main.py monitor`. En paresseux, aucun probleme :
au moment ou une route HTTP s'execute, `main` est deja pleinement charge
(process CLI) ou trivialement importable (tests, `import main` direct comme
tests/test_healthcheck.py le fait deja).

STDLIB uniquement. Ne touche jamais aux cles (aucune valeur ne transite ici).
"""
import datetime as dt


def truststore_active() -> bool:
    """Vrai si truststore est installe/importable. Aucun appel reseau."""
    import main
    return main.truststore_active()


def static_diagnostic_lines() -> list:
    """Versions installees + etat truststore. Aucun appel reseau (cf. spec
    §4.2 : l'etat initial de /check ne doit jamais interroger Kraken seul)."""
    import main
    return main.diagnostic_static_lines()


def run_web_check(symbol) -> dict:
    """
    Execute le VRAI test de connexion Kraken : UN appel reseau, lecture seule
    (fetch_price). Classe le resultat avec main.diagnose_error (memes
    categories/messages que la CLI `check`). Ne leve jamais.

    Retourne un dict : {ok, category, message, price, symbol, time}.
    `category` est None si ok=True, sinon "ssl" | "network" (cf. diagnose_error).
    """
    import main
    from trading.exchange import KrakenExchange

    now_str = dt.datetime.now().strftime("%H:%M:%S")
    exchange = KrakenExchange()
    try:
        price = exchange.fetch_price(symbol)
        return {"ok": True, "category": None, "message": None,
                "price": price, "symbol": symbol, "time": now_str}
    except Exception as exc:  # noqa: BLE001 -- classee par diagnose_error, jamais de crash
        category, message = main.diagnose_error(exc)
        return {"ok": False, "category": category, "message": message,
                "price": None, "symbol": symbol, "time": now_str}
