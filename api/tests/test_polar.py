"""Pro account via Polar.sh — hermetic tests for the checkout + webhook flow
(issue #35, validated in the sandbox #90). No network: the Polar webhook is
Standard Webhooks, so we sign payloads locally with a test secret.
"""

import base64
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.main as main

client = TestClient(main.app)

TEST_SECRET = "whsec_" + base64.b64encode(b"ecobuilding-polar-test-secret-01").decode()


def _signed(payload: dict):
    """Return (body_bytes, headers) with a valid Standard Webhooks signature."""
    from standardwebhooks import Webhook
    body = json.dumps(payload).encode()
    msg_id = "msg_test_1"
    ts = datetime.now(timezone.utc)
    sig = Webhook(TEST_SECRET).sign(msg_id, ts, body.decode())
    return body, {
        "webhook-id": msg_id,
        "webhook-timestamp": str(int(ts.timestamp())),
        "webhook-signature": sig,
        "content-type": "application/json",
    }


def _sub_event(etype, sub, status="active"):
    return {"type": etype, "data": {
        "id": "sub_123", "status": status, "product_id": "prod_pro",
        "customer": {"external_id": sub, "email": "e2e@test.io"}}}


def test_checkout_requires_auth():
    assert client.get("/v1/pro/checkout").status_code == 401


def test_checkout_unconfigured_returns_503(monkeypatch):
    monkeypatch.setattr(main, "_decode_token", lambda t: {"sub": "u1", "email": "e@x.io"})
    monkeypatch.setattr(main, "POLAR_ACCESS_TOKEN", "")  # not configured
    r = client.get("/v1/pro/checkout", headers={"Authorization": "Bearer x"})
    assert r.status_code == 503


def test_webhook_signature_enforced(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "POLAR_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setattr(main, "PRO_PATH", str(tmp_path / "pro.json"))
    body, headers = _signed(_sub_event("subscription.active", "u_tamper"))
    headers["webhook-signature"] = "v1,not-a-valid-signature"
    r = client.post("/v1/pro/webhook", content=body, headers=headers)
    assert r.status_code == 401
    assert not main._pro_active("u_tamper")  # nothing provisioned


def test_webhook_provisions_pro(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "POLAR_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setattr(main, "PRO_PATH", str(tmp_path / "pro.json"))
    body, headers = _signed(_sub_event("subscription.active", "u_pro"))
    r = client.post("/v1/pro/webhook", content=body, headers=headers)
    assert r.status_code == 202
    assert main._pro_active("u_pro") is True


def test_cancellation_downgrades(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "POLAR_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setattr(main, "PRO_PATH", str(tmp_path / "pro.json"))
    body, headers = _signed(_sub_event("subscription.active", "u_x"))
    client.post("/v1/pro/webhook", content=body, headers=headers)
    assert main._pro_active("u_x") is True
    body, headers = _signed(_sub_event("subscription.canceled", "u_x", status="canceled"))
    r = client.post("/v1/pro/webhook", content=body, headers=headers)
    assert r.status_code == 202
    assert main._pro_active("u_x") is False


def test_me_reflects_pro_tier(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "PRO_PATH", str(tmp_path / "pro.json"))
    monkeypatch.setattr(main, "_decode_token",
                        lambda t: {"sub": "u_me", "email": "e@x.io", "org": "ACME"})
    main._pro_set("u_me", True)
    r = client.get("/v1/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json()["tier"] == "pro"
