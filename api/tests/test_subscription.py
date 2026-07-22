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
