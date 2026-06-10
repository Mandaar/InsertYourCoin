"""
Garde-fous de configuration et de sortie (tests de non-regression).
"""
from pathlib import Path

import pytest

import config


def test_fee_ne_sous_estime_pas_le_taker_kraken():
    # BUG-003 : config.FEE doit refleter le taker Kraken reel du comportement simule
    # (ordres MARCHE). Taker palier de base = 0.80% des le 9 juillet 2026 (0.40% avant).
    # On developpe pour trader dans le futur -> on ne descend pas sous le taker FUTUR.
    # Sous-estimer le frais flatte TOUS les backtests/paper. (Si passage en ordres LIMIT
    # = maker 0.40%, ajuster CONSCIEMMENT ce seuil a 0.004.)
    assert config.FEE >= 0.008


def test_fee_pointe_sur_le_taker():
    # Brique 2 : le moteur simule des ordres MARCHE (taker) -> config.FEE doit
    # pointer sur le taker. Garde-fou anti-derive (on ne fait pas pointer FEE sur le
    # maker par megarde, ce qui flatterait tous les backtests).
    assert config.FEE == config.FEE_TAKER


def test_maker_moins_cher_que_taker():
    # Brique 2 : la grille Kraken (des le 9/07/2026) a maker < taker. Si un jour on
    # passe en ordres LIMIT (maker), c'est ce frais reduit qu'on utilisera CONSCIEMMENT.
    assert config.FEE_MAKER < config.FEE_TAKER
    assert config.FEE_TAKER == pytest.approx(0.0080)
    assert config.FEE_MAKER == pytest.approx(0.0040)


def test_slippage_defini_et_positif():
    # Brique 1 (B6) : le slippage (cout d'execution defavorable) doit etre defini et
    # strictement positif par defaut (les resultats etaient optimistes sans lui).
    assert hasattr(config, "SLIPPAGE")
    assert config.SLIPPAGE > 0.0


def test_verify_ssl_reste_actif():
    # Garde-fou projet : la verification SSL ne doit jamais etre desactivee ici
    # (le contournement n'etait qu'un bricolage de bac a sable). Cf. CLAUDE.md.
    assert config.VERIFY_SSL is True


def test_main_force_stdout_utf8():
    # BUG-004 : main DOIT forcer stdout/stderr en UTF-8, sinon la console Windows
    # (cp1252) leve UnicodeEncodeError sur les accents/symboles des sorties
    # (sigma de Bollinger, fleches/emoji du verdict). Garde-fou anti-suppression.
    src = Path(__file__).resolve().parent.parent.joinpath("main.py").read_text(encoding="utf-8")
    assert 'reconfigure(encoding="utf-8"' in src
