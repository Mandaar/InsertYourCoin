"""
Routes GET /export/* (demande user 2026-08-20 : telecharger les donnees du
paper depuis l'interface, "pas besoin d'ouvrir la consol").

Contrat teste :
- la table nom -> chemin est FIXE et fermee : seul un des 3 noms publics est
  servi, tout le reste (y compris une tentative de traversal) -> 404 ;
- le fichier est servi en attachment, bon type MIME, contenu BYTE-EXACT du
  fichier que le monitor lit deja (--stats/--log/--state) ;
- fichier pas encore produit par le paper -> 404 explicite, jamais un 500 ;
- la page /monitoring (branche avec donnees) porte la carte Export (3 liens)
  et l'etiquette honnete "Drawdown (session)" (le pic repart de zero a chaque
  restart du paper -- constat serveur du 2026-08-20 : -5.08% affiche pour un
  P&L de -35.30% depuis le depart).
"""
import threading
import urllib.request
import urllib.error

import pytest

import trading.monitor as mon
from tests.test_monitor_server import _teardown_server


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.options.OPTIONS_PATH",
                        lambda: tmp_path / "options.json")
    srv = mon.build_monitor_server(port=0,
                                   stats_path=tmp_path / "s.csv",
                                   log_path=tmp_path / "l.log",
                                   state_path=tmp_path / "st.json")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    finally:
        _teardown_server(srv)


def _get_full(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, dict(r.headers), r.read()


CSV = """ts,equity
1,10000
2,9990
"""


def test_export_stats_csv_sert_le_fichier_en_attachment(server):
    base, tmp = server
    (tmp / "s.csv").write_text(CSV, encoding="utf-8")
    code, headers, body = _get_full(base + "/export/stats.csv")
    assert code == 200
    # Byte-exact contre le DISQUE (write_text peut traduire les fins de ligne
    # sous Windows -- le contrat du serveur est de servir le fichier tel quel).
    assert body == (tmp / "s.csv").read_bytes(), "contenu servi != fichier disque"
    assert "text/csv" in headers.get("Content-Type", "")
    assert 'attachment; filename="paper_stats.csv"' in headers.get(
        "Content-Disposition", "")


def test_export_trades_log_et_state_json(server):
    base, tmp = server
    (tmp / "l.log").write_text("[t] BUY 100", encoding="utf-8")
    (tmp / "st.json").write_text('{"entry_price": 100}', encoding="utf-8")
    code_l, h_l, body_l = _get_full(base + "/export/trades.log")
    code_s, h_s, body_s = _get_full(base + "/export/state.json")
    assert (code_l, code_s) == (200, 200)
    assert b"BUY 100" in body_l and b"entry_price" in body_s
    assert "text/plain" in h_l.get("Content-Type", "")
    assert "application/json" in h_s.get("Content-Type", "")


def test_export_fichier_absent_404_jamais_500(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _get_full(base + "/export/stats.csv")
    assert e.value.code == 404


def test_export_nom_inconnu_et_traversal_404(server):
    base, tmp = server
    (tmp / "s.csv").write_text("x", encoding="utf-8")
    for mauvais in ("config.py", "..%2Fconfig.py", "../.env", "stats.csv/../l.log"):
        with pytest.raises(urllib.error.HTTPError) as e:
            _get_full(base + "/export/" + mauvais)
        assert e.value.code == 404, f"'{mauvais}' aurait du faire 404"


def test_page_monitoring_porte_la_carte_export_et_le_label_session(server):
    base, tmp = server
    from trading.stats import StatsRecorder
    rec = StatsRecorder(str(tmp / "s.csv"))
    rec.record({"time": "2022-01-01 00:00:00", "hour": 0, "weekday": 0,
                "equity": 100.0, "exposure": 0.0, "price": 10.0,
                "action": "", "pnl": 0.0, "fee_paid": 0.0})
    code, _, body = _get_full(base + "/monitoring")
    page = body.decode("utf-8")
    assert code == 200
    for lien in ("/export/stats.csv", "/export/trades.log", "/export/state.json"):
        assert lien in page, f"lien {lien} absent de la page monitoring"
    assert "Drawdown (session)" in page, (
        "l'etiquette doit dire que le drawdown est intra-session")
