"""End-to-end checks for the isolated sandbox environment (issue #90).

Validates the registration workflow plumbing against the live sandbox, through
the public edge. Opt-in: set SANDBOX_E2E to run.

    SANDBOX_E2E=1 ./deploy/test.sh

Skipped (never faked) otherwise, so the hermetic unit suite stays offline.
The pro-plan (Polar sandbox) half lives in test_polar.py and is un-skipped once
the sandbox Polar organization credentials are provisioned.
"""

import os

import httpx
import pytest

APP = os.environ.get("SANDBOX_APP_URL", "https://sandbox.ecobuilding.confinia.io")
API = os.environ.get("SANDBOX_API_URL", "https://sandbox.api.ecobuilding.confinia.io")
REALM = "sandbox-ecobuilding"
ISSUER = f"{APP}/auth/realms/{REALM}"

pytestmark = pytest.mark.skipif(
    not os.environ.get("SANDBOX_E2E"), reason="set SANDBOX_E2E to run the sandbox e2e checks"
)


def test_sandbox_realm_issuer_is_isolated():
    r = httpx.get(f"{ISSUER}/.well-known/openid-configuration", timeout=20)
    assert r.status_code == 200, r.text
    assert r.json()["issuer"] == ISSUER  # isolated from prod's "confinia" realm


def test_registration_flow_reachable():
    # Start of the browser sign-up flow; a 200/302 (not 404/5xx) proves the
    # realm + public client are wired for self-registration.
    r = httpx.get(
        f"{ISSUER}/protocol/openid-connect/registrations",
        params={"client_id": "ecobuilding-web", "response_type": "code",
                "scope": "openid", "redirect_uri": f"{APP}/"},
        follow_redirects=False, timeout=20,
    )
    assert r.status_code in (200, 302), r.status_code


def test_frontend_targets_sandbox_realm():
    r = httpx.get(f"{APP}/env.js", timeout=20)
    assert r.status_code == 200
    assert REALM in r.text  # shared image, sandbox override mounted


def test_me_requires_auth():
    r = httpx.get(f"{API}/v1/me", timeout=20)
    assert r.status_code == 401  # auth enforced against the sandbox realm


@pytest.mark.skipif(
    not os.environ.get("SANDBOX_TEST_TOKEN"),
    reason="set SANDBOX_TEST_TOKEN (a token from a real sandbox sign-up) to assert the org claim",
)
def test_org_claim_reaches_api():
    # Final proof of the registration -> organization -> `org` claim chain, using
    # a token obtained from an interactive sign-up on the sandbox realm.
    tok = os.environ["SANDBOX_TEST_TOKEN"]
    r = httpx.get(f"{API}/v1/me", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json().get("org"), "org claim missing from /v1/me"
