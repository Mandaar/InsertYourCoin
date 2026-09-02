"""
Tests du LOT B : hygiene de mesure.

1. `paper --reset` ARCHIVE (jamais n'ecrase, jamais ne supprime) puis recree un
   etat neuf au capital initial.
2. `stats --since/--until` filtre le CSV sur la colonne `time`, bornes incluses,
   fenetre vide toleree, et le resume DIT sur quelle fenetre il porte.

Aucun reseau, aucune cle API : tout passe par tmp_path.
"""
import datetime as dt
import json

import pandas as pd
import pytest

import config
import main
from trading import reset as reset_mod
from trading.paper_trader import PaperTrader, fresh_state
from trading.stats import (filter_period, format_summary, parse_bound, summarize)
from trading.strategies import build_strategy


WHEN = dt.datetime(2026, 9, 1, 14, 30, 0)


def _seed(tmp_path, state_text="{\"cash\": 1.0}", stats_text="time,equity\nt,1\n"):
    st = tmp_path / "paper_state.json"
    cs = tmp_path / "paper_stats.csv"
    st.write_text(state_text)
    cs.write_text(stats_text)
    return st, cs


# --------------------------------------------------------------------------- #
#  1. --reset : ARCHIVE, ne detruit rien                                       #
# --------------------------------------------------------------------------- #
def test_reset_archive_les_deux_fichiers_sous_un_nom_horodate(tmp_path):
    st, cs = _seed(tmp_path)
    old_state, old_stats = st.read_text(), cs.read_text()

    res = reset_mod.reset_paper(st, cs, when=WHEN)

    a_state = tmp_path / "paper_state.2026-09-01T14-30-00.json"
    a_stats = tmp_path / "paper_stats.2026-09-01T14-30-00.csv"
    assert a_state.exists() and a_stats.exists()          # les anciens EXISTENT ENCORE
    assert a_state.read_text() == old_state               # ... contenu intact
    assert a_stats.read_text() == old_stats
    assert [d for _s, d in res["archived"]] == [a_state, a_stats]
    # le CSV de stats a bien ete deplace (repart vide), pas duplique
    assert not cs.exists()


def test_reset_produit_un_etat_neuf_au_capital_initial(tmp_path):
    st, cs = _seed(tmp_path)
    reset_mod.reset_paper(st, cs, when=WHEN)

    state = json.loads(st.read_text())
    assert state == fresh_state(config.INITIAL_CAPITAL)
    assert state["cash"] == config.INITIAL_CAPITAL
    assert state["invested"] is False and state["base_amount"] == 0.0
    assert state["trades"] == []


def test_letat_neuf_est_relu_tel_quel_par_le_papertrader(tmp_path):
    """Le schema ecrit par le reset est bien celui qu'attend le trader."""
    st, cs = _seed(tmp_path)
    reset_mod.reset_paper(st, cs, when=WHEN)
    pt = PaperTrader(object(), build_strategy("sma"), state_file=st,
                     stats_file=None, log_file=None)
    assert pt.state["cash"] == config.INITIAL_CAPITAL
    assert pt._units() == 0.0 and pt._entry_price() is None


def test_reset_n_ecrase_jamais_une_archive_existante(tmp_path):
    st, cs = _seed(tmp_path)
    deja = tmp_path / "paper_state.2026-09-01T14-30-00.json"
    deja.write_text("ARCHIVE PRECEDENTE")

    reset_mod.reset_paper(st, cs, when=WHEN)

    assert deja.read_text() == "ARCHIVE PRECEDENTE"       # INTACTE
    assert (tmp_path / "paper_state.2026-09-01T14-30-00-2.json").exists()


def test_reset_sans_fichier_existant_ne_plante_pas(tmp_path):
    res = reset_mod.reset_paper(tmp_path / "s.json", tmp_path / "s.csv", when=WHEN)
    assert res["archived"] == []
    assert json.loads((tmp_path / "s.json").read_text())["cash"] == config.INITIAL_CAPITAL


def test_archive_name_est_pure_et_ne_touche_pas_au_disque(tmp_path):
    p = tmp_path / "paper_stats.csv"
    name = reset_mod.archive_name(p, when=WHEN)
    assert name.name == "paper_stats.2026-09-01T14-30-00.csv"
    assert not name.exists() and not p.exists()          # aucune I/O
    assert ":" not in name.name                          # nom valide sous Windows


def test_cli_paper_reset_absent_par_defaut():
    """NON-REGRESSION : sans --reset, rien n'est archive ni reinitialise."""
    args = main.build_parser().parse_args(["paper"])
    assert args.reset is False
    assert args.state == "paper_state.json" and args.stats == "paper_stats.csv"


def test_cmd_paper_reset_archive_avant_de_lancer_la_boucle(tmp_path, monkeypatch):
    """Chemin REEL du CLI (pas seulement la fonction) : --reset archive, puis
    le trader est construit sur l'etat neuf."""
    st, cs = _seed(tmp_path)
    built = {}

    class _FakePaper:
        def __init__(self, *a, **kw):
            built.update(kw)

        def run(self):
            built["ran"] = True

    monkeypatch.setattr("trading.paper_trader.PaperTrader", _FakePaper)
    monkeypatch.setattr(main, "KrakenExchange", lambda *a, **k: object())
    args = main.build_parser().parse_args(
        ["paper", "--reset", "--state", str(st), "--stats", str(cs)])
    main.cmd_paper(args)

    assert built["ran"] is True
    assert json.loads(st.read_text())["cash"] == config.INITIAL_CAPITAL
    assert len(list(tmp_path.glob("paper_state.*.json"))) == 1   # l'archive existe
    assert built["order_type"] == "market"                       # defaut inchange


