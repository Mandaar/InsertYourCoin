"""
Garde-fou HOLDOUT (incident #9 du 2026-09-01).

Le 2026-09-01, `backtest --timeframe 1d --days 730` (2024-09-11 -> 2026-08-31) a
recouvert INTEGRALEMENT le holdout ETH de l'etude #5 (frontiere 2024-10) sans
qu'aucun message ne soit affiche : `backtest`/`compare`/`optimize` ignoraient
totalement la notion de holdout. Ces tests verrouillent le garde-fou :

- la frontiere vient d'UNE source (`holdout_split` applique au registre gele) et
  colle a ce que documente l'etude #5 ;
- recouvrement total ou PARTIEL -> refus par defaut, avec fraction et dates ;
- fenetre hors zone ou actif sans holdout declare -> AUCUN bruit ;
- `--use-holdout` -> passe outre ET laisse une trace ;
- `walkforward --holdout` : comportement strictement inchange.

Aucun reseau, aucune cle API (l'exchange et le chargement sont neutralises).
"""
import types

import pandas as pd
import pytest

import config
import main
from conftest import make_ohlcv
from trading import optimizer as opt


# --------------------------------------------------------------------------- #
#  Outils : fenetres synthetiques + args comme ceux du vrai parser             #
# --------------------------------------------------------------------------- #
def _window(start, periods, tz="UTC"):
    """DataFrame OHLCV daily de `periods` bougies a partir de `start`."""
    df = make_ohlcv([100.0 + i for i in range(periods)], start=start)
    return df if tz else df.tz_localize(None)


def _args(cmd="backtest", **over):
    """Args PARSES par le vrai parser (donc avec les vrais defauts, dont
    use_holdout=False) -- pas un faux namespace qui pourrait diverger."""
    argv = [cmd] + list(over.pop("argv", []))
    ns = main.build_parser().parse_args(argv)
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture
def offline(monkeypatch):
    """Neutralise reseau + chargement : `_load_data` rend la fenetre voulue."""
    monkeypatch.setattr(main, "KrakenExchange", lambda *a, **k: object())

    def install(df):
        monkeypatch.setattr(main, "_load_data",
                            lambda *a, **k: df)
        return df
    return install


# --------------------------------------------------------------------------- #
#  1. La frontiere : UNE source, et elle colle a l'etude #5                    #
# --------------------------------------------------------------------------- #
def test_la_frontiere_est_celle_documentee_par_letude_5():
    """ETUDE #5 : recherche BTC/ETH 2017-08-17 -> 2024-10-02 ; SOL -> 2025-05-08.
    La premiere bougie RESERVEE est donc le lendemain. Ce test verrouille le
    registre gele de config.py contre le document qui l'a produit."""
    assert opt.holdout_start("ETH/USD") == pd.Timestamp("2024-10-03")
    assert opt.holdout_start("BTC/USD") == pd.Timestamp("2024-10-03")
    assert opt.holdout_start("SOL/USD") == pd.Timestamp("2025-05-09")


def test_la_frontiere_est_calculee_par_holdout_split_pas_recopiee():
    """Changer le % de holdout DOIT deplacer la frontiere : la date n'est nulle
    part en dur, elle sort de holdout_split (source unique, comme walkforward)."""
    ref = {"ETH": {"start": "2020-01-01", "bars": 1000, "timeframe": "1d"}}
    cut = opt.holdout_split(1000, 0.20)
    attendu = pd.date_range("2020-01-01", periods=1000, freq=pd.Timedelta("1D"))[cut]
    assert opt.holdout_start("ETH/USD", holdout_pct=20, references=ref) == attendu
    assert opt.holdout_start("ETH/USD", holdout_pct=50, references=ref) \
        == pd.Timestamp("2020-01-01") + pd.Timedelta(days=opt.holdout_split(1000, 0.5))


