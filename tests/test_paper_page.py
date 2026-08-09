"""
Tests de trading/paper_page.py (Lot 7, ecran /paper) -- fonctions PURES,
aucun serveur ni reseau. Les routes HTTP (spawn/pid/CSRF) sont testees dans
tests/test_monitor_server.py (integration, comme les autres ecrans).
"""
import config
from trading import paper_page as pp
from trading.strategies import STRATEGIES


# --------------------------------------------------------------------------- #
#  parse_paper_params -- validation, tolerance, defauts                       #
# --------------------------------------------------------------------------- #
def test_parse_paper_params_valeurs_par_defaut_completes():
    params, errors = pp.parse_paper_params({
        "strategy": "sma", "timeframe": "5m",
        "stop_loss": "5", "take_profit": "10", "trailing_stop": "8",
        "position_sizing": "none",
    })
    assert errors == []
    assert params["strategy"] == "sma"
    assert params["symbol"] == config.DEFAULT_SYMBOL
    assert params["timeframe"] == "5m"
    assert params["stop_loss"] == 5.0
    assert params["take_profit"] == 10.0
    assert params["trailing_stop"] == 8.0
    assert params["position_sizing"] == "none"
    assert params["target_vol"] is None


def test_parse_paper_params_symbole_vide_retombe_sur_defaut():
    params, errors = pp.parse_paper_params({"strategy": "sma", "symbol": "  "})
    assert errors == []
    assert params["symbol"] == config.DEFAULT_SYMBOL


def test_parse_paper_params_strategie_inconnue_rejetee():
    params, errors = pp.parse_paper_params({"strategy": "n-existe-pas"})
    assert params is None
    assert any("Stratégie inconnue" in e for e in errors)


def test_parse_paper_params_timeframe_invalide_rejete():
    params, errors = pp.parse_paper_params({"strategy": "sma", "timeframe": "3s"})
    assert params is None
    assert any("Timeframe non supporté" in e for e in errors)


def test_parse_paper_params_aucun_champ_source_jamais_construit():
    # Garde-fou spec §4.9 : le paper est TOUJOURS Kraken, aucun champ `source`
    # n'existe dans le formulaire -- meme si le POST en fournit un, il est
    # ignore (pas de cle "source" dans les params retournes).
    params, errors = pp.parse_paper_params({"strategy": "sma", "source": "binance"})
    assert errors == []
    assert "source" not in params


def test_parse_paper_params_champs_risque_tolerants_texte_invalide():
    params, errors = pp.parse_paper_params({
        "strategy": "sma", "stop_loss": "pas-un-nombre",
    })
    assert errors == []
    assert params["stop_loss"] is None  # tolerant, pas d'erreur bloquante


def test_parse_paper_params_sizing_vol_avec_target_vol():
    params, errors = pp.parse_paper_params({
        "strategy": "tsmom", "position_sizing": "vol", "target_vol": "40",
    })
    assert errors == []
    assert params["position_sizing"] == "vol"
    assert params["target_vol"] == 40.0


def test_parse_paper_params_toutes_les_strategies_du_registre_acceptees():
    for key in STRATEGIES:
        params, errors = pp.parse_paper_params({"strategy": key})
        assert errors == [], f"{key} devrait etre accepte"
        assert params["strategy"] == key


# --------------------------------------------------------------------------- #
#  compute_paper_status -- fonction pure, aucune I/O                          #
# --------------------------------------------------------------------------- #
def test_compute_paper_status_arrete():
    status = pp.compute_paper_status(False, None)
    assert status == {"running": False, "since": None}


def test_compute_paper_status_en_cours_avec_horodatage():
    status = pp.compute_paper_status(True, 1750000000.0)
    assert status["running"] is True
    assert status["since"] is not None
    assert "-" in status["since"]  # format YYYY-MM-DD HH:MM


def test_compute_paper_status_en_cours_sans_start_ts_reste_coherent():
    status = pp.compute_paper_status(True, None)
    assert status["running"] is True
    assert status["since"] is None


