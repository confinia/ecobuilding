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
    sh = (ROOT / "deploy/kc-smtp.sh").read_text()
    assert "verifyEmail=true" in sh            # registration confirmation flow
    assert "smtpServer.password=$SMTP_PASSWORD" in sh  # creds from secrets.env
    deploy = (ROOT / "deploy/deploy.sh").read_text()
    assert "kc-smtp.sh" in deploy              # applied on every deploy
    assert "set -a; . deploy/secrets.env" in deploy  # compose substitution source


@pytest.mark.skip(reason="e2e email delivery: needs live SMTP creds + a mailbox check")
def test_registration_email_delivered_e2e():
    """Register a throwaway user on sandbox -> a verification email arrives
    from alert@confinia.io. Manual/e2e only; never faked (rule 9)."""
