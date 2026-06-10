"""
Tests de la page Options et de ses fonctions PURES.

Aucun reseau, aucune cle API reelle, AUCUN serveur instancie : on teste les
fonctions pures (options.py + rendu/securite de monitor.py) via tmp_path, et les
niveaux de logs via un PaperTrader factice (meme approche que test_resilience.py).

SECURITE : plusieurs tests verifient explicitement qu'une valeur de cle
n'apparait jamais dans le HTML rendu, et qu'un POST sans token CSRF est rejete.
"""
import json

import pytest

from trading.options import (
    read_options, write_options, update_env_file, keys_configured,
    OPTIONS_PATH, LOG_LEVELS,
)
from trading.monitor import render_options_page, csrf_valid, host_allowed
from trading.paper_trader import PaperTrader
from trading.strategies import build_strategy


# --------------------------------------------------------------------------- #
#  FakeExchange minimal (aucun reseau)                                         #
# --------------------------------------------------------------------------- #
class FakeExchange:
    def fetch_ohlcv(self, symbol, timeframe, limit=200):
        return None

    def fetch_price(self, symbol):
        return 100.0

    def fetch_balance(self):
        return {}


# --------------------------------------------------------------------------- #
#  read_options / write_options                                                #
# --------------------------------------------------------------------------- #
def test_read_options_default_when_missing(tmp_path):
    out = read_options(tmp_path / "nope.json")
    assert out == {"log_level": "moyen"}


def test_read_options_default_when_corrupt(tmp_path):
    p = tmp_path / "options.json"
    p.write_text("{ pas du json", encoding="utf-8")
    assert read_options(p) == {"log_level": "moyen"}


def test_read_options_invalid_level_falls_back(tmp_path):
    p = tmp_path / "options.json"
    p.write_text(json.dumps({"log_level": "n_importe_quoi"}), encoding="utf-8")
    assert read_options(p)["log_level"] == "moyen"


def test_write_then_read_roundtrip(tmp_path):
    p = tmp_path / "options.json"
    write_options({"log_level": "complet"}, p)
    assert read_options(p)["log_level"] == "complet"


def test_write_options_rejects_invalid_level(tmp_path):
    p = tmp_path / "options.json"
    with pytest.raises(ValueError):
        write_options({"log_level": "ultra"}, p)
    # Rien ne doit avoir ete ecrit.
    assert not p.exists()


def test_write_options_all_valid_levels(tmp_path):
    for lvl in LOG_LEVELS:
        p = tmp_path / f"opt_{lvl}.json"
        write_options({"log_level": lvl}, p)
        assert read_options(p)["log_level"] == lvl


def test_options_path_is_under_project_root():
    # OPTIONS_PATH() pointe vers <racine>/options.json (resolu en absolu).
    assert OPTIONS_PATH().name == "options.json"
    assert OPTIONS_PATH().is_absolute()


# --------------------------------------------------------------------------- #
#  update_env_file : creation, preservation, remplacement, anti-injection      #
# --------------------------------------------------------------------------- #
def test_update_env_creates_file(tmp_path):
    env = tmp_path / ".env"
    update_env_file({"KRAKEN_API_KEY": "AAA", "KRAKEN_API_SECRET": "BBB"}, env)
    text = env.read_text(encoding="utf-8")
    assert "KRAKEN_API_KEY=AAA" in text
    assert "KRAKEN_API_SECRET=BBB" in text


def test_update_env_preserves_foreign_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# mon commentaire\n"
        "AUTRE_VAR=valeur_a_garder\n"
        "KRAKEN_API_KEY=ancienne\n",
        encoding="utf-8",
    )
    update_env_file({"KRAKEN_API_KEY": "nouvelle"}, env)
    text = env.read_text(encoding="utf-8")
    assert "# mon commentaire" in text          # commentaire preserve
    assert "AUTRE_VAR=valeur_a_garder" in text  # variable etrangere preservee
    assert "KRAKEN_API_KEY=nouvelle" in text    # cle remplacee
    assert "ancienne" not in text               # ancienne valeur ecrasee


