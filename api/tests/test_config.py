"""Config-as-code assertions (#128): the email/alerting setup must live entirely
in versioned files — compose env, Grafana provisioning, kcadm script. These
tests pin the wiring so a UI-only or hand-edited config can't silently replace
it. They need the repo root (deploy/test.sh mounts it; skipped otherwise)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
needs_repo = pytest.mark.skipif(
    not (ROOT / "monitoring_stack").is_dir(),
    reason="repo root not available (api-only checkout)",
)


@needs_repo
def test_grafana_smtp_is_code():
    compose = (ROOT / "monitoring_stack/docker-compose.yml").read_text()
    for key in ("GF_SMTP_ENABLED", "GF_SMTP_HOST", "GF_SMTP_USER",
                "GF_SMTP_PASSWORD", "GF_SMTP_FROM_ADDRESS"):
        assert key in compose, f"{key} missing from monitoring compose"
    # Secrets stay in secrets.env: compose only substitutes, never hardcodes.
    assert "${SMTP_PASSWORD" in compose


@needs_repo
def test_grafana_alerting_provisioned_as_code():
    y = (ROOT / "monitoring/grafana-shared/provisioning/alerting/ops-email.yaml").read_text()
    assert "contactPoints:" in y and "type: email" in y
    assert "contact@confinia.io" in y          # ops recipient (redirect-managed)
    assert "policies:" in y and "receiver: ops-email" in y
    assert "datasourceUid: prometheus" in y    # rule pinned to the stable uid
    ds = (ROOT / "monitoring/grafana-shared/provisioning/datasources/prometheus.yaml").read_text()
    assert "uid: prometheus" in ds


@needs_repo
def test_keycloak_email_is_code():
    """Keycloak email as code, two versioned layers: realm-confinia.json is the
    SAFE bootstrap (SMTP sans password, verifyEmail off — a fresh import can
    never strand registrations), kc-smtp.sh is the reconciler that injects the
    secret and flips verifyEmail once the relay accepts the creds."""
    import json
    realm = json.loads((ROOT / "auth_stack/realm-confinia.json").read_text())
    smtp = realm.get("smtpServer") or {}
    assert smtp.get("host") == "ssl0.ovh.net" and smtp.get("from") == "alert@confinia.io"
    assert "password" not in smtp              # secrets never in git
    assert realm.get("verifyEmail") is False   # safe bootstrap; script promotes
    assert realm.get("registrationAllowed") is True
    sh = (ROOT / "deploy/kc-smtp.sh").read_text()
    assert "verifyEmail=true" in sh            # registration confirmation flow
    assert "smtpServer.password=$SMTP_PASSWORD" in sh  # creds from secrets.env
    assert "pre-flight" in sh.lower()          # never enabled with bad creds
    stack = (ROOT / "deploy/stack-up.sh").read_text()
    assert "kc-smtp.sh" in stack               # applied on every deploy
    assert "set -a; . deploy/secrets.env" in stack  # compose substitution source


@needs_repo
def test_keycloak_client_uris_are_code():
    """The live client's URI surface is replayed from realm-confinia.json on
    every deploy (kc-client.sh) — pre-prod is staging., next. must not exist
    anywhere (rule 12)."""
    import json
    realm = json.loads((ROOT / "auth_stack/realm-confinia.json").read_text())
    client = next(c for c in realm["clients"] if c["clientId"] == "ecobuilding-web")
    assert any("staging.ecobuilding" in u for u in client["redirectUris"])
    assert not any("next.ecobuilding" in u for u in client["redirectUris"])
    sh = (ROOT / "deploy/kc-client.sh").read_text()
    assert "realm-confinia.json" in sh and "redirectUris" in sh
    assert "kc-client.sh" in (ROOT / "deploy/stack-up.sh").read_text()


@needs_repo
def test_cicd_pipeline_is_code():
    """Rule 14: the pipeline mirrors code state — PR→sandbox, main→staging,
    dispatch→promote — on the VM's own runner; the wrappers stay break-glass."""
    wf = ROOT / ".github/workflows"
    sandbox = (wf / "sandbox.yml").read_text()
    staging = (wf / "staging.yml").read_text()
    promote = (wf / "promote.yml").read_text()
    assert "pull_request" in sandbox and "deploy/sandbox.sh" in sandbox
    assert "main" in staging and "deploy/stack-up.sh" in staging and "deploy/test.sh" in staging
    assert "workflow_dispatch" in promote and "deploy/promote-up.sh" in promote
    for y in (sandbox, staging, promote):
        assert "self-hosted" in y and "ecobuilding" in y
        assert "group: vm-deploy" in y          # one VM: deploys serialized
    assert "stack-up.sh" in (ROOT / "deploy/deploy.sh").read_text()      # wrapper
    assert "promote-up.sh" in (ROOT / "deploy/promote.sh").read_text()   # wrapper
    sandbox_sh = (ROOT / "deploy/sandbox.sh").read_text()
    # The sandbox script must never hand-edit the platform edge again
    # (reverted-on-redeploy + duplicate-site-block footgun).
    assert ">> ~/projects/platform" not in sandbox_sh
    # ...and must force-recreate: podman-compose keeps a running container on
    # a rebuilt image, silently serving stale code otherwise.
    assert "--force-recreate" in sandbox_sh


@pytest.mark.skip(reason="e2e email delivery: needs live SMTP creds + a mailbox check")
def test_registration_email_delivered_e2e():
    """Register a throwaway user on sandbox -> a verification email arrives
    from alert@confinia.io. Manual/e2e only; never faked (rule 9)."""
