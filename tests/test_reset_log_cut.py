"""
La COUPURE : `paper --reset` archive AUSSI le journal des ordres.

Avant : `--reset` archivait `paper_state.json` et `paper_stats.csv` mais laissait
`paper_trades.log` s'empiler -- apres une remise a zero, le journal melangeait
l'ancienne configuration et la nouvelle, sans coupure lisible. Or c'est justement
dans ce fichier qu'on relit ce qui s'est passe.

Exigence verrouillee ici : les TROIS archives portent le MEME horodatage (sans
quoi on ne peut pas reconstituer un ensemble coherent), aucun contenu n'est
altere, et un journal absent (paper jamais lance) n'est pas une erreur.

Aucun reseau, aucune cle API : tout passe par tmp_path.
"""
import datetime as dt
import json
import re

import config
import main
from trading import reset as reset_mod


WHEN = dt.datetime(2026, 9, 2, 9, 15, 0)
STAMP = "2026-09-02T09-15-00"


def _seed(tmp_path, log=True):
    st = tmp_path / "paper_state.json"
    cs = tmp_path / "paper_stats.csv"
    lg = tmp_path / "paper_trades.log"
    st.write_text('{"cash": 1234.0}')
    cs.write_text("time,equity\n2026-09-01 00:00:00,100\n")
    if log:
        lg.write_text("[2026-09-01] ACHAT 0.1 ETH a 3000\n[2026-09-01] VENTE\n",
                      encoding="utf-8")
    return st, cs, lg


# --------------------------------------------------------------------------- #
#  1. Les TROIS fichiers, le MEME horodatage                                   #
# --------------------------------------------------------------------------- #
def test_le_journal_est_archive_avec_letat_et_les_stats(tmp_path):
    st, cs, lg = _seed(tmp_path)

    res = reset_mod.reset_paper(st, cs, when=WHEN, log_file=lg)

    attendus = [tmp_path / f"paper_state.{STAMP}.json",
                tmp_path / f"paper_stats.{STAMP}.csv",
                tmp_path / f"paper_trades.{STAMP}.log"]
    assert [d for _s, d in res["archived"]] == attendus
    assert all(a.exists() for a in attendus)
    assert not lg.exists()                       # le journal repart VIDE (coupure)


def test_les_trois_archives_portent_exactement_le_meme_horodatage(tmp_path):
    """Sans horodatage commun, impossible de reconstituer un ensemble coherent."""
    st, cs, lg = _seed(tmp_path)

    res = reset_mod.reset_paper(st, cs, when=WHEN, log_file=lg)

    stamps = {re.match(r"paper_\w+\.(.+)\.\w+$", d.name).group(1)
              for _s, d in res["archived"]}
    assert stamps == {STAMP}                     # UN seul horodatage pour les 3


def test_les_archives_sont_identiques_aux_originaux(tmp_path):
    st, cs, lg = _seed(tmp_path)
    avant = (st.read_text(), cs.read_text(), lg.read_text(encoding="utf-8"))

    reset_mod.reset_paper(st, cs, when=WHEN, log_file=lg)

    apres = ((tmp_path / f"paper_state.{STAMP}.json").read_text(),
             (tmp_path / f"paper_stats.{STAMP}.csv").read_text(),
             (tmp_path / f"paper_trades.{STAMP}.log").read_text(encoding="utf-8"))
    assert apres == avant                        # RENAME : rien n'est reecrit


def test_journal_absent_nest_pas_une_erreur(tmp_path):
    """Paper jamais lance : pas de log a archiver, le reset se fait quand meme."""
    st, cs, lg = _seed(tmp_path, log=False)
    assert not lg.exists()

    res = reset_mod.reset_paper(st, cs, when=WHEN, log_file=lg)

    assert [d.name for _s, d in res["archived"]] == [
        f"paper_state.{STAMP}.json", f"paper_stats.{STAMP}.csv"]
    assert json.loads(st.read_text())["cash"] == config.INITIAL_CAPITAL


