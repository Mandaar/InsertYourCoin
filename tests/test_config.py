"""
Garde-fous de configuration (tests de non-regression).
"""
import config


def test_fee_ne_sous_estime_pas_le_taker_kraken():
    # BUG-003 : config.FEE doit refleter le taker Kraken reel (palier de base ~0.40%).
    # Sous-estimer le frais flatte TOUS les backtests et le paper (conclusions optimistes).
    # Ne jamais redescendre sous 0.40% sans passer explicitement en ordres LIMIT (maker).
    assert config.FEE >= 0.004


def test_verify_ssl_reste_actif():
    # Garde-fou projet : la verification SSL ne doit jamais etre desactivee ici
    # (le contournement n'etait qu'un bricolage de bac a sable). Cf. CLAUDE.md.
    assert config.VERIFY_SSL is True