def test_update_env_replaces_existing_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("KRAKEN_API_KEY=old1\nKRAKEN_API_SECRET=old2\n", encoding="utf-8")
    update_env_file({"KRAKEN_API_KEY": "new1", "KRAKEN_API_SECRET": "new2"}, env)
    text = env.read_text(encoding="utf-8")
    assert "KRAKEN_API_KEY=new1" in text
    assert "KRAKEN_API_SECRET=new2" in text
    # Pas de doublon de la cle (remplacee sur place, pas appendue).
    assert text.count("KRAKEN_API_KEY=") == 1


def test_update_env_appends_missing_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AUTRE=x\n", encoding="utf-8")
    update_env_file({"KRAKEN_API_KEY": "AAA"}, env)
    text = env.read_text(encoding="utf-8")
    assert "AUTRE=x" in text
    assert "KRAKEN_API_KEY=AAA" in text


def test_update_env_refuses_newline_value(tmp_path):
    env = tmp_path / ".env"
    with pytest.raises(ValueError):
        update_env_file({"KRAKEN_API_KEY": "abc\nINJECTED=evil"}, env)
    # Le fichier ne doit pas avoir ete cree/modifie avec l'injection.
    assert not env.exists()


def test_update_env_refuses_carriage_return_value(tmp_path):
    env = tmp_path / ".env"
    with pytest.raises(ValueError):
        update_env_file({"KRAKEN_API_KEY": "abc\rdef"}, env)


# --------------------------------------------------------------------------- #
#  keys_configured                                                             #
# --------------------------------------------------------------------------- #
def test_keys_configured_false_when_absent(tmp_path):
    assert keys_configured(tmp_path / "nope.env") is False


def test_keys_configured_false_when_empty_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("KRAKEN_API_KEY=\nKRAKEN_API_SECRET=\n", encoding="utf-8")
    assert keys_configured(env) is False


def test_keys_configured_false_when_one_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("KRAKEN_API_KEY=AAA\n", encoding="utf-8")
    assert keys_configured(env) is False


def test_keys_configured_true_when_both_present(tmp_path):
    env = tmp_path / ".env"
    env.write_text("KRAKEN_API_KEY=AAA\nKRAKEN_API_SECRET=BBB\n", encoding="utf-8")
    assert keys_configured(env) is True


# --------------------------------------------------------------------------- #
#  Niveaux de logs dans le paper (via _trace + _log_status reels)             #
# --------------------------------------------------------------------------- #
def _make_paper(tmp_path, level):
    """PaperTrader factice avec un niveau de logs force (comme run() le ferait)."""
    log = tmp_path / "p.log"
    pt = PaperTrader(
        FakeExchange(), build_strategy("sma"),
        state_file=str(tmp_path / "state.json"),
        stats_file=str(tmp_path / "stats.csv"),
        log_file=str(log),
    )
    pt._log_level = level
    return pt, log


def test_log_level_leger_omits_status_line(tmp_path):
    pt, log = _make_paper(tmp_path, "leger")
    pt._log_status(100.0)               # ligne de STATUT (niveau moyen)
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "portefeuille" not in text   # le statut ne doit PAS etre ecrit en leger


def test_log_level_moyen_writes_status_line(tmp_path):
    pt, log = _make_paper(tmp_path, "moyen")
    pt._log_status(100.0)
    text = log.read_text(encoding="utf-8")
    assert "portefeuille" in text       # statut present au niveau moyen (defaut)


def test_log_level_moyen_omits_detail_line(tmp_path):
    pt, log = _make_paper(tmp_path, "moyen")
    pt._trace_cycle_detail(signal=1, desired=1, fraction=0.5, reason=None)
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "detail cycle" not in text   # le detail n'apparait qu'en complet


def test_log_level_complet_writes_detail_line(tmp_path):
    pt, log = _make_paper(tmp_path, "complet")
    pt._trace_cycle_detail(signal=1, desired=0, fraction=0.5, reason="STOP-LOSS")
    text = log.read_text(encoding="utf-8")
    assert "detail cycle" in text
    assert "risk-overlay=STOP-LOSS" in text  # motif risk-overlay present


