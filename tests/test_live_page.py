"""
Tests PURS du Lot 8 (Live verrouille) -- rendu et parsing, sans reseau ni
serveur, cf. docs/design/LOT8_LIVE_SPEC.md §5.1.

Couvre : radio dry-run par defaut, plafonds affiches, aucune cle jamais
affichee, verrouillage du reel quand un pre-requis manque, resolve_execute,
phrase_ok, build_live_command (jamais de plafond en argument, jamais de cle).
"""
import config
from trading.live_control import (
    build_live_command, check_prerequisites_a, phrase_ok, resolve_execute,
)
from trading.live_page import render_live_wall

_ROOT = __import__("pathlib").Path("C:/fake/root")


def _prereq_ok():
    return check_prerequisites_a(True, True, True)


def _prereq_missing_all():
    return check_prerequisites_a(False, False, False)


def test_live_page_dry_run_selectionne_par_defaut():
    out = render_live_wall(_prereq_ok(), True, True, True, "tok123")
    assert "name='mode_display' value='dry' checked" in out
    assert "name='mode_display' value='reel' checked" not in out


def test_live_page_affiche_les_plafonds_config():
    out = render_live_wall(_prereq_ok(), True, True, True, "tok123")
    assert f"{config.MAX_TRADE_VALUE_USD:g}" in out
    assert f"{config.MAX_POSITION_VALUE_USD:g}" in out
    assert f"{config.MIN_TRADE_INTERVAL_SEC:g}" in out


def test_live_page_ne_contient_jamais_de_cle():
    # `render_live_wall` ne recoit JAMAIS de valeur de cle en parametre --
    # seuls des booleens (keys_ok) lui parviennent. On verifie qu'aucun
    # secret plausible ne fuit meme en variant keys_ok=True/False.
    fake_secret = "sk_live_SUPER_SECRET_KRAKEN_TOKEN_1234567890"
    out_true = render_live_wall(_prereq_ok(), True, True, True, "tok123")
    out_false = render_live_wall(_prereq_missing_all(), False, False, False, "tok123")
    assert fake_secret not in out_true
    assert fake_secret not in out_false
    assert "KRAKEN_API_KEY" not in out_true
    assert "KRAKEN_API_SECRET" not in out_true


def test_live_page_reel_verrouille_si_prerequis_manquant():
    prereq_missing = check_prerequisites_a(False, True, True)  # cles manquantes
    out = render_live_wall(prereq_missing, False, True, True, "tok123")
    # Le bouton "Continuer en RÉEL" est DESACTIVE cote serveur (le VRAI
    # verrou vit dans la route /live/arm -- ceci n'est qu'un reflet honnete
    # de l'etat calcule serveur, N1 : la vraie garde n'est jamais QUE cote
    # client).
    assert "Continuer en RÉEL</button>" in out
    reel_btn_idx = out.index("Continuer en RÉEL</button>")
    btn_open = out.rindex("<button", 0, reel_btn_idx)
    assert "disabled" in out[btn_open:reel_btn_idx]
    assert "manquant" in out  # au moins un pre-requis affiche "manquant"

    prereq_full = _prereq_ok()
    out_ok = render_live_wall(prereq_full, True, True, True, "tok123")
    # Quand tout est ok, le bouton reel n'est PAS desactive.
    assert "Continuer en RÉEL</button>" in out_ok
    reel_btn_idx = out_ok.index("Continuer en RÉEL</button>")
    btn_open = out_ok.rindex("<button", 0, reel_btn_idx)
    assert "disabled" not in out_ok[btn_open:reel_btn_idx]


def test_resolve_execute_defaut_dry_run():
    assert resolve_execute({"mode": "reel"}) is True
    assert resolve_execute({"mode": "dry"}) is False
    assert resolve_execute({}) is False
    assert resolve_execute({"mode": "REEL"}) is True  # insensible a la casse cote saisie
    assert resolve_execute({"mode": "n_importe_quoi"}) is False


def test_phrase_exacte_requise():
    assert phrase_ok("OUI JE CONFIRME") is True
    assert phrase_ok("  OUI JE CONFIRME  ") is True  # strip() externe tolere
    assert phrase_ok("oui je confirme") is False
    assert phrase_ok("OUI") is False
    assert phrase_ok("") is False
    assert phrase_ok(None) is False
    assert phrase_ok("OUI  JE CONFIRME") is False  # double espace interne = pas exact


def test_build_live_command_reel_a_execute_sans_override_plafond():
    params = {"strategy": "sma", "symbol": "ETH/USD", "timeframe": "1h"}
    cmd_reel = build_live_command(_ROOT, params, execute=True)
    assert "live" in cmd_reel
    assert "--execute" in cmd_reel
    assert not any("--max-trade-value" in str(t) for t in cmd_reel)
    assert not any("--max-position" in str(t) for t in cmd_reel)
    assert not any("--min-trade-interval" in str(t) for t in cmd_reel)

    cmd_dry = build_live_command(_ROOT, params, execute=False)
    assert "live" in cmd_dry
    assert "--execute" not in cmd_dry


def test_build_live_command_ne_contient_jamais_de_cle():
    params = {"strategy": "sma", "symbol": "ETH/USD", "timeframe": "1h"}
    cmd = build_live_command(_ROOT, params, execute=True)
    joined = " ".join(str(t) for t in cmd).lower()
    assert "kraken_api_key" not in joined
    assert "kraken_api_secret" not in joined
    assert "--api-key" not in joined
    assert "--api-secret" not in joined