def test_une_archive_de_journal_existante_nest_jamais_ecrasee(tmp_path):
    st, cs, lg = _seed(tmp_path)
    deja = tmp_path / f"paper_trades.{STAMP}.log"
    deja.write_text("ARCHIVE PRECEDENTE", encoding="utf-8")

    reset_mod.reset_paper(st, cs, when=WHEN, log_file=lg)

    assert deja.read_text(encoding="utf-8") == "ARCHIVE PRECEDENTE"
    assert (tmp_path / f"paper_trades.{STAMP}-2.log").exists()


def test_le_resume_affiche_les_trois_archives(tmp_path):
    st, cs, lg = _seed(tmp_path)
    txt = reset_mod.format_reset(reset_mod.reset_paper(st, cs, when=WHEN, log_file=lg))
    assert txt.count("archive :") == 3
    assert "paper_trades." in txt


def test_le_journal_par_defaut_est_resolu_A_COTE_de_letat(tmp_path):
    """GARDE-FOU (incident du 2026-09-02) : un defaut litteral 'paper_trades.log'
    se resout contre le REPERTOIRE COURANT -- un reset sur des fichiers de test
    est alle archiver le journal du paper REELLEMENT EN TRAIN DE TOURNER a la
    racine du depot. Le defaut suit desormais l'etat."""
    st, cs, lg = _seed(tmp_path)

    res = reset_mod.reset_paper(st, cs, when=WHEN)        # aucun log_file passe

    assert reset_mod.resolve_log_file(st) == lg
    assert [d.name for _s, d in res["archived"]][-1] == f"paper_trades.{STAMP}.log"
    assert not lg.exists()


def test_log_file_none_desactive_larchivage_du_journal(tmp_path):
    """NON-REGRESSION : les appels historiques a 2 fichiers restent possibles."""
    st, cs, lg = _seed(tmp_path)
    res = reset_mod.reset_paper(st, cs, when=WHEN, log_file=None)
    assert len(res["archived"]) == 2
    assert lg.exists()                           # intact, rien touche


# --------------------------------------------------------------------------- #
#  1bis. Deux poches (eth_/btc_) dans le MEME dossier : LOT B (constat C05)    #
# --------------------------------------------------------------------------- #
def test_le_nom_du_journal_se_deduit_du_prefixe_de_letat(tmp_path):
    eth_state = tmp_path / "eth_state.json"
    btc_state = tmp_path / "btc_state.json"
    assert reset_mod.resolve_log_file(eth_state) == tmp_path / "eth_trades.log"
    assert reset_mod.resolve_log_file(btc_state) == tmp_path / "btc_trades.log"


def test_deux_poches_dans_le_meme_dossier_ont_deux_journaux_distincts(tmp_path):
    eth_state = tmp_path / "eth_state.json"
    btc_state = tmp_path / "btc_state.json"
    eth_state.write_text('{"cash": 1.0}')
    btc_state.write_text('{"cash": 2.0}')
    (tmp_path / "eth_stats.csv").write_text("time,equity\n")
    (tmp_path / "btc_stats.csv").write_text("time,equity\n")
    eth_log = reset_mod.resolve_log_file(eth_state)
    btc_log = reset_mod.resolve_log_file(btc_state)
    eth_log.write_text("[eth] ACHAT\n", encoding="utf-8")
    btc_log.write_text("[btc] ACHAT\n", encoding="utf-8")

    assert eth_log != btc_log
    assert eth_log.name == "eth_trades.log" and btc_log.name == "btc_trades.log"


def test_reset_dune_poche_ne_touche_aucun_fichier_de_lautre(tmp_path):
    eth_state = tmp_path / "eth_state.json"
    btc_state = tmp_path / "btc_state.json"
    eth_stats = tmp_path / "eth_stats.csv"
    btc_stats = tmp_path / "btc_stats.csv"
    eth_state.write_text('{"cash": 1.0}')
    btc_state.write_text('{"cash": 2.0}')
    eth_stats.write_text("time,equity\n")
    btc_stats.write_text("time,equity\n")
    btc_log = reset_mod.resolve_log_file(btc_state)
    btc_log.write_text("[btc] ACHAT jamais touche\n", encoding="utf-8")
    btc_before = btc_log.read_text(encoding="utf-8")

    reset_mod.reset_paper(eth_state, eth_stats, when=WHEN,
                          log_file=reset_mod.resolve_log_file(eth_state))

    assert btc_state.exists() and json.loads(btc_state.read_text()) == {"cash": 2.0}
    assert btc_stats.read_text() == "time,equity\n"
    assert btc_log.exists() and btc_log.read_text(encoding="utf-8") == btc_before


