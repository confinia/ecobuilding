"""Sign-up flow validation (Keycloak IdP, issue #36).

Active now: JWT validation on /v1/me (hermetic, local RSA keypair — no IdP
needed). Still SKIPPED until the corresponding pieces ship: anonymous-cap
tests (#27 metering) and full browser registration (manual checklist in
TEST_SUBSCRIPTION.md).
"""

import time

import pytest
from fastapi.testclient import TestClient

import app.main as main

client = TestClient(main.app)


@pytest.fixture(scope="module")
def rsa_keys():
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


def _token(rsa_keys, **overrides):
    import jwt as pyjwt

    priv, _ = rsa_keys
    claims = {
        "sub": "user-123",
        "email": "clement@example.org",
        "org": "Confinia",
        "iss": main.OIDC_ISSUER,
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    return pyjwt.encode(claims, priv, algorithm="RS256")


def test_me_requires_token():
    assert client.get("/v1/me").status_code == 401


def test_me_rejects_garbage_token():
    r = client.get("/v1/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_me_returns_identity_with_org(rsa_keys, monkeypatch):
    _, pub = rsa_keys
    monkeypatch.setattr(main, "_get_signing_key", lambda token: pub)
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {_token(rsa_keys)}"})
    assert r.status_code == 200
    body = r.json()
    assert body["organization"] == "Confinia"
    assert body["tier"] == "free"


def test_me_rejects_wrong_issuer(rsa_keys, monkeypatch):
    _, pub = rsa_keys
    monkeypatch.setattr(main, "_get_signing_key", lambda token: pub)
    bad = _token(rsa_keys, iss="https://evil.example.org/realm")
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


def test_me_rejects_expired_token(rsa_keys, monkeypatch):
    _, pub = rsa_keys
    monkeypatch.setattr(main, "_get_signing_key", lambda token: pub)
    expired = _token(rsa_keys, exp=int(time.time()) - 60)
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


@pytest.mark.skip(reason="Anonymous daily cap not implemented — issue #27")
def test_anonymous_cap_hints_signup():
    raise NotImplementedError


@pytest.mark.skip(reason="Key provisioning not implemented — issue #27")
def test_key_bypasses_anonymous_cap():
    raise NotImplementedError


def test_le_changement_de_palier_nomme_son_comportement_de_prorata(monkeypatch):
    """#268 — l'intention de facturation ne doit pas dépendre d'un défaut.

    L'appel a longtemps échoué en 403 : Creem traduisait toute erreur serveur
    non reconnue en un 403 générique sans message, ce qui a fait chercher du
    côté de la clé et des portées pendant des jours. La charge utile était
    bonne — vérifié le 2026-08-26, montée ET descente en 200.

    `update_behavior` reste facultatif ; on l'écrit parce qu'un prorata est une
    décision de facturation, pas un détail de transport.
    """
    import app.main as main

    envoye = {}

    class Reponse:
        status_code = 200

        def raise_for_status(self):
            pass

    async def faux_post(url, json=None, headers=None):
        envoye["url"] = url
        envoye["json"] = json
        return Reponse()

    monkeypatch.setattr(main._client, "post", faux_post)
    monkeypatch.setattr(main, "CREEM_API_KEY", "creem_test_x")
    monkeypatch.setattr(main, "PAYMENT_PROVIDER", "creem")
    monkeypatch.setattr(main, "CREEM_PRODUCTS", {"s": "prod_S", "l": "prod_L"})
    monkeypatch.setattr(main, "_creem_find_subscription",
                        lambda email: {"id": "sub_1", "product": {"id": "prod_S"}})
    monkeypatch.setattr(main, "_decode_token",
                        lambda t: {"sub": "kc-1", "email": "a@b.c"})
    monkeypatch.setattr(main, "_pro_set", lambda *a, **k: None)

    from fastapi.testclient import TestClient

    r = TestClient(main.app).post("/v1/pro/upgrade?tier=l",
                                  headers={"Authorization": "Bearer jeton"})
    assert r.status_code == 200, r.text
    assert envoye["url"].endswith("/subscriptions/sub_1/upgrade")
    assert envoye["json"]["product_id"] == "prod_L"
    assert envoye["json"]["update_behavior"] == "proration-charge-immediately"