def test_la_paire_de_cotation_ne_change_pas_lactif_reserve():
    """ETH/USDT (recherche Binance) et ETH/USD (execution Kraken) = meme actif,
    memes bougies reservees. C'est le coeur de l'incident #9 (holdout gele sur
    binance, entame par un backtest kraken)."""
    for sym in ("ETH/USD", "eth/usdt", "ETH/USD:USD"):
        assert opt.holdout_start(sym) == pd.Timestamp("2024-10-03")


def test_actif_sans_holdout_declare_nest_pas_concerne():
    assert opt.holdout_start("DOGE/USD") is None
    assert opt.holdout_overlap(_window("2026-01-01", 30).index, "DOGE/USD") is None


# --------------------------------------------------------------------------- #
#  2. Detection du recouvrement (total ET partiel)                            #
# --------------------------------------------------------------------------- #
def test_recouvrement_total_detecte_avec_dates_et_fraction():
    """La fenetre exacte de l'incident #9 : 730 bougies daily a partir du
    2024-09-11 -- 100% apres la frontiere sauf les 22 premieres bougies."""
    df = _window("2024-09-11", 730)
    ov = opt.holdout_overlap(df.index, "ETH/USD")
    assert ov is not None
    assert ov["holdout_start"] == pd.Timestamp("2024-10-03", tz="UTC")
    assert ov["holdout_first"] == pd.Timestamp("2024-10-03", tz="UTC")
    assert ov["n_holdout"] == 730 - 22          # 2024-09-11 -> 2024-10-02 = 22 bougies
    assert ov["frac"] == pytest.approx((730 - 22) / 730)


def test_recouvrement_PARTIEL_detecte():
    """Cas piege : la fenetre est majoritairement propre, seules les 10 dernieres
    bougies entrent dans la zone reservee. Doit etre vu comme le cas total."""
    df = _window("2023-10-01", 378)             # se termine le 2024-10-12
    ov = opt.holdout_overlap(df.index, "ETH/USD")
    assert ov is not None
    assert ov["n_holdout"] == 10
    assert 0 < ov["frac"] < 0.03


def test_fenetre_entierement_avant_la_frontiere_ne_signale_rien():
    df = _window("2022-01-01", 500)             # se termine bien avant 2024-10-03
    assert opt.holdout_overlap(df.index, "ETH/USD") is None


def test_index_sans_fuseau_horaire_traite_comme_les_autres():
    df = _window("2024-09-11", 730, tz=None)
    ov = opt.holdout_overlap(df.index, "ETH/USD")
    assert ov is not None and ov["n_holdout"] == 708


def test_message_donne_la_fraction_et_les_dates_exactes():
    ov = opt.holdout_overlap(_window("2024-09-11", 730).index, "ETH/USD")
    msg = opt.format_holdout_overlap(ov, command="backtest")
    assert "REFUS" in msg and "HOLDOUT" in msg
    assert "2024-10-03" in msg                  # debut de la zone reservee
    assert "2024-09-11" in msg                  # debut de la fenetre demandee
    assert "97.0%" in msg                       # 708/730
    assert "--use-holdout" in msg               # la sortie est dite


# --------------------------------------------------------------------------- #
#  3. Cote CLI : refus par defaut, contournement explicite et TRACE            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cmd", ["backtest", "compare", "optimize"])
def test_les_trois_commandes_refusent_par_defaut(cmd, offline, capsys):
    """Incident #9 : ces trois commandes prenaient le holdout SANS UN MOT."""
    offline(_window("2024-09-11", 730))
    args = _args(cmd)
    args.symbol = "ETH/USD"
    with pytest.raises(SystemExit) as e:
        {"backtest": main.cmd_backtest, "compare": main.cmd_compare,
         "optimize": main.cmd_optimize}[cmd](args)
    assert "HOLDOUT" in str(e.value) and cmd in str(e.value)
    # rien n'a ete calcule ni affiche : on s'arrete AVANT de regarder les donnees
    assert capsys.readouterr().out.strip() == ""