def test_log_errors_written_at_all_levels(tmp_path):
    # Une erreur (level="leger") doit etre ecrite quel que soit le niveau actif.
    for lvl in LOG_LEVELS:
        sub = tmp_path / lvl
        sub.mkdir()
        pt, log = _make_paper(sub, lvl)
        pt._trace(f"Erreur cycle [reseau] {lvl}", level="leger")
        text = log.read_text(encoding="utf-8")
        assert f"Erreur cycle [reseau] {lvl}" in text


# --------------------------------------------------------------------------- #
#  Rendu de la page Options : jamais de valeur de cle, lien wallet, token      #
# --------------------------------------------------------------------------- #
def test_options_page_never_contains_key_value():
    # Meme si les cles sont configurees (keys_ok=True), la page n'affiche QUE
    # l'etat booleen, jamais une valeur. La fonction de rendu ne recoit d'ailleurs
    # aucune valeur de cle en argument (par conception) : on verifie qu'elle ne
    # fuit pas le token CSRF dans un champ de cle non plus.
    page = render_options_page("moyen", keys_ok=True, csrf_token="TOK123")
    # Les champs de cle sont de type password et VIDES (placeholder seulement,
    # jamais d'attribut value rempli).
    assert "type='password'" in page
    assert "name='api_key'" in page
    assert "name='api_secret'" in page
    # Le token CSRF doit n'apparaitre QUE dans le champ cache dedie, jamais dans
    # un champ password : on verifie qu'aucun input password ne porte de value.
    import re
    for m in re.finditer(r"<input[^>]*type='password'[^>]*>", page):
        assert "value=" not in m.group(0)
    assert "OUI" in page                  # etat keys_ok=True affiche en clair (booleen)


def test_options_page_contains_withdraw_link():
    page = render_options_page("moyen", keys_ok=False, csrf_token="TOK")
    assert "kraken.com/u/funding/withdraw" in page
    assert "rel='noopener'" in page or 'rel="noopener"' in page


def test_options_page_contains_csrf_token():
    page = render_options_page("moyen", keys_ok=False, csrf_token="ABC123XYZ")
    assert "ABC123XYZ" in page
    assert "name='csrf_token'" in page or 'name="csrf_token"' in page


def test_options_page_marks_active_level():
    page = render_options_page("complet", keys_ok=False, csrf_token="T")
    # Le radio "complet" doit etre coche, pas les autres.
    assert "value='complet' checked" in page
    assert "value='leger' checked" not in page


def test_options_page_warns_no_withdraw_permission():
    page = render_options_page("moyen", keys_ok=False, csrf_token="T")
    assert "Query Funds" in page
    assert "Withdraw Funds" in page       # mentionne pour dire de NE PAS l'activer


def test_options_page_saved_banner():
    page = render_options_page("moyen", keys_ok=False, csrf_token="T", saved=True)
    assert "enregistrees" in page.lower()


# --------------------------------------------------------------------------- #
#  Securite : verification CSRF et Host (fonctions pures)                      #
# --------------------------------------------------------------------------- #
def test_csrf_valid_accepts_matching_token():
    assert csrf_valid("abc", "abc") is True


def test_csrf_valid_rejects_mismatch():
    assert csrf_valid("abc", "xyz") is False


def test_csrf_valid_rejects_empty():
    assert csrf_valid("", "abc") is False
    assert csrf_valid("abc", "") is False
    assert csrf_valid(None, "abc") is False


def test_host_allowed_accepts_loopback():
    assert host_allowed("127.0.0.1:8765", 8765) is True
    assert host_allowed("localhost:8765", 8765) is True
    assert host_allowed("127.0.0.1", 8765) is True


def test_host_allowed_rejects_foreign_host():
    assert host_allowed("evil.example.com", 8765) is False
    assert host_allowed("attacker.com:8765", 8765) is False
    assert host_allowed("", 8765) is False
    assert host_allowed(None, 8765) is False