# --------------------------------------------------------------------------- #
#  2. stats --since / --until                                                  #
# --------------------------------------------------------------------------- #
def _df():
    times = ["2026-08-19 23:59:59", "2026-08-20 00:00:00", "2026-08-20 12:00:00",
             "2026-08-21 00:00:00", "2026-08-22 08:00:00"]
    return pd.DataFrame({"time": times,
                         "equity": [100.0, 101.0, 102.0, 103.0, 104.0],
                         "action": ["hold"] * 5,
                         "fee_paid": [0.0] * 5,
                         "exposure": [0.0] * 5,
                         "hour": [0, 0, 12, 0, 8],
                         "weekday": [2, 3, 3, 4, 5]})


def test_parse_bound_accepte_les_deux_formats():
    assert parse_bound("2026-08-20") == pd.Timestamp("2026-08-20 00:00:00")
    assert parse_bound("2026-08-20 12:34:56") == pd.Timestamp("2026-08-20 12:34:56")
    assert parse_bound(None) is None and parse_bound("  ") is None
    with pytest.raises(ValueError):
        parse_bound("20/08/2026")


def test_since_est_inclusif_a_la_borne_exacte():
    out = filter_period(_df(), since="2026-08-20")
    assert list(out["time"])[0] == "2026-08-20 00:00:00"   # la ligne PILE a la borne
    assert len(out) == 4


def test_until_date_seule_inclut_toute_la_journee():
    out = filter_period(_df(), until="2026-08-20")
    assert list(out["time"]) == ["2026-08-19 23:59:59", "2026-08-20 00:00:00",
                                 "2026-08-20 12:00:00"]


def test_until_avec_heure_est_inclusif_a_la_seconde():
    out = filter_period(_df(), until="2026-08-20 12:00:00")
    assert list(out["time"])[-1] == "2026-08-20 12:00:00"
    assert len(out) == 3


def test_since_et_until_combines():
    out = filter_period(_df(), since="2026-08-20", until="2026-08-21")
    assert len(out) == 3


def test_fenetre_vide_ne_plante_pas_et_le_resume_le_dit():
    out = filter_period(_df(), since="2027-01-01")
    assert len(out) == 0
    d = summarize(out, since="2027-01-01", n_total=5)
    assert d["n_cycles"] == 0 and d["n_trades"] == 0
    assert d["total_return"] == 0.0 and d["max_drawdown"] == 0.0
    txt = format_summary(d)                       # ne leve pas
    assert "Aucun cycle dans cette fenetre" in txt


def test_sans_filtre_le_dataframe_est_rendu_tel_quel():
    """NON-REGRESSION : aucune option -> aucun filtrage, aucune ligne perdue."""
    df = _df()
    assert filter_period(df, None, None) is df


def test_le_resume_annonce_la_fenetre_et_le_total():
    df = _df()
    sub = filter_period(df, since="2026-08-20", until="2026-08-21")
    txt = format_summary(summarize(sub, since="2026-08-20", until="2026-08-21",
                                   n_total=len(df)))
    assert "Fenetre" in txt
    assert "2026-08-20" in txt and "2026-08-21" in txt
    assert "3 cycles retenus sur 5 au total" in txt


def test_sans_filtre_le_resume_ne_montre_aucune_ligne_fenetre():
    """NON-REGRESSION : rendu par defaut strictement inchange."""
    txt = format_summary(summarize(_df()))
    assert "Fenetre" not in txt
    assert "Periode      : 2026-08-19 23:59:59 -> 2026-08-22 08:00:00" in txt


def test_summarize_reste_appelable_avec_le_seul_dataframe():
    """Les appelants existants (web) passent summarize(df) : signature preservee."""
    d = summarize(_df())
    assert d["n_cycles"] == 5 and d["n_cycles_total"] == 5
    assert d["filter_since"] is None and d["filter_until"] is None


def test_cmd_stats_filtre_par_date_de_bout_en_bout(tmp_path, capsys):
    csv = tmp_path / "s.csv"
    _df().to_csv(csv, index=False)
    args = main.build_parser().parse_args(
        ["stats", "--file", str(csv), "--since", "2026-08-21"])
    main.cmd_stats(args)
    out = capsys.readouterr().out
    assert "2 cycles retenus sur 5 au total" in out


def test_cmd_stats_sans_option_est_inchange(tmp_path, capsys):
    csv = tmp_path / "s.csv"
    _df().to_csv(csv, index=False)
    main.cmd_stats(main.build_parser().parse_args(["stats", "--file", str(csv)]))
    out = capsys.readouterr().out
    assert "Fenetre" not in out and "Cycles       : 5" in out


def test_cmd_stats_date_invalide_sort_avec_un_message_clair(tmp_path):
    csv = tmp_path / "s.csv"
    _df().to_csv(csv, index=False)
    args = main.build_parser().parse_args(
        ["stats", "--file", str(csv), "--since", "hier"])
    with pytest.raises(SystemExit) as e:
        main.cmd_stats(args)
    assert "Date invalide" in str(e.value)