def test_aucun_bruit_quand_la_fenetre_ne_touche_pas_au_holdout(offline, capsys):
    offline(_window("2022-01-01", 500))
    args = _args("backtest")
    args.symbol = "ETH/USD"
    main.cmd_backtest(args)                     # ne leve pas
    sortie = capsys.readouterr().out
    assert "HOLDOUT" not in sortie and "holdout" not in sortie
    assert "Rendement" in sortie or "rendement" in sortie.lower()


def test_use_holdout_passe_outre_et_laisse_une_trace(offline, capsys, tmp_path,
                                                     monkeypatch):
    monkeypatch.chdir(tmp_path)
    offline(_window("2024-09-11", 730))
    args = _args("backtest", argv=["--use-holdout"])
    args.symbol = "ETH/USD"

    main.cmd_backtest(args)                     # ne leve pas : decision assumee

    sortie = capsys.readouterr().out
    assert "HOLDOUT UTILISE VOLONTAIREMENT" in sortie
    journal = tmp_path / config.HOLDOUT_USAGE_LOG
    assert journal.exists()
    ligne = journal.read_text(encoding="utf-8").strip()
    assert "backtest" in ligne and "ETH/USD" in ligne
    assert "2024-10-03" in ligne and "708/730" in ligne


def test_la_trace_est_append_only(tmp_path):
    ov = opt.holdout_overlap(_window("2024-09-11", 730).index, "ETH/USD")
    p = tmp_path / "usage.log"
    p.write_text("DEJA LA\n", encoding="utf-8")
    opt.trace_holdout_use(ov, command="backtest", path=p)
    opt.trace_holdout_use(ov, command="optimize", path=p)
    lignes = p.read_text(encoding="utf-8").splitlines()
    assert lignes[0] == "DEJA LA"               # rien d'ecrase
    assert len(lignes) == 3


def test_le_drapeau_existe_sur_les_trois_commandes_et_pas_ailleurs():
    p = main.build_parser()
    for cmd in ("backtest", "compare", "optimize"):
        assert p.parse_args([cmd]).use_holdout is False
        assert p.parse_args([cmd, "--use-holdout"]).use_holdout is True
    # walkforward garde SON --holdout (pourcentage), sans drapeau de contournement
    wf = p.parse_args(["walkforward", "--holdout", "20"])
    assert wf.holdout == 20 and not hasattr(wf, "use_holdout")


# --------------------------------------------------------------------------- #
#  4. NON-REGRESSION : walkforward --holdout strictement inchange              #
# --------------------------------------------------------------------------- #
def test_walkforward_holdout_inchange_sur_une_fenetre_qui_couvre_le_holdout(
        offline, capsys):
    """`walkforward --holdout 20` retire lui-meme la zone reservee : il ne doit
    ni refuser, ni afficher le bandeau du garde-fou, ni changer son message."""
    offline(_window("2024-09-11", 730))
    args = main.build_parser().parse_args(
        ["walkforward", "--holdout", "20", "--fixed", "fast=10,slow=30",
         "--windows", "2"])
    args.symbol = "ETH/USD"

    main.cmd_walkforward(args)                  # ne leve pas

    sortie = capsys.readouterr().out
    assert "Holdout reserve : 146 bougies (20% recents)" in sortie
    assert "REFUS" not in sortie and "--use-holdout" not in sortie


def test_walkforward_sans_holdout_reste_silencieux_comme_avant(offline, capsys):
    """Perimetre assume : le garde-fou n'a PAS ete cable sur walkforward (qui a
    deja sa propre notion de holdout). Ce test fige ce choix -- si un jour on
    l'y cable, il faudra le decider explicitement, pas par accident."""
    offline(_window("2024-09-11", 300))
    args = main.build_parser().parse_args(
        ["walkforward", "--fixed", "fast=10,slow=30", "--windows", "2"])
    args.symbol = "ETH/USD"
    main.cmd_walkforward(args)
    assert "REFUS" not in capsys.readouterr().out