# --------------------------------------------------------------------------- #
#  render_paper_page -- rendu HTML (fonction pure)                            #
# --------------------------------------------------------------------------- #
def test_render_paper_page_arrete_affiche_formulaire_complet():
    status = pp.compute_paper_status(False, None)
    html = pp.render_paper_page(status, "TOKEN123")
    assert "ARRÊTÉ" in html
    assert "name='csrf_token'" in html
    assert "value='TOKEN123'" in html
    assert "name='strategy'" in html
    assert "name='symbol'" in html
    assert "name='timeframe'" in html
    assert "name='stop_loss'" in html
    assert "name='take_profit'" in html
    assert "name='trailing_stop'" in html
    assert "name='position_sizing'" in html
    assert "Démarrer le paper trading" in html
    assert "name='source'" not in html          # jamais de champ source (paper = Kraken only)
    assert "type='password'" not in html         # aucune cle requise


def test_render_paper_page_en_cours_affiche_statut_et_bouton_arreter():
    status = pp.compute_paper_status(True, 1750000000.0)
    html = pp.render_paper_page(status, "TOKEN123")
    assert "EN COURS" in html
    assert "depuis" in html
    assert "Arrêter" in html
    assert "/monitoring" in html
    assert "Démarrer le paper trading" not in html  # pas de formulaire de config pendant l'execution


def test_render_paper_page_erreurs_affichees():
    status = pp.compute_paper_status(False, None)
    html = pp.render_paper_page(status, "T", errors=["Stratégie inconnue : xx."])
    assert "Stratégie inconnue" in html


def test_render_paper_page_message_confirmation():
    status = pp.compute_paper_status(False, None)
    html = pp.render_paper_page(status, "T", message="Paper trading arrete.")
    assert "Paper trading arrete." in html


def test_render_paper_page_alerte_inactivite_si_en_cours_et_inactif():
    status = pp.compute_paper_status(True, 1750000000.0)
    html = pp.render_paper_page(status, "T", inactif=True, age_seconds=725)
    assert "725" in html
    assert "inactif" in html.lower()


def test_render_paper_page_re_remplit_formulaire_apres_erreur():
    status = pp.compute_paper_status(False, None)
    html = pp.render_paper_page(
        status, "T",
        errors=["Timeframe non supporté : 3s (attendu : 1m, 5m, 15m, 1h, 4h, 1d)."],
        values={"strategy": "rsi", "symbol": "BTC/USD", "timeframe": "3s"},
    )
    assert "value='BTC/USD'" in html
    assert "<option value='rsi' selected>" in html


# --------------------------------------------------------------------------- #
#  paper_control_disabled -- parsing pur de IYC_DISABLE_PAPER_CONTROL         #
#  (deploiement Docker multi-conteneurs, docs/DEPLOY_DOCKER.md §7)            #
# --------------------------------------------------------------------------- #
def test_paper_control_disabled_absent_ou_vide_est_false():
    assert pp.paper_control_disabled(None) is False
    assert pp.paper_control_disabled("") is False
    assert pp.paper_control_disabled("   ") is False


def test_paper_control_disabled_valeurs_vraies_insensibles_a_la_casse():
    for val in ("1", "true", "True", "TRUE", "yes", "Yes", "  yes  "):
        assert pp.paper_control_disabled(val) is True, val


def test_paper_control_disabled_valeurs_fausses():
    for val in ("0", "false", "no", "n-importe-quoi", "2"):
        assert pp.paper_control_disabled(val) is False, val


# --------------------------------------------------------------------------- #
#  render_paper_page(control_disabled=True) -- formulaire/bouton RETIRES,     #
#  encart affiche, statut consultable en lecture seule (§7)                   #
# --------------------------------------------------------------------------- #
def test_render_paper_page_disabled_arrete_aucun_formulaire_mais_encart():
    status = pp.compute_paper_status(False, None)
    html = pp.render_paper_page(status, "T", control_disabled=True)
    assert "ARRÊTÉ" in html                       # statut reste consultable
    assert "Démarrer le paper trading" not in html
    assert "name='strategy'" not in html
    assert "Pilotage désactivé" in html
    assert "docker compose" in html


def test_render_paper_page_disabled_en_cours_aucun_bouton_arreter_mais_encart():
    status = pp.compute_paper_status(True, 1750000000.0)
    html = pp.render_paper_page(status, "T", control_disabled=True)
    assert "EN COURS" in html                     # statut reste consultable
    assert "Arrêter</button>" not in html
    assert "Pilotage désactivé" in html


def test_render_paper_page_disabled_false_par_defaut_comportement_lot7_inchange():
    # Non-regression explicite : sans l'argument, le rendu est identique a
    # avant l'introduction du flag.
    status = pp.compute_paper_status(False, None)
    html = pp.render_paper_page(status, "T")
    assert "Démarrer le paper trading" in html
    assert "Pilotage désactivé" not in html