def test_letat_par_defaut_paper_state_garde_le_journal_par_defaut(tmp_path):
    """NON-REGRESSION explicite : le prefixe 'paper' (etat historique) rend
    exactement le meme resultat qu'avant ce correctif."""
    st = tmp_path / "paper_state.json"
    assert reset_mod.resolve_log_file(st) == tmp_path / reset_mod.DEFAULT_LOG_NAME
    assert reset_mod._log_name_for_state(st) == "paper_trades.log"


# --------------------------------------------------------------------------- #
#  2. Chemin REEL du CLI                                                       #
# --------------------------------------------------------------------------- #
def test_cmd_paper_reset_coupe_aussi_le_journal(tmp_path, monkeypatch):
    """`paper --reset` du CLI : le journal est resolu A COTE de l'etat et coupe
    avec lui ; le trader ecrit ensuite dans le MEME chemin (pas de divergence)."""
    st, cs, lg = _seed(tmp_path)
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
    assert len(list(tmp_path.glob("paper_trades.*.log"))) == 1   # journal archive
    assert not lg.exists()
    # le trader recoit EXACTEMENT le chemin qui vient d'etre coupe
    assert str(built["log_file"]) == str(lg)


def test_cmd_paper_defaut_le_journal_reste_paper_trades_log(tmp_path, monkeypatch):
    """NON-REGRESSION du defaut : sans --state, c'est bien ./paper_trades.log
    (celui que lit le monitor), pas un chemin invente."""
    built = {}

    class _FakePaper:
        def __init__(self, *a, **kw):
            built.update(kw)

        def run(self):
            pass

    monkeypatch.chdir(tmp_path)                  # aucun fichier reel du depot touche
    monkeypatch.setattr("trading.paper_trader.PaperTrader", _FakePaper)
    monkeypatch.setattr(main, "KrakenExchange", lambda *a, **k: object())
    args = main.build_parser().parse_args(["paper"])

    main.cmd_paper(args)

    assert str(built["log_file"]).replace("\\", "/") == "paper_trades.log"


def test_cmd_paper_poche_eth_recoit_son_propre_journal(tmp_path, monkeypatch):
    """LOT B (deux poches) : `--state .../eth_state.json` donne un journal
    `eth_trades.log`, jamais le `paper_trades.log` d'une autre poche."""
    built = {}

    class _FakePaper:
        def __init__(self, *a, **kw):
            built.update(kw)

        def run(self):
            pass

    monkeypatch.setattr("trading.paper_trader.PaperTrader", _FakePaper)
    monkeypatch.setattr(main, "KrakenExchange", lambda *a, **k: object())
    st = tmp_path / "eth_state.json"
    cs = tmp_path / "eth_stats.csv"
    args = main.build_parser().parse_args(
        ["paper", "--state", str(st), "--stats", str(cs)])

    main.cmd_paper(args)

    assert str(built["log_file"]) == str(tmp_path / "eth_trades.log")


def test_cmd_paper_cree_les_dossiers_parents_de_letat_et_des_stats(tmp_path, monkeypatch):
    """LOT B : les poches vivent sous un dossier neuf (ex. /data/poches/) --
    cmd_paper le cree au besoin plutot que de planter a l'ecriture."""
    built = {}

    class _FakePaper:
        def __init__(self, *a, **kw):
            built.update(kw)

        def run(self):
            pass

    monkeypatch.setattr("trading.paper_trader.PaperTrader", _FakePaper)
    monkeypatch.setattr(main, "KrakenExchange", lambda *a, **k: object())
    sub = tmp_path / "poches"
    assert not sub.exists()
    args = main.build_parser().parse_args(
        ["paper", "--state", str(sub / "eth_state.json"),
         "--stats", str(sub / "eth_stats.csv")])

    main.cmd_paper(args)

    assert sub.is_dir()
