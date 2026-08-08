"""
Tests PURS du store de nonces d'armement (Lot 8, docs/design/LOT8_LIVE_SPEC.md
§5.2) -- trading.live_control.ArmTokenStore. Aucun reseau, aucun serveur.

Invariants testes : usage unique, TTL, lien aux parametres figes a
l'armement (jamais ceux resoumis au start), plafond de tentatives de phrase.
"""
from trading.live_control import ArmTokenStore


def test_nonce_usage_unique():
    store = ArmTokenStore()
    nonce = store.create({"strategy": "sma", "symbol": "ETH/USD"})
    first = store.consume(nonce)
    assert first == {"strategy": "sma", "symbol": "ETH/USD"}
    second = store.consume(nonce)
    assert second is None  # 2e consommation : echoue toujours


def test_nonce_expire_apres_ttl():
    store = ArmTokenStore(ttl_seconds=120)
    t0 = 1_000_000.0
    nonce = store.create({"strategy": "sma"}, now=t0)
    # Toujours valide juste avant le TTL.
    assert store.peek_params(nonce, now=t0 + 119) == {"strategy": "sma"}
    # Expire une fois le TTL depasse.
    assert store.peek_params(nonce, now=t0 + 200) is None
    assert store.consume(nonce, now=t0 + 200) is None


def test_nonce_lie_aux_parametres():
    store = ArmTokenStore()
    original_params = {"strategy": "sma", "symbol": "ETH/USD", "timeframe": "1h"}
    nonce = store.create(original_params)

    # Le start "resoumet" d'autres valeurs -- le store les ignore totalement :
    # consume() ne connait QUE ce qui a ete fige a create().
    swapped_attempt = {"strategy": "tsmom", "symbol": "BTC/USD", "timeframe": "1d"}
    result = store.consume(nonce)
    assert result == original_params
    assert result != swapped_attempt

    # Immutabilite : muter le dict retourne n'affecte pas un futur create/peek.
    nonce2 = store.create(dict(original_params))
    peeked = store.peek_params(nonce2)
    peeked["strategy"] = "MUTATED"
    assert store.peek_params(nonce2)["strategy"] == "sma"


def test_nonce_plafond_tentatives_phrase():
    store = ArmTokenStore(max_attempts=3)
    nonce = store.create({"strategy": "sma"})

    # 1re et 2e phrase fausse : le nonce reste valide (retry autorise).
    assert store.register_failed_phrase(nonce) is True
    assert store.peek_params(nonce) == {"strategy": "sma"}
    assert store.register_failed_phrase(nonce) is True
    assert store.peek_params(nonce) == {"strategy": "sma"}

    # 3e phrase fausse : plafond atteint -> nonce INVALIDE.
    assert store.register_failed_phrase(nonce) is False
    assert store.peek_params(nonce) is None
    assert store.consume(nonce) is None


def test_nonce_inconnu_ou_vide_toujours_invalide():
    store = ArmTokenStore()
    assert store.peek_params("nonce-jamais-cree") is None
    assert store.peek_params(None) is None
    assert store.peek_params("") is None
    assert store.consume("nonce-jamais-cree") is None
    assert store.register_failed_phrase("nonce-jamais-cree") is False
